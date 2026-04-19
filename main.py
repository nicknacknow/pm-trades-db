"""Persist pminspect trade events into Postgres."""

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import asyncpg
import redis.asyncio as redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/trade_store",
)
CHANNEL = os.getenv("CHANNEL", "trades.raw")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trade_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    event_version TEXT NOT NULL,
    block_number BIGINT NOT NULL,
    trade_timestamp TIMESTAMPTZ NOT NULL,
    transaction_hash TEXT NOT NULL,
    wallet TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side SMALLINT NOT NULL,
    maker_amount BIGINT NOT NULL,
    taker_amount BIGINT NOT NULL,
    payload_json JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_trade_events_received_at
    ON trade_events (received_at DESC);
"""

INSERT_SQL = """
INSERT INTO trade_events (
    event_id,
    event_type,
    event_version,
    block_number,
    trade_timestamp,
    transaction_hash,
    wallet,
    token_id,
    side,
    maker_amount,
    taker_amount,
    payload_json
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb
)
ON CONFLICT (event_id) DO NOTHING;
"""


def canonical_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def event_id_for_payload(payload_json: str) -> str:
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def parse_trade_timestamp(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_trade_event(payload: dict[str, Any]) -> dict[str, Any]:
    event_type = str(payload["event_type"])
    event_version = str(payload["event_version"])
    trade = payload["trade"]
    if not isinstance(trade, dict):
        raise TypeError("trade payload must be an object")

    return {
        "event_type": event_type,
        "event_version": event_version,
        "trade": trade,
    }


async def bootstrap_schema(connection: asyncpg.Connection) -> None:
    await connection.execute(CREATE_TABLE_SQL)
    await connection.execute(CREATE_INDEX_SQL)


async def store_trade(
    connection: asyncpg.Connection,
    payload: dict[str, Any],
) -> None:
    parsed = parse_trade_event(payload)
    trade = parsed["trade"]
    payload_json = canonical_payload(payload)
    event_id = event_id_for_payload(payload_json)

    await connection.execute(
        INSERT_SQL,
        event_id,
        parsed["event_type"],
        parsed["event_version"],
        int(trade["block_number"]),
        parse_trade_timestamp(str(trade["timestamp"])),
        str(trade["transaction_hash"]),
        str(trade["wallet"]),
        str(trade["token_id"]),
        int(trade["side"]),
        int(trade["maker_amount"]),
        int(trade["taker_amount"]),
        payload_json,
    )


async def main() -> None:
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()

    async with db_pool.acquire() as connection:
        await bootstrap_schema(connection)

    await pubsub.subscribe(CHANNEL)
    print(f"storing {CHANNEL} from {REDIS_URL} into {DATABASE_URL}")

    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue

            raw_data = message.get("data")
            if not isinstance(raw_data, str):
                continue

            try:
                payload = json.loads(raw_data)
                async with db_pool.acquire() as connection:
                    await store_trade(connection, payload)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                print(f"skipping malformed trade event: {exc}")
    finally:
        await pubsub.unsubscribe(CHANNEL)
        await pubsub.aclose()
        await redis_client.aclose()
        await db_pool.close()


if __name__ == "__main__":
    asyncio.run(main())

