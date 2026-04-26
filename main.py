"""Persist pminspect trade events into Postgres."""

import asyncio

import asyncpg

from app.metrics import start_metrics_server
from app.settings import DATABASE_URL
from app.trade_storage import bootstrap_schema
from app.trade_stream import stream_trade_events


async def main() -> None:
    start_metrics_server()
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    try:
        async with db_pool.acquire() as connection:
            await bootstrap_schema(connection)

        await stream_trade_events(db_pool)
    finally:
        await db_pool.close()


if __name__ == "__main__":
    asyncio.run(main())
