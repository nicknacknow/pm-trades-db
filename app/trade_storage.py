"""Postgres persistence for trade events."""

from typing import Any

import asyncpg

from app.trade_payload import (
    canonical_payload,
    event_id_for_payload,
    parse_trade_event,
    parse_trade_timestamp,
)
from app.metrics import record_trade_stored

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
    record_trade_stored()
    # is it worth logging this? i.e. explicit data? perhaps just link to primary key?
