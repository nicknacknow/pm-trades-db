#!/usr/bin/env bash
set -e

DB_NAME="trade_store"
BACKUP_DIR="/var/backups/pm-trades-db"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$(dirname "$SCRIPT_DIR")/docker-compose.yml"

# Skip if postgres is not running
docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U postgres -d trade_store > /dev/null 2>&1 || exit 0

mkdir -p "$BACKUP_DIR"

docker compose -f "$COMPOSE_FILE" exec -T postgres pg_dump -U postgres -d "$DB_NAME" -Z 9 > "$BACKUP_DIR/trade_$(date +%Y%m%d).sql.gz"

docker compose -f "$COMPOSE_FILE" exec -T postgres psql -U postgres -d "$DB_NAME" -c "VACUUM ANALYZE;" > /dev/null 2>&1
