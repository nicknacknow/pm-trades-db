"""Redis subscription loop for trade events."""

import asyncio
import contextlib
import json
from typing import Any

import asyncpg
import redis.asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.metrics import (
    mark_redis_connected,
    mark_redis_disconnected,
    record_malformed_trade_event,
    record_redis_retry,
)
from app.settings import CHANNEL, REDIS_URL, RETRY_DELAY_SECONDS
from app.trade_payload import parse_trade_event
from app.trade_storage import store_trade


async def close_redis_subscription(
    redis_client: redis.Redis,
    pubsub: Any,
) -> None:
    with contextlib.suppress(RedisConnectionError, OSError):
        await pubsub.unsubscribe(CHANNEL)
    with contextlib.suppress(RedisConnectionError, OSError):
        await pubsub.aclose()
    with contextlib.suppress(RedisConnectionError, OSError):
        await redis_client.aclose()


async def stream_trade_events_once(db_pool: asyncpg.Pool) -> None:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()

    try:
        print(f"connecting to Redis at {REDIS_URL} for {CHANNEL}")
        await pubsub.subscribe(CHANNEL)
        mark_redis_connected()
        print(f"connected to Redis; listening on {CHANNEL}")

        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue

            raw_data = message.get("data")
            if not isinstance(raw_data, str):
                continue

            try:
                payload = json.loads(raw_data)
                parsed_payload = parse_trade_event(payload)
                async with db_pool.acquire() as connection:
                    await store_trade(connection, parsed_payload)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                record_malformed_trade_event()
                print(f"skipping malformed trade event: {exc}")
    finally:
        mark_redis_disconnected()
        await close_redis_subscription(redis_client, pubsub)


async def stream_trade_events(db_pool: asyncpg.Pool) -> None:
    while True:
        try:
            await stream_trade_events_once(db_pool)
        except RedisConnectionError as exc:
            record_redis_retry()
            print(f"Redis unavailable: {exc}")
            print(f"waiting {RETRY_DELAY_SECONDS}s before retrying")
            await asyncio.sleep(RETRY_DELAY_SECONDS)
            print("retrying Redis connection")
