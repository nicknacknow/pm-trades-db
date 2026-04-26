"""Prometheus metrics for pm-trades-db."""

from prometheus_client import Counter, Gauge, start_http_server

from app.settings import METRICS_PORT

REDIS_RETRIES_TOTAL = Counter(
    "pm_trades_db_redis_retries_total",
    "Total Redis reconnect attempts.",
)
REDIS_CONNECTED = Gauge(
    "pm_trades_db_redis_connected",
    "Whether pm-trades-db is connected to Redis.",
)
TRADE_EVENTS_STORED_TOTAL = Counter(
    "pm_trades_db_trade_events_stored_total",
    "Total trade events stored in Postgres.",
)
MALFORMED_TRADE_EVENTS_TOTAL = Counter(
    "pm_trades_db_malformed_trade_events_total",
    "Total malformed trade events skipped.",
)

REDIS_CONNECTED.set(0)


def start_metrics_server(port: int = METRICS_PORT) -> None:
    """Expose Prometheus metrics over HTTP."""
    start_http_server(port)


def mark_redis_connected() -> None:
    """Record that Redis is currently reachable."""
    REDIS_CONNECTED.set(1)


def mark_redis_disconnected() -> None:
    """Record that Redis is currently unreachable."""
    REDIS_CONNECTED.set(0)


def record_redis_retry() -> None:
    """Count a Redis reconnect attempt."""
    REDIS_RETRIES_TOTAL.inc()


def record_trade_stored() -> None:
    """Count a successfully stored trade event."""
    TRADE_EVENTS_STORED_TOTAL.inc()


def record_malformed_trade_event() -> None:
    """Count a malformed event that was skipped."""
    MALFORMED_TRADE_EVENTS_TOTAL.inc()
