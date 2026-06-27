#!/bin/bash
# scripts/restore_local.sh
# 从本地备份恢复 Emerald 开发环境。
# 用法: ./scripts/restore_local.sh ./backups/20260627-120000

set -e

BACKUP_DIR=$1

if [ -z "$BACKUP_DIR" ]; then
    echo "❌ 用法: ./scripts/restore_local.sh <backup-dir>"
    echo "示例: ./scripts/restore_local.sh ./backups/20260627-120000"
    exit 1
fi

if [ ! -d "$BACKUP_DIR" ]; then
    echo "❌ 备份目录不存在: $BACKUP_DIR"
    exit 1
fi

echo "==> Emerald 本地恢复"
echo "==> 来源目录: $BACKUP_DIR"
echo ""
echo "⚠️  警告: 此操作会删除当前 Docker volume 中的数据，请确认已备份当前状态。"
read -p "是否继续? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "已取消"
    exit 0
fi

# 确保服务在运行
echo "--> 启动基础服务..."
docker compose up -d postgres neo4j redis minio >/dev/null 2>&1 || true

# 1. 恢复 PostgreSQL
if [ -f "$BACKUP_DIR/postgres.sql.gz" ]; then
    echo "--> 恢复 PostgreSQL..."
    gunzip -c "$BACKUP_DIR/postgres.sql.gz" | docker exec -i emerald-postgres psql -U emerald -d emerald
    echo "✅ PostgreSQL 恢复完成"
else
    echo "⚠️  未找到 PostgreSQL 备份文件"
fi

# 2. 恢复 Neo4j
if [ -d "$BACKUP_DIR/neo4j-data" ]; then
    echo "--> 恢复 Neo4j..."
    docker compose stop neo4j >/dev/null 2>&1 || docker stop emerald-neo4j >/dev/null 2>&1 || true
    docker volume rm emerald_neo4j_data 2>/dev/null || true
    docker compose up -d neo4j >/dev/null 2>&1 || true
    sleep 5
    docker cp "$BACKUP_DIR/neo4j-data/." emerald-neo4j:/data/
    docker restart neo4j >/dev/null 2>&1 || true
    echo "✅ Neo4j 恢复完成"
else
    echo "⚠️  未找到 Neo4j 备份目录"
fi

# 3. 恢复 Redis
if [ -f "$BACKUP_DIR/redis-dump.rdb" ] || [ -f "$BACKUP_DIR/redis-appendonly.aof" ]; then
    echo "--> 恢复 Redis..."
    docker compose stop redis >/dev/null 2>&1 || docker stop emerald-redis >/dev/null 2>&1 || true
    docker volume rm emerald_redis_data 2>/dev/null || true
    docker compose up -d redis >/dev/null 2>&1 || true
    sleep 2
    [ -f "$BACKUP_DIR/redis-dump.rdb" ] && docker cp "$BACKUP_DIR/redis-dump.rdb" emerald-redis:/data/dump.rdb
    [ -f "$BACKUP_DIR/redis-appendonly.aof" ] && docker cp "$BACKUP_DIR/redis-appendonly.aof" emerald-redis:/data/appendonly.aof
    docker restart redis >/dev/null 2>&1 || true
    echo "✅ Redis 恢复完成"
else
    echo "⚠️  未找到 Redis 备份文件"
fi

# 4. 恢复 MinIO
if [ -d "$BACKUP_DIR/minio-data" ]; then
    echo "--> 恢复 MinIO..."
    docker compose stop minio >/dev/null 2>&1 || docker stop emerald-minio >/dev/null 2>&1 || true
    docker volume rm emerald_minio_data 2>/dev/null || true
    docker compose up -d minio >/dev/null 2>&1 || true
    sleep 2
    docker cp "$BACKUP_DIR/minio-data/." emerald-minio:/data/
    docker restart minio >/dev/null 2>&1 || true
    echo "✅ MinIO 恢复完成"
else
    echo "⚠️  未找到 MinIO 备份目录"
fi

echo ""
echo "==> 恢复完成"
echo "==> 请运行: docker compose up -d"
