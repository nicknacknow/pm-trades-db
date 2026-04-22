import unittest
from unittest.mock import AsyncMock, patch

from redis.exceptions import ConnectionError as RedisConnectionError

from app.settings import RETRY_DELAY_SECONDS
from app.trade_stream import stream_trade_events


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
        print_mock.assert_any_call("waiting 5s before retrying")
        print_mock.assert_any_call("retrying Redis connection")
