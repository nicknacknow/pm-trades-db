import unittest

from app.trade_payload import (
    canonical_payload,
    event_id_for_payload,
    parse_trade_event,
    parse_trade_timestamp,
)


class TradePayloadTests(unittest.TestCase):
    def test_canonical_payload_sorts_keys(self) -> None:
        self.assertEqual(canonical_payload({"b": 2, "a": 1}), '{"a":1,"b":2}')

    def test_event_id_for_payload_is_stable(self) -> None:
        payload_one = canonical_payload({"b": 2, "a": 1})
        payload_two = canonical_payload({"a": 1, "b": 2})

        self.assertEqual(event_id_for_payload(payload_one), event_id_for_payload(payload_two))

    def test_parse_trade_timestamp_handles_z_suffix(self) -> None:
        parsed = parse_trade_timestamp("2026-01-01T00:00:00Z")

        self.assertEqual(parsed.isoformat(), "2026-01-01T00:00:00+00:00")

    def test_parse_trade_event_rejects_non_object_trade(self) -> None:
        with self.assertRaises(TypeError):
            parse_trade_event(
                {
                    "event_type": "trade",
                    "event_version": "1.0.0",
                    "trade": "not-an-object",
                }
            )
