# pm-trades-db

Database service that subscribes to `pminspect` and stores each trade event in Postgres.

This is intentionally a separate consumer. `pminspect` keeps publishing trades to Redis, and this service reads
those messages and writes them to Postgres. That means this service can stop, restart, or be replaced without
blocking trade ingest.

## Prerequisites

- Python 3.12+
- `pminspect` running and publishing to Redis at `redis://localhost:6379/0`
- Postgres reachable via `DATABASE_URL`

## Setup

```bash
cd pm-trades-db
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
REDIS_URL=redis://localhost:6379/0 \
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/trade_store \
CHANNEL=trades.raw \
METRICS_PORT=8001 \
python main.py
```

## Docker

```bash
cp .env.example .env
docker build -t pm-trades-db .
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  --env-file .env \
  -p 8001:8001 \
  pm-trades-db
```

## Docker Compose

```bash
cp .env.example .env
docker compose up --build -d
docker compose logs -f pm-trades-db
```

This starts:

- `postgres` on `localhost:5432`
- `pm-trades-db` connected to that Postgres container
- metrics on `http://localhost:8001/metrics`
- Compose reads `.env` from the repo root for `REDIS_URL`, `DATABASE_URL`, `CHANNEL`, and `METRICS_PORT`

Notes:

- Copy `.env.example` to `.env` before running Compose
- Redis is expected on your host at `redis://localhost:6379/0`
- The service container reaches it via `redis://host.docker.internal:6379/0`
- Metrics are exposed on `http://localhost:8001/metrics`
- Redis is the handoff point between ingest and storage, so `pminspect` can keep publishing even if this service
  restarts.
- If Redis is temporarily unavailable, `pm-trades-db` logs the wait and keeps retrying instead of exiting.

Stop everything:

```bash
docker compose down
```

Stop and remove Postgres data volume too:

```bash
docker compose down -v
```

## View data in Postgres (`docker exec`)

Open an interactive SQL shell:

```bash
docker compose exec postgres psql -U postgres -d trade_store
```

Inside `psql`:

```sql
\dt
SELECT COUNT(*) FROM trade_events;
SELECT * FROM trade_events ORDER BY received_at DESC LIMIT 20;
```

Exit `psql`:

```text
\q
```

Run a one-off query without opening a shell:

```bash
docker compose exec postgres \
  psql -U postgres -d trade_store \
  -c "SELECT * FROM trade_events ORDER BY received_at DESC LIMIT 5;"
```

## Environment variables

- `REDIS_URL` — Redis pub/sub endpoint
- `DATABASE_URL` — Postgres connection string
- `CHANNEL` — Redis channel, defaults to `trades.raw`
- `POSTGRES_USER` — Postgres username, defaults to `postgres`
- `POSTGRES_PASSWORD` — Postgres password, defaults to `postgres`
- `POSTGRES_DB` — Postgres database name, defaults to `trade_store`
- `METRICS_PORT` — HTTP port for Prometheus metrics, defaults to `8001`

## TODO

| Item | Notes |
|---|---|
| Setup Postgres | Get a local Postgres instance running for the service. |
| Docker Compose | Add a local compose file with Postgres for development. |
| Migrations | Replace inline table creation with a proper migration/init step. |
| Replay/query | Add a small command or endpoint to inspect stored trades. |
| Dashboard replay | Add replay/history functionality (for `pm-dashboard`) |
| DB notifications | Consider Postgres `LISTEN/NOTIFY` for optional wake-up signals later. |
| Redis outage handling | Investigate whether the consumer should retry forever or stop after N failures. Perhaps add prometheus / grafana. |
