import unittest

from app.pubsub.schema_loader import load_schema
from app.pubsub.validator import validate_trade_event_payload
from app.pubsub.topics import TRADE_EVENT_TYPE, TRADE_EVENT_VERSION


_TRADE_SCHEMA_PATH = f"polymarket/{TRADE_EVENT_TYPE}/v{TRADE_EVENT_VERSION}/schema.json"
_TRADE_SCHEMA_TITLE = f"polymarket.{TRADE_EVENT_TYPE}.v{TRADE_EVENT_VERSION}"


class PubSubSchemaTests(unittest.TestCase):
    def test_load_schema_reads_bundled_trade_schema(self) -> None:
        schema = load_schema(_TRADE_SCHEMA_PATH)

        self.assertEqual(schema["title"], _TRADE_SCHEMA_TITLE)
        self.assertFalse(schema["additionalProperties"])

    def test_load_schema_missing_file_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_schema(_TRADE_SCHEMA_PATH.replace("schema.json", "missing.json"))

    def test_validate_trade_event_payload_accepts_valid_payload(self) -> None:
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

        validate_trade_event_payload(payload)

    def test_validate_trade_event_payload_rejects_extra_trade_fields(self) -> None:
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
                "unexpected": True,
            },
        }

        with self.assertRaises(ValueError):
            validate_trade_event_payload(payload)


if __name__ == "__main__":
    unittest.main()