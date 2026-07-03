# Emerald Kubernetes 运维手册

> 适用版本：v0.4.0+ / 目标环境：Kubernetes 1.27+

## 部署

### 前置检查
- kubectl 已配置，连接到目标集群
- 8 个 manifest 文件存在于 `k8s/` 目录
- 镜像已构建：`docker build --target production -t emerald:v0.4.0 .`

### 部署顺序

```bash
# 1. 命名空间（必须最先）
kubectl apply -f k8s/namespace.yaml

# 2. 配置（无依赖）
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml

# 3. 应用层
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# 4. 自动伸缩 + Ingress
kubectl apply -f k8s/hpa.yaml
kubectl apply -f k8s/ingress.yaml

# 5. 备份（最后）
kubectl apply -f k8s/backup-cronjob.yaml
```

> **注意：** 当前数据层（Postgres / Neo4j / Redis / MinIO）由 `docker-compose.yml` 管理。K8s 数据层 manifest 是 M2+ 交付项，将在后续版本补齐。

### 验证

```bash
# 检查所有 pod 就绪
kubectl get pods -n emerald -l app=emerald-api

# 健康检查
kubectl port-forward -n emerald svc/emerald-api 8000:8000 &
curl http://localhost:8000/v1/health

# 检查 HPA 状态
kubectl get hpa -n emerald
```

## 升级

```bash
# 1. 构建新镜像
docker build --target production -t emerald:v0.4.1 .

# 2. 推送到镜像仓库（按实际仓库地址调整）
docker tag emerald:v0.4.1 your-registry/emerald:v0.4.1
docker push your-registry/emerald:v0.4.1

# 3. 更新 deployment
kubectl set image deployment/emerald-api -n emerald api=your-registry/emerald:v0.4.1

# 4. 监控滚动更新
kubectl rollout status deployment/emerald-api -n emerald

# 5. 回滚（如需要）
kubectl rollout undo deployment/emerald-api -n emerald
```

## 灾备恢复

### 备份（自动化）
`backup-cronjob.yaml` 配置每日凌晨 2 点备份 PostgreSQL 到 PVC 挂载点。

### DR Drill（手动）
```bash
# 在测试命名空间执行灾备演练
./scripts/disaster_recovery_drill.sh
```

### PostgreSQL 恢复（docker-compose）

```bash
# 1. 解压备份
gunzip -c postgres-YYYYMMDD-HHMMSS.sql.gz > /tmp/restore.sql

# 2. 停止 API + worker（避免并发写入）
docker compose -p emerald stop emerald-api emerald-worker

# 3. 恢复数据
docker compose -p emerald exec -T postgres \
    psql -U emerald emerald < /tmp/restore.sql

# 4. 重启应用
docker compose -p emerald start emerald-api emerald-worker
```

### Neo4j 恢复（docker-compose）

```bash
# 1. 停止 Neo4j
docker compose -p emerald stop neo4j

# 2. 恢复 dump
docker cp neo4j-YYYYMMDD-HHMMSS.dump emerald-neo4j-1:/tmp/neo4j.dump
docker compose -p emerald exec neo4j neo4j-admin database load neo4j \
    --from-path=/tmp/neo4j.dump --overwrite-destination=true

# 3. 重启 Neo4j
docker compose -p emerald start neo4j
```

### Redis 恢复

Redis 数据可丢失（仅缓存、会话、OAuth state）。如需恢复：

```bash
docker compose -p emerald stop redis
docker cp redis-YYYYMMDD-HHMMSS.rdb emerald-redis-1:/data/dump.rdb
docker compose -p emerald start redis
```

## 常见故障排查

| 症状 | 排查命令 | 修复方案 |
|---|---|---|
| Pod CrashLoopBackOff | `kubectl logs -n emerald <pod> --previous` | 检查应用日志，常见为环境变量缺失或数据库连接失败 |
| API 502/504 | `kubectl get events -n emerald --sort-by='.lastTimestamp'` | 检查上游 Postgres/Neo4j/Redis 健康 |
| 内存持续增长 | `kubectl top pods -n emerald` | 检查是否有内存泄漏；可能需要重启 pod |
| HPA 不扩容 | `kubectl describe hpa -n emerald emerald-api-hpa` | 检查 metrics-server 是否运行 |
| Ingress 404 | `kubectl describe ingress -n emerald` | 检查 ingressClassName 和 path 配置 |

## 监控接入

Prometheus 通过标准 `kubernetes_sd_configs` 自动发现 emerald-api pod。

关键指标：
- `emerald_search_latency_seconds` (P50, P99)
- `emerald_pipeline_jobs_total` (按状态分组)
- `emerald_facts_total` (按 memory_type 分组)

告警规则建议（详见 `docs/deployment/observability.md`）：
- API P99 > 1s 持续 5 分钟
- Pipeline 失败率 > 5%
- 内存使用 > 80%
