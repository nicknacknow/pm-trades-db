# pm-trades-db

Persist Polymarket trade events from Redis into Postgres.

## Runtime

- `REDIS_URL` — Redis pub/sub endpoint, defaults to `redis://localhost:6379/0`
- `DATABASE_URL` — Postgres connection string, defaults to `postgresql://postgres:postgres@localhost:5432/trade_store`
- `CHANNEL` — Redis channel, defaults to `trades.raw`

## Docker

```bash
docker build -t pm-trades-db .
docker run --rm \
  --add-host=host.docker.internal:host-gateway \
  -e REDIS_URL=redis://host.docker.internal:6379/0 \
  -e DATABASE_URL=postgresql://postgres:postgres@host.docker.internal:5432/trade_store \
  pm-trades-db
```

The service creates its table on startup and ignores duplicate events by event hash.
