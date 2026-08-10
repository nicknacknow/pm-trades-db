import unittest

from app.trade_payload import canonical_payload, parse_trade_event
from app.pubsub.topics import TRADE_EVENT_TYPE, TRADE_EVENT_VERSION
from app.trade_storage import bootstrap_schema, store_trade


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def execute(self, sql: str, *args: object) -> None:
        self.calls.append((sql, args))


class TradeStorageTests(unittest.IsolatedAsyncioTestCase):
    async def test_bootstrap_schema_executes_table_and_index_statements(self) -> None:
        connection = FakeConnection()

        await bootstrap_schema(connection)  # type: ignore[arg-type]

        self.assertEqual(len(connection.calls), 3)
        self.assertIn("CREATE TABLE IF NOT EXISTS trade_events", connection.calls[0][0])
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_trade_events_received_at", connection.calls[1][0])
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_trade_events_condition_id", connection.calls[2][0])

    async def test_store_trade_persists_normalized_payload(self) -> None:
        connection = FakeConnection()
        payload = {
            "event_type": TRADE_EVENT_TYPE,
            "event_version": TRADE_EVENT_VERSION,
            "trade": {
                "block_number": 1,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "transaction_hash": "0xabcdef",
                "wallet": "0x1234567890abcdef1234567890abcdef12345678",
                "token_id": "1",
                "condition_id": "0x" + "11" * 32,
                "side": 0,
                "maker_amount": 1,
                "taker_amount": 2,
            },
        }

        parsed_payload = parse_trade_event(payload)

        await store_trade(connection, parsed_payload)

        self.assertEqual(len(connection.calls), 1)
        sql, args = connection.calls[0]
        self.assertIn("INSERT INTO trade_events", sql)
        self.assertEqual(args[1], TRADE_EVENT_TYPE)
        self.assertEqual(args[2], TRADE_EVENT_VERSION)
        self.assertEqual(args[3], 1)
        self.assertEqual(args[4].isoformat(), "2026-01-01T00:00:00+00:00")
        self.assertEqual(args[5], "0xabcdef")
        self.assertEqual(args[6], "0x1234567890abcdef1234567890abcdef12345678")
        self.assertEqual(args[7], "1")
        self.assertEqual(args[8], "")       # condition_id defaults to empty
        self.assertEqual(args[9], 0)        # side
        self.assertEqual(args[10], 1)       # maker_amount
        self.assertEqual(args[11], 2)       # taker_amount

    async def test_store_trade_captures_condition_id(self) -> None:
        connection = FakeConnection()
        payload = {
            "event_type": "trade",
            "event_version": "2.0.0",
            "trade": {
                "block_number": 42,
                "timestamp": "2026-01-01T00:00:00+00:00",
                "transaction_hash": "0xdeadbeef",
                "wallet": "0x1234567890abcdef1234567890abcdef12345678",
                "token_id": "2",
                "condition_id": "0x9999999999999999999999999999999999999999999999999999999999999999",
                "side": 1,
                "maker_amount": 10,
                "taker_amount": 20,
            },
        }

        await store_trade(connection, payload)  # type: ignore[arg-type]

        sql, args = connection.calls[0]
        self.assertEqual(args[8], "0x9999999999999999999999999999999999999999999999999999999999999999")
