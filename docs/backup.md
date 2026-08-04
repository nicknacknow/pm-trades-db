# Backup

Daily incremental PostgreSQL backup + optional live-DB cleanup for `trade_store`.

- Schedule: `03:00` daily (systemd user timer)
- Script: `scripts/backup.sh`
- Destination: `/var/backups/pm-trades-db/`
- Retention: not enforced (see below)

---

## Strategy

The database is a **write-only archive** — trade events stream in from Redis and are
stored, but never read back by the application.  This makes it a perfect candidate
for an **incremental backup with live cleanup**:

| File | Contents | Frequency |
|---|---|---|
| `pm_backup_YYYYMMDD_schema.sql.gz` | Table structure only (≈1 KB) | Every run |
| `pm_backup_YYYYMMDD_TABLENAME.sql.gz` | Rows where `received_at` fell on the **previous** calendar day | Every run, one per table |

When `CLEANUP_AFTER_BACKUP=true` the script additionally does (per table in `DATA_TABLES`):

```sql
-- only the rows that were just dumped (previous calendar day)
DELETE FROM table WHERE received_at >= 'YYYY-MM-DD'::date - INTERVAL '1 day'
                  AND received_at <  'YYYY-MM-DD'::date;
VACUUM (PARALLEL 0) table;
```

(The cutoff date is captured once at script start so the dump and the DELETE
are guaranteed to use the same boundary, even if execution spans midnight.)

