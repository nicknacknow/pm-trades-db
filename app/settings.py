"""Runtime settings for pm-trades-db."""

import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/trade_store",
)
CHANNEL = os.getenv("CHANNEL", "trades.raw")
RETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", "5"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "8001"))
