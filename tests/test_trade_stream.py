import unittest
from unittest.mock import AsyncMock, patch

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


class StreamValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_trade_events_once_validates_before_db_acquire(self) -> None:
        class FakePubSub:
            async def subscribe(self, channel: str) -> None:
                self.channel = channel

            async def unsubscribe(self, channel: str) -> None:
                self.unsubscribed = channel

            async def aclose(self) -> None:
                self.closed = True

            async def listen(self):
                yield {
                    "type": "message",
                    "data": (
                        '{"event_type":"trade","event_version":"1.0.0","trade":'
                        '{"block_number":1,"timestamp":"2026-01-01T00:00:00+00:00",'
                        '"transaction_hash":"0xabcdef",'
                        '"wallet":"0x1234567890abcdef1234567890abcdef12345678",'
                        '"token_id":"1","condition_id":"0x'
                        + "11" * 32
                        + '","side":0,"maker_amount":1,"taker_amount":2}}'
                    ),
                }

        class FakeRedisClient:
            def __init__(self) -> None:
                self.pubsub_client = FakePubSub()

            def pubsub(self):
                return self.pubsub_client

            async def aclose(self) -> None:
                self.closed = True

        class FakePool:
            async def acquire(self):
                raise AssertionError("db connection should not be acquired for invalid payloads")

        redis_client = FakeRedisClient()

        with (
            patch("app.trade_stream.redis.from_url", return_value=redis_client),
            patch("app.trade_stream.print"),
        ):
            await stream_trade_events_once(FakePool())  # type: ignore[arg-type]
