#!/usr/bin/env bash
# scripts/disaster_recovery_drill.sh — DR drill for Postgres, Neo4j, Redis
# Targets docker-compose stacks (current production-equivalent).
# Usage: ./scripts/disaster_recovery_drill.sh [compose-project-name]

set -euo pipefail

PROJECT="${1:-emerald}"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/tmp/emerald-dr-${TIMESTAMP}"

echo "=== Emerald Disaster Recovery Drill ==="
echo "Compose project: $PROJECT"
echo "Backup dir: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

# Verify docker-compose is running
if ! docker compose -p "$PROJECT" ps --services >/dev/null 2>&1; then
    echo "ERROR: docker compose project '$PROJECT' not running" >&2
    echo "Start with: docker compose -p $PROJECT up -d" >&2
    exit 1
fi

# 1. PostgreSQL backup
echo
echo "[1/4] Backing up PostgreSQL..."
docker compose -p "$PROJECT" exec -T postgres \
    pg_dump -U emerald emerald | gzip > "$BACKUP_DIR/postgres-${TIMESTAMP}.sql.gz"
echo "✓ Postgres backup: $BACKUP_DIR/postgres-${TIMESTAMP}.sql.gz"

# 2. Neo4j backup
echo
echo "[2/4] Backing up Neo4j..."
NEO4J_CONTAINER=$(docker compose -p "$PROJECT" ps -q neo4j)
if [ -z "$NEO4J_CONTAINER" ]; then
    echo "ERROR: Neo4j container not found in project '$PROJECT'" >&2
    exit 1
fi

# Read Neo4j auth from docker-compose env
NEO4J_AUTH_VALUE=$(docker compose -p "$PROJECT" config 2>/dev/null \
    | grep -E "NEO4J_AUTH" | head -1 | sed 's/.*NEO4J_AUTH[=:]*//' | tr -d ' "\r')
if [ -z "$NEO4J_AUTH_VALUE" ]; then
    echo "WARNING: NEO4J_AUTH not set in docker-compose; assuming auth disabled (dev only)"
    docker exec "$NEO4J_CONTAINER" \
        neo4j-admin database dump neo4j --to-path=/tmp/ 2>/dev/null || {
            echo "WARNING: neo4j-admin dump failed; falling back to data dir snapshot..."
            docker cp "$NEO4J_CONTAINER":/data "$BACKUP_DIR/neo4j-data-${TIMESTAMP}" 2>/dev/null || \
                echo "WARNING: Could not snapshot Neo4j data dir"
        }
else
    NEO4J_USER=$(echo "$NEO4J_AUTH_VALUE" | cut -d/ -f1)
    NEO4J_PASS=$(echo "$NEO4J_AUTH_VALUE" | cut -d/ -f2)
    docker exec "$NEO4J_CONTAINER" \
        neo4j-admin database dump neo4j --to-path=/tmp/ \
        --user="$NEO4J_USER" --password="$NEO4J_PASS" 2>/dev/null || {
            echo "WARNING: neo4j-admin dump with auth failed; falling back to data dir snapshot..."
            docker cp "$NEO4J_CONTAINER":/data "$BACKUP_DIR/neo4j-data-${TIMESTAMP}" 2>/dev/null || \
                echo "WARNING: Could not snapshot Neo4j data dir"
        }
fi
docker cp "$NEO4J_CONTAINER":/tmp/neo4j.dump "$BACKUP_DIR/neo4j-${TIMESTAMP}.dump" 2>/dev/null || true
echo "✓ Neo4j backup in: $BACKUP_DIR/neo4j-*"

# 3. Redis backup (RDB snapshot)
echo
echo "[3/4] Backing up Redis..."
REDIS_CONTAINER=$(docker compose -p "$PROJECT" ps -q redis)
docker exec "$REDIS_CONTAINER" sh -c "redis-cli BGSAVE && sleep 3"
docker cp "$REDIS_CONTAINER":/data/dump.rdb \
    "$BACKUP_DIR/redis-${TIMESTAMP}.rdb"
echo "✓ Redis backup: $BACKUP_DIR/redis-${TIMESTAMP}.rdb"

# 4. Verify backups (size sanity check)
echo
echo "[4/4] Verifying backups..."
for f in "$BACKUP_DIR"/*; do
    SIZE=$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f" 2>/dev/null)
    if [ "${SIZE:-0}" -lt 1024 ]; then
        echo "WARNING: Backup $(basename "$f") is small ($SIZE bytes), may have failed"
    else
        echo "✓ $(basename "$f") ($SIZE bytes)"
    fi
done

echo
echo "=== DR Drill Complete ==="
echo "Backups in: $BACKUP_DIR"
echo "Restoration is a manual step — see docs/deployment/k8s-runbook.md"
