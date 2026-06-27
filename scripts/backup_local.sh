#!/bin/bash
# scripts/backup_local.sh
# 备份本地 Docker Compose 开发环境的所有持久化数据。
# 备份保存在 ./backups/<timestamp>/ 目录下。

set -e

BACKUP_DIR="./backups/$(date +%Y%m%d-%H%M%S)"
KEEP_COUNT=10

echo "==> Emerald 本地备份"
echo "==> 目标目录: $BACKUP_DIR"

mkdir -p "$BACKUP_DIR"

# 检查必要容器是否运行
for container in emerald-postgres emerald-neo4j emerald-redis emerald-minio; do
    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        echo "❌ 容器 $container 没有运行。请先执行: docker compose up -d"
        exit 1
    fi
done

# 1. PostgreSQL 备份
echo "--> 备份 PostgreSQL..."
docker exec emerald-postgres pg_dump -U emerald emerald \
    | gzip > "$BACKUP_DIR/postgres.sql.gz"
echo "✅ PostgreSQL 备份完成"

# 2. Neo4j 备份（离线复制，社区版最稳妥）
echo "--> 备份 Neo4j（会短暂停止服务）..."
docker compose stop neo4j >/dev/null 2>&1 || docker stop emerald-neo4j >/dev/null 2>&1 || true
docker cp emerald-neo4j:/data "$BACKUP_DIR/neo4j-data"
docker compose start neo4j >/dev/null 2>&1 || docker start emerald-neo4j >/dev/null 2>&1 || true
echo "✅ Neo4j 备份完成"

# 3. Redis 备份
echo "--> 备份 Redis..."
# 触发 BGSAVE
docker exec emerald-redis redis-cli -a emerald_dev LASTSAVE >/dev/null 2>&1 || true
docker exec emerald-redis redis-cli -a emerald_dev BGSAVE >/dev/null 2>&1 || true
# 等待 RDB 生成完成
sleep 2
docker cp emerald-redis:/data/dump.rdb "$BACKUP_DIR/redis-dump.rdb" 2>/dev/null || true
docker cp emerald-redis:/data/appendonly.aof "$BACKUP_DIR/redis-appendonly.aof" 2>/dev/null || true

if [ ! -f "$BACKUP_DIR/redis-dump.rdb" ] && [ ! -f "$BACKUP_DIR/redis-appendonly.aof" ]; then
    echo "⚠️  Redis 数据文件未找到（可能 AOF 未生成）"
else
    echo "✅ Redis 备份完成"
fi

# 4. MinIO 备份
echo "--> 备份 MinIO..."
docker cp emerald-minio:/data "$BACKUP_DIR/minio-data"
echo "✅ MinIO 备份完成"

# 5. 元数据
cat > "$BACKUP_DIR/README.txt" <<EOF
Emerald 本地开发备份
创建时间: $(date)
包含: PostgreSQL, Neo4j, Redis, MinIO
恢复方式: ./scripts/restore_local.sh $BACKUP_DIR
EOF

# 6. 清理旧备份，只保留最近 KEEP_COUNT 个
echo "--> 清理旧备份（保留最近 $KEEP_COUNT 个）..."
ls -1td ./backups/*/ 2>/dev/null | tail -n +$((KEEP_COUNT + 1)) | xargs -r rm -rf

echo ""
echo "==> 备份完成: $BACKUP_DIR"
echo "==> 恢复命令: ./scripts/restore_local.sh $BACKUP_DIR"
