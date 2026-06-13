#!/usr/bin/env bash
set -e

DB_NAME="trade_store"
BACKUP_DIR="/var/backups/pm-trades-db"
# RETENTION_DAYS=14                       # uncomment to keep only N days of dumps

# Skip if postgres not running
docker exec pm-trades-db_postgres_1 pg_isready -U postgres > /dev/null 2>&1 || exit 0

mkdir -p "$BACKUP_DIR"

docker exec pm-trades-db_postgres_1 pg_dump -U postgres -d "$DB_NAME" -Z 9 > "$BACKUP_DIR/trade_$(date +%Y%m%d).sql.gz"
# find "$BACKUP_DIR" -name "trade_*.sql.gz" -mtime +$RETENTION_DAYS -delete   # uncomment with RETENTION_DAYS

