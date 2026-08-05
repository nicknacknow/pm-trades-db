import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
from redis.exceptions import ConnectionError as RedisConnectionError

from app.settings import RETRY_DELAY_SECONDS
from app.trade_stream import stream_trade_events, stream_trade_events_once


class StreamRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_trade_events_logs_and_retries_after_redis_failure(self) -> None:
        db_pool = object()

        with (
            patch(
                "app.trade_stream.stream_trade_events_once",
                new=AsyncMock(
                    side_effect=[
                        RedisConnectionError("nope"),
                        RuntimeError("stop"),
                    ]
                ),
            ) as stream_once,
            patch("app.trade_stream.asyncio.sleep", new=AsyncMock()) as sleep_mock,
            patch("app.trade_stream.print") as print_mock,
        ):
            with self.assertRaises(RuntimeError):
                await stream_trade_events(db_pool)  # type: ignore[arg-type]

        self.assertEqual(stream_once.await_count, 2)
        sleep_mock.assert_awaited_once_with(RETRY_DELAY_SECONDS)
        print_mock.assert_any_call(f"waiting {RETRY_DELAY_SECONDS}s before retrying")
        print_mock.assert_any_call("retrying Redis connection")


def _build_pubsub_mocks(messages: list[dict[str, object]]) -> tuple[MagicMock, MagicMock]:
    """Return (redis_client, pubsub) mocks whose listen() yields `messages`."""
    async def fake_listen() -> object:
        for message in messages:
            yield message

    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen = fake_listen
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()

    redis_client = MagicMock()
    redis_client.pubsub.return_value = pubsub
    redis_client.aclose = AsyncMock()
    return redis_client, pubsub


class StreamDatabaseErrorTests(unittest.IsolatedAsyncioTestCase):
    def _make_db_pool(self) -> MagicMock:
        db_pool = MagicMock()
        db_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=object())
        db_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
        return db_pool

    async def test_connection_error_is_counted_and_next_message_still_processed(self) -> None:
        db_pool = self._make_db_pool()
        redis_client, _ = _build_pubsub_mocks(
            [
                {"type": "message", "data": json.dumps({"event": 1})},
                {"type": "message", "data": json.dumps({"event": 2})},
            ]
        )

        db_error = asyncpg.exceptions.PostgresConnectionError("connection lost")

        with (
            patch("app.trade_stream.redis.from_url", return_value=redis_client),
            patch(
                "app.trade_stream.store_trade",
                new=AsyncMock(side_effect=[db_error, None]),
            ) as store,
            patch("app.trade_stream.record_db_error") as record_error,
        ):
            await stream_trade_events_once(db_pool)

        record_error.assert_called_once()
        self.assertEqual(store.await_count, 2)

    async def test_server_side_db_error_is_counted_and_loop_survives(self) -> None:
        db_pool = self._make_db_pool()
        redis_client, _ = _build_pubsub_mocks(
            [{"type": "message", "data": json.dumps({"event": 1})}]
        )

        db_error = asyncpg.exceptions.UniqueViolationError(
            "duplicate key value violates unique constraint"
        )

        with (
            patch("app.trade_stream.redis.from_url", return_value=redis_client),
            patch(
                "app.trade_stream.store_trade",
                new=AsyncMock(side_effect=[db_error]),
            ) as store,
            patch("app.trade_stream.record_db_error") as record_error,
        ):
            await stream_trade_events_once(db_pool)

        record_error.assert_called_once()
        store.assert_awaited_once()

    async def test_pool_acquire_timeout_does_not_crash_loop_and_next_message_processed(self) -> None:
        """A pool-acquire failure (e.g. asyncio.TimeoutError when the pool is
        exhausted) must not escape the consumer loop; the next message must
        still be processed."""
        db_pool = self._make_db_pool()
        db_pool.acquire.side_effect = [
            asyncio.TimeoutError("pool exhausted"),
            db_pool.acquire.return_value,  # second message: acquire succeeds
        ]
        redis_client, _ = _build_pubsub_mocks(
            [
                {"type": "message", "data": json.dumps({"event": 1})},
                {"type": "message", "data": json.dumps({"event": 2})},
            ]
        )

        with (
            patch("app.trade_stream.redis.from_url", return_value=redis_client),
            patch(
                "app.trade_stream.store_trade",
                new=AsyncMock(return_value=None),
            ) as store,
        ):
            await stream_trade_events_once(db_pool)

        self.assertEqual(store.await_count, 1)
