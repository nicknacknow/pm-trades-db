import unittest

from prometheus_client import generate_latest

from app.metrics import (
    mark_redis_connected,
    mark_redis_disconnected,
    record_malformed_trade_event,
    record_redis_retry,
    record_trade_stored,
)


class MetricsTests(unittest.TestCase):
    def test_metric_helpers_update_prometheus_state(self) -> None:
        mark_redis_disconnected()
        record_redis_retry()
        record_trade_stored()
        record_malformed_trade_event()
        mark_redis_connected()

        payload = generate_latest().decode("utf-8")

        self.assertIn("pm_trades_db_redis_retries_total 1.0", payload)
        self.assertIn("pm_trades_db_trade_events_stored_total 1.0", payload)
        self.assertIn("pm_trades_db_malformed_trade_events_total 1.0", payload)
        self.assertIn("pm_trades_db_redis_connected 1.0", payload)
