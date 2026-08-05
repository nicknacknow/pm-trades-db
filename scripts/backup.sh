#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────────────────
# pm-trades-db — daily incremental PostgreSQL backup
# ──────────────────────────────────────────────────────────────
# Generates two output files per table each run:
#   pm_backup_YYYYMMDD_schema.sql.gz        — schema only (structure)
#   pm_backup_YYYYMMDD_TABLENAME.sql.gz     — yesterday's data only (incremental)
#
# When CLEANUP_AFTER_BACKUP is true the dumped rows are deleted
# from the live database and the table is vacuumed-full to
# reclaim disk space.  Toggle this off when you eventually need
# to query historical data live (and have off-device storage).
#
# History
#   2026-08-04  Safety fix: cleanup DELETE now targets only the
#               just-dumped previous-day range ([yesterday, today))
#               instead of every row older than today.  After a
#               missed run (e.g. the Jul 16 – Aug 3 gap) the old
#               DELETE purged rows that had never been dumped.
#               Also switched the incremental dump from
#               pg_dump --data-only --where to psql COPY (pg_dump
#               --where is unavailable in PostgreSQL 16).  VACUUM
#               runs with (PARALLEL 0) as a standalone statement —
#               parallel VACUUM needs a >64 MB /dev/shm segment
#               the container cannot provide, and VACUUM cannot be
#               bundled with SET in one psql -c (transaction block).
#   2026-06-21  Full-dump → incremental-dump: pg_dump --data-only
#               with a WHERE clause on received_at.  Added
#               CLEANUP_AFTER_BACKUP toggle and daily DELETE +
#               VACUUM FULL.  Removed superseded full-dump files
#               and the old volume-level backup
#               (postgres_volume_backup.tar.gz — it contained
#               Docker internals, not portable anyway).
#   2026-06-16  docker exec → compose-aware execution; systemd
#               user timer instead of /etc/cron.d.
# ──────────────────────────────────────────────────────────────

DB_NAME="trade_store"
BACKUP_DIR="/var/backups/pm-trades-db"

# Off-device copy target (Phase 1 of the backup plan). The USB drive is
# mounted at /mnt/KINGSTON via fstab (nofail). If it's absent, the copy is
# skipped with a warning — the primary backup on BACKUP_DIR still succeeds.
USB_BACKUP_DIR="/mnt/KINGSTON/pm-trades-db-backups"

# ── Toggle ─────────────────────────────────────────────────────
# Set to "true" to purge yesterday's data from Postgres after a
# successful backup.  Switch to "false" when you need to query
# historical data live (move backups to proper storage first).
# TODO: Before flipping, ensure you have off-device storage
#       (USB/NAS/S3) and the backup increment chain is complete.
CLEANUP_AFTER_BACKUP=true

# TODO: Accept --date and --duration CLI params to allow retroactive /
# catch-up runs.  Defaults to today and 1 day (previous day).
# E.g. --date 2026-06-15 --duration 3 would back up June 15-17.

# Tables whose data is dumped incrementally (by received_at).
# Extend this array when adding new data tables.
DATA_TABLES=("trade_events")
# ────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$(dirname "$SCRIPT_DIR")/docker-compose.yml"

# Skip if postgres is not running
docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready \
  -U postgres -d "$DB_NAME" > /dev/null 2>&1 || exit 0

mkdir -p "$BACKUP_DIR"

CUTOFF="$(date +%Y-%m-%d)"
TODAY="${CUTOFF//-/}"

# ── Schema dump ────────────────────────────────────────────────
# Tiny file (≈1 KB) — structure only, no data.
docker compose -f "$COMPOSE_FILE" exec -T postgres pg_dump \
  -U postgres -d "$DB_NAME" --schema-only -Z 9 \
  > "$BACKUP_DIR/pm_backup_${TODAY}_schema.sql.gz"

# ── Incremental data dumps ────────────────────────────────────
# Only rows where received_at fell on the *previous* calendar day.
# NOTE: pg_dump --where is unavailable in PostgreSQL 16.
# We use psql + COPY to produce a valid psql-restorable data block.
DUMP_OK=true
for table in "${DATA_TABLES[@]}"; do
  dump_file="$BACKUP_DIR/pm_backup_${TODAY}_${table}.sql.gz"
  # Build column list for the COPY header (preserves column order).
  cols=$(docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
    -U postgres -d "$DB_NAME" -t -A \
    -c "SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='${table}' AND table_schema='public'")
  if [ -z "$cols" ]; then
    echo "WARNING: could not retrieve columns for $table" >&2
    DUMP_OK=false
    continue
  fi
  if ! {
    echo "COPY ${table} (${cols}) FROM stdin;"
    docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
      -U postgres -d "$DB_NAME" -t -A \
      -c "COPY (SELECT * FROM ${table} WHERE received_at >= '${CUTOFF}'::date - INTERVAL '1 day' AND received_at < '${CUTOFF}'::date) TO STDOUT WITH (FORMAT text, DELIMITER E'\t', NULL '')"
    echo '\.'
  } | gzip > "$dump_file"
  then
    echo "WARNING: data dump failed for $table" >&2
    DUMP_OK=false
  elif [ ! -s "$dump_file" ]; then
    echo "WARNING: $dump_file is empty — backup may have failed" >&2
    DUMP_OK=false
  fi
done

# ── Off-device copy: mirror today's dump to the USB drive ──────
# Phase 1 of the backup plan. Best-effort: if the drive isn't mounted
# (fstab nofail), warn and continue — the primary backup still succeeded.
if [ "$DUMP_OK" = "true" ]; then
  if [ -d "$USB_BACKUP_DIR" ]; then
    cp -n "$BACKUP_DIR"/*.gz "$USB_BACKUP_DIR"/
    echo "Copied backup files to $USB_BACKUP_DIR"
  else
    echo "WARNING: USB backup target $USB_BACKUP_DIR not mounted — skipping off-device copy" >&2
  fi
fi

# ── Cleanup: purge yesterday's data from live DB ──────────────
# Only fires when:
#   1. The toggle is ON, AND
#   2. Every data-dump succeeded AND produced a non-empty file
if [ "$CLEANUP_AFTER_BACKUP" = "true" ] && [ "$DUMP_OK" = "true" ]; then
  echo "Cleaning up yesterday's data from live database..."
  for table in "${DATA_TABLES[@]}"; do
    docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
      -U postgres -d "$DB_NAME" \
      -c "SET statement_timeout TO '60s'; DELETE FROM ${table} WHERE received_at >= '${CUTOFF}'::date - INTERVAL '1 day' AND received_at < '${CUTOFF}'::date;"
    docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
      -U postgres -d "$DB_NAME" \
      -c "SET lock_timeout TO '30s';" \
      -c "VACUUM (PARALLEL 0) ${table};"
  done
  echo "Cleanup complete."
fi

# ANALYZE refreshes query-planner stats after VACUUM FULL rewrites
# each table. Harmless now (no queries), essential once we query.
for table in "${DATA_TABLES[@]}"; do
  docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
    -U postgres -d "$DB_NAME" \
    -c "SET lock_timeout TO '10s'; ANALYZE ${table};" > /dev/null 2>&1
done

if [ "$CLEANUP_AFTER_BACKUP" = "true" ] && [ "$DUMP_OK" = "false" ]; then
  echo "WARNING: Backup incomplete — skipping cleanup. Yesterday's data is preserved." >&2
fi
