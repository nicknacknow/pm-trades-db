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
| `trade_YYYYMMDD_schema.sql.gz` | Table structure only (≈1 KB) | Every run |
| `trade_YYYYMMDD.sql.gz` | Rows where `received_at` fell on the **previous** calendar day | Every run |

When `CLEANUP_AFTER_BACKUP=true` the script additionally does:

```sql
DELETE FROM trade_events WHERE received_at < 'YYYY-MM-DD'::date;
VACUUM FULL trade_events;
```

(The cutoff date is captured once at script start so the dump and the DELETE
are guaranteed to use the same boundary, even if execution spans midnight.)

This keeps the live database lean (≈ today's data only, ≈300 MB) instead of
growing unbounded.  **Set `CLEANUP_AFTER_BACKUP=false`** when you eventually need
to query historical data live (and have moved backups to proper off-device
storage — see [Future](#future) below).

---

## Safety

The cleanup **only** fires when **all** of these hold:

1. `CLEANUP_AFTER_BACKUP=true`
2. `pg_dump` exited with code 0
3. The compressed dump file is non-empty (confirmed with `-s`)

If any data-dump fails or is empty, yesterday's data is **preserved** in the
live database and a warning is logged.  Your daily alert catches this.

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

---

## Restore

### From scratch (full recovery)

```bash
# 1. Apply schema (any schema dump works — they're identical)
gunzip -c /var/backups/pm-trades-db/trade_20260621_schema.sql.gz \
  | docker compose exec -T postgres psql -U postgres -d trade_store

# 2. Restore the last full dump as a baseline
gunzip -c /var/backups/pm-trades-db/trade_20260621.sql.gz \
  | docker compose exec -T postgres psql -U postgres -d trade_store

# 3. Apply each daily increment in order
for f in /var/backups/pm-trades-db/trade_2026062*.sql.gz; do
  gunzip -c "$f" | docker compose exec -T postgres psql -U postgres -d trade_store
done
```

### Single-day restore (a specific day's data)

```bash
gunzip -c /var/backups/pm-trades-db/trade_20260622.sql.gz \
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

Retention is not automated.  To enable it, uncomment the `find … -mtime +N
-delete` line in `scripts/backup.sh`.

Suggested policy: keep daily increments for **30 days**.

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
  increment is ≈300 MB.

---

## History

| Date | Change |
|---|---|
| **2026-06-21** | Full-dump → incremental-dump (`pg_dump --data-only --where`). Added `CLEANUP_AFTER_BACKUP` toggle with `DELETE` + `VACUUM FULL`. Deleted superseded full dumps (Jun 14–20) and the old volume backup. |
| **2026-06-16** | `docker exec` → compose-aware execution; systemd user timer replaces `/etc/cron.d`. |
