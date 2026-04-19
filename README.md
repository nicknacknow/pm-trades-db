# pm-trades-db

Database service that subscribes to `pminspect` and stores each trade event in Postgres.

## Prerequisites

- Python 3.12+
- `pminspect` running and publishing to Redis at `redis://localhost:6379/0`
- Postgres reachable via `DATABASE_URL`

## Setup

```bash
cd pm-trades-db
python3 -m venv .venv
source .venv/bin/activate
pip install asyncpg redis
```

## Run

```bash
REDIS_URL=redis://localhost:6379/0 \
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/trade_store \
CHANNEL=trades.raw \
python main.py
```

## Docker

```bash
docker build -t pm-trades-db .
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e REDIS_URL=redis://host.docker.internal:6379/0 \
  -e DATABASE_URL=postgresql://postgres:postgres@host.docker.internal:5432/trade_store \
  pm-trades-db
```

## Environment variables

- `REDIS_URL` — Redis pub/sub endpoint
- `DATABASE_URL` — Postgres connection string
- `CHANNEL` — Redis channel, defaults to `trades.raw`
