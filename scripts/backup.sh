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

# ── Toggle ─────────────────────────────────────────────────────
# Set to "true" to purge yesterday's data from Postgres after a
# successful backup.  Switch to "false" when you need to query
# historical data live (move backups to proper storage first).
# TODO: Before flipping, ensure you have off-device storage
#       (USB/NAS/S3) and the backup increment chain is complete.
CLEANUP_AFTER_BACKUP=true

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
DUMP_OK=true
for table in "${DATA_TABLES[@]}"; do
  dump_file="$BACKUP_DIR/pm_backup_${TODAY}_${table}.sql.gz"
  if ! docker compose -f "$COMPOSE_FILE" exec -T postgres pg_dump \
    -U postgres -d "$DB_NAME" --data-only --table="$table" \
    --where="received_at >= '${CUTOFF}'::date - INTERVAL '1 day' AND received_at < '${CUTOFF}'::date" \
    -Z 9 \
    > "$dump_file"
  then
    echo "WARNING: pg_dump exited non-zero for $table" >&2
    DUMP_OK=false
  elif [ ! -s "$dump_file" ]; then
    echo "WARNING: $dump_file is empty — backup may have failed" >&2
    DUMP_OK=false
  fi
done

# ── Cleanup: purge yesterday's data from live DB ──────────────
# Only fires when:
#   1. The toggle is ON, AND
#   2. Every data-dump succeeded AND produced a non-empty file
if [ "$CLEANUP_AFTER_BACKUP" = "true" ] && [ "$DUMP_OK" = "true" ]; then
  echo "Cleaning up yesterday's data from live database..."
  docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
    -U postgres -d "$DB_NAME" \
    -c "DELETE FROM trade_events WHERE received_at < '${CUTOFF}'::date;"

  docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
    -U postgres -d "$DB_NAME" \
    -c "VACUUM FULL trade_events;"
  echo "Cleanup complete."
fi

# ANALYZE refreshes query-planner stats after VACUUM FULL rewrites
# the table.  Harmless now (no queries), essential once we query.
docker compose -f "$COMPOSE_FILE" exec -T postgres psql \
  -U postgres -d "$DB_NAME" -c "ANALYZE trade_events;" > /dev/null 2>&1

if [ "$CLEANUP_AFTER_BACKUP" = "true" ] && [ "$DUMP_OK" = "false" ]; then
  echo "WARNING: Backup incomplete — skipping cleanup. Yesterday's data is preserved." >&2
fi