The DELETE only ever purges the previous day's rows — the exact rows the
incremental dump just captured.  After a missed run, un-dumped older rows stay
in the live database (safely accumulating) instead of being silently destroyed;
run a manual catch-up (see [Catch-up after a missed run](#catch-up-after-a-missed-run))
to close the gap.  `VACUUM` runs with `PARALLEL 0` as a standalone `psql -c`
statement: parallel maintenance workers need a >64 MB shared-memory segment the
container's `/dev/shm` cannot provide, and VACUUM cannot be bundled with `SET`
in a single `-c` (transaction block error).

This keeps the live database lean (≈ today's data only) instead of
growing unbounded.  **Set `CLEANUP_AFTER_BACKUP=false`** when you eventually need
to query historical data live (and have moved backups to proper off-device
storage — see [Future](#future) below).

---

## Safety

The cleanup **only** fires when **all** of these hold:

1. `CLEANUP_AFTER_BACKUP=true`
2. Every data-dump (psql `COPY`) exited with code 0
3. The compressed dump file is non-empty (confirmed with `-s`)

Even then, only the just-dumped previous-day rows are purged — never rows that
have no backup.  If any data-dump fails or is empty, the cleanup is skipped,
older data is **preserved** in the live database, and a warning is logged.

---

## How it runs

A systemd user timer triggers the backup every morning:

```bash
systemctl --user status pm-trades-db-backup.timer
systemctl --user list-timers pm-trades-db-backup.timer
```

Logs are available with:

```bash
journalctl -u pm-trades-db-backup.service -e
```

## Install / start

```bash
systemctl --user enable --now pm-trades-db-backup.timer
```

## Manual run

```bash
bash /home/nick/projects/pm-project/pm-trades-db/scripts/backup.sh
ls -lh /var/backups/pm-trades-db
```

## Catch-up after a missed run

The script only dumps the **previous** calendar day.  If the timer was down for
N days, run N catch-up dumps with the same `COPY` technique, one per missed day
(`YYYYMMDD` = the day *after* the day being dumped — the file name carries the
run date, and the restore loop applies them in order):

```bash
COLS=$(docker exec pm-trades-db-postgres-1 psql -U postgres -d trade_store -t -A \
  -c "SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position)
      FROM information_schema.columns
      WHERE table_name='trade_events' AND table_schema='public'")

for DAY in 2026-07-15; do
  NEXT=$(date -d "$DAY +1 day" +%Y%m%d)
  {
    echo "COPY trade_events (${COLS}) FROM stdin;"
    docker exec pm-trades-db-postgres-1 psql -U postgres -d trade_store -t -A \
      -c "COPY (SELECT * FROM trade_events
                WHERE received_at >= '$DAY'::date
                  AND received_at <  '$DAY'::date + INTERVAL '1 day')
          TO STDOUT WITH (FORMAT text, DELIMITER E'\t', NULL '')"
    echo '\.'
  } | gzip > "/var/backups/pm-trades-db/pm_backup_${NEXT}_trade_events.sql.gz"
done
```

Verify each file with `gzip -t` and confirm the row count matches the live DB:

```bash
gunzip -c /var/backups/pm-trades-db/pm_backup_20260716_trade_events.sql.gz | grep -c $'\t'
```

(2026-08-04: the Jul 15 – Aug 3 gap was closed this way —
`pm_backup_20260716_trade_events.sql.gz` holds Jul 15's 1,936,460 rows.)

---

## Restore

### From scratch (full recovery)

```bash
# 1. Apply schema (any schema dump works — they're identical)
gunzip -c /var/backups/pm-trades-db/pm_backup_20260622_schema.sql.gz \
  | docker compose exec -T postgres psql -U postgres -d trade_store

# 2. Restore the last full dump as a baseline
gunzip -c /var/backups/pm-trades-db/trade_20260621.sql.gz \
  | docker compose exec -T postgres psql -U postgres -d trade_store

# 3. Apply each daily increment in order (per table)
for f in /var/backups/pm-trades-db/pm_backup_*_trade_events.sql.gz; do
  gunzip -c "$f" | docker compose exec -T postgres psql -U postgres -d trade_store
done
```

### Single-day restore (a specific day's table data)

```bash
gunzip -c /var/backups/pm-trades-db/pm_backup_20260622_trade_events.sql.gz \
  | docker compose exec -T postgres psql -U postgres -d trade_store
```

---

## What we learned

This system went through a few iterations.  Here is what surprised us.

### `pg_dump` without flags dumps everything

Running `pg_dump -Z 9` with no `--where` or `--data-only` produces a **full
snapshot** of the entire database.  Each daily file was a complete copy — they
only differed by whatever new data arrived in the previous 24 hours.  The files
grew unbounded (141 MB → 2.2 GB over one week) and were entirely redundant.

**Fix:** `pg_dump --data-only --table=trade_events --where="received_at >= ..."`

### Compressed dump size ≠ database size

The compressed SQL dumps are **much smaller** than the live database:

- `trade_20260621.sql.gz` (compressed dump): **2.1 GB**
- `trade_store` on disk: **10 GB**
- Ratio: **≈5:1**

SQL text compresses extremely well (`-Z 9` = gzip max).  The live database also
carries indexes, MVCC dead rows, and free space that the dump strips out.

### Backups were on the same disk as the database

Both the Docker volume (`/var/lib/docker/volumes/…`) and the backup directory
(`/var/backups/pm-trades-db`) lived on the same SD card (`/dev/mmcblk0p2`).
This means a disk failure would destroy the database **and** all backups
simultaneously.  The backup only protected against logical corruption
(accidental `DROP TABLE`, bad data, etc.).

This is why off-device storage (USB, NAS, S3) is the eventual goal.

### The old volume backup contained Docker internals

`postgres_volume_backup.tar.gz` was a raw tarball of the Docker volume —
Postgres's data directory with WAL segments, `pg_xact`, `pg_stat`, and other
internal state.  It is tied to the exact Docker image and Postgres version, not
portable across machines.  SQL dumps (`pg_dump`) are much more portable — they
can be restored into any Postgres version on any platform.

### Full dumps were redundant

`trade_20260614.sql.gz` through `trade_20260620.sql.gz` each contained every
row from the beginning of time — each one was a superset of the previous.  Only
`trade_20260621.sql.gz` (the last full dump) was kept as a restore baseline.

---

## Retention

Retention is not currently automated.  Suggested policy: keep daily increments
for **30 days**.

To clean up old dumps, run something like (adjust retention as needed):

```bash
find /var/backups/pm-trades-db -name 'pm_backup_*.sql.gz' -mtime +30 -delete
```

---

## Future

### When you need to query historical data live

1. **First**, set up proper off-device storage (USB stick, NAS, or S3).
2. **Set `CLEANUP_AFTER_BACKUP=false`** in `backup.sh`.
3. The data will start accumulating in the live database again.
4. Historical data that was previously cleaned up can be restored from the
   backup chain (last full dump + all daily increments).

### Off-device storage

The current setup protects against logical corruption only.  For hardware
failure protection, copy the backup files to a separate device (USB drive
mounted at `/mnt/backup` or similar).  The SQL dump format is portable — you
can restore on any machine with PostgreSQL installed.

### Redis backpressure

The app receives trade events via a Redis **pub/sub** channel, which is
fire-and-forget.  If PostgreSQL is locked (e.g., during `VACUUM FULL`), the
Redis client buffer overflows and messages are dropped.

To fix this in the future, swap pub/sub for a **Redis LIST** or **stream**
(persistent queue).  Messages persist in Redis until the app acknowledges them,
so a locked Postgres just means the queue backs up harmlessly.

**TODO:** Convert `trade_stream.py` from `pubsub.listen()` to
`BLPOP`/`BRPOP` (LIST) or `XREAD` (stream).

### CLI parameters for ad-hoc runs

The script only backs up "yesterday" relative to the current date.  For
retroactive runs or catch-up after a missed backup, it would be useful to
pass `--date` and `--duration`:

```bash
# Back up June 15-17 inclusive
bash scripts/backup.sh --date 2026-06-15 --duration 3
```

**TODO:** Add argument parsing to `backup.sh`.  Defaults remain `--date today
--duration 1` so the 03:00 cron behaviour is unchanged.

---

## Troubleshooting

- **"Permission denied on /var/backups/pm-trades-db"** → the user running the
  script needs write access there.
- **Container name changes** no longer break the script (compose-aware); if
  backups still fail, check `docker compose ps` for the `postgres` service
  health.
- **Cleanup was skipped** → check `journalctl` for the warning message.  Either
  the dump failed or the toggle is off.
- **"disk full" errors** → check `df -h /` and remove old dumps.  Each daily
  increment is a few hundred MB when the day has data (a quiet day is ~160 B).
- **`VACUUM cannot run inside a transaction block` / shared-memory errors** →
  the cleanup VACUUM must be a standalone `psql -c` with `(PARALLEL 0)`, as the
  script now does; the container's `/dev/shm` cannot size a parallel-worker segment.

---

## History

| Date | Change |
|---|---|
| **2026-08-04** | Safety fix: cleanup DELETE now targets only the just-dumped previous-day range instead of every row older than today — a missed run no longer destroys never-dumped rows. Incremental dump switched from `pg_dump --data-only --where` to psql `COPY` (unavailable in PostgreSQL 16); `VACUUM (PARALLEL 0)` as a standalone statement (container `/dev/shm` too small for parallel workers). Timer re-enabled (daily 03:00, `Persistent=true`). Gap Jul 16 – Aug 3 closed via catch-up (`pm_backup_20260716_trade_events.sql.gz`, 1,936,460 rows). |
| **2026-06-21** | Full-dump → incremental-dump (`pg_dump --data-only --where`). Added `CLEANUP_AFTER_BACKUP` toggle with `DELETE` + `VACUUM FULL`. Deleted superseded full dumps (Jun 14–20) and the old volume backup. |
| **2026-06-16** | `docker exec` → compose-aware execution; systemd user timer replaces `/etc/cron.d`. |
