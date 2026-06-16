# Backup

Daily PostgreSQL backup + VACUUM for `trade_store`.

- Schedule: `03:00` daily
- Script: `scripts/backup.sh`
- Destination: `/var/backups/pm-trades-db/trade_YYYYMMDD.sql.gz`
- Retention: not enforced (see below)

## How it runs

The backup is triggered by a systemd user timer:

```bash
systemctl --user status pm-trades-db-backup.timer
systemctl --user list-timers pm-trades-db-backup.timer
```

Logs are available with:

```bash
journalctl -u pm-trades-db-backup.service
```

## Install / start

```bash
systemctl --user enable --now pm-trades-db-backup.timer
```

## Script behavior
- Skips if Postgres is not healthy.
- Dumps the database with gzip level 9.
- Runs `VACUUM ANALYZE` after the dump.
- The script resolves its own compose project path, so it works regardless of the working directory or container name.

## Manual run

```bash
bash /home/nick/projects/pm-project/pm-trades-db/scripts/backup.sh
ls -lh /var/backups/pm-trades-db
```

## Restore

```bash
gunzip -c /var/backups/pm-trades-db/trade_YYYYMMDD.sql.gz | docker compose exec -T postgres psql -U postgres -d trade_store
```

## Retention

Retention is currently not automated. To enable, uncomment the `find ... -mtime +N -delete` line in `scripts/backup.sh`.

## Troubleshooting

- “permission denied on /var/backups/pm-trades-db” → the user running the script needs write access there.
- Container name changes no longer break the script; if backups still fail, check `docker compose ps` for the `postgres` service health.

## History

- **2026-06-16** — switched from hardcoded `docker exec` to compose-aware execution; moved scheduling from `/etc/cron.d` to a systemd user timer.
