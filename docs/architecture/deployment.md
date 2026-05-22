# 部署方案

本文档涵盖 Emerald 的开发环境（Docker Compose）和生产环境（Kubernetes）部署方案。

---

## 1. Docker Compose 开发环境

### 1.1 服务拓扑

```
┌─────────────────────────────────────────────────────────┐
│                     Docker Network                       │
│                                                          │
│  ┌────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Nginx  │  │ Emerald  │  │ Celery   │  │ Celery   │  │
│  │ :80    │  │ API      │  │ Worker   │  │ Beat     │  │
│  │        │  │ :8000    │  │          │  │          │  │
│  └───┬────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │
│      │            │              │              │         │
│      └────────────┴──────────────┴──────────────┘         │
│                          │                                │
│              ┌───────────┼───────────┐                    │
│              │           │           │                    │
│        ┌─────▼────┐ ┌───▼───┐ ┌─────▼────┐              │
│        │ Neo4j    │ │Postgre│ │ Redis    │              │
│        │ :7474    │ │SQL    │ │ :6379    │              │
│        │ :7687    │ │ :5432 │ │          │              │
│        └──────────┘ └───────┘ └──────────┘              │
│                                                          │
│              ┌──────────────┐                            │
│              │ MinIO        │                            │
│              │ :9000 :9001  │                            │
│              └──────────────┘                            │
└─────────────────────────────────────────────────────────┘
```

### 1.2 docker-compose.yml

```yaml
version: "3.8"

services:
  # ============================================
  # API 服务
  # ============================================
  api:
    build:
      context: .
      dockerfile: Dockerfile
      target: development
    container_name: emerald-api
    command: uvicorn emerald.api.app:app --host 0.0.0.0 --port 8000 --reload
    ports:
      - "8000:8000"
    volumes:
      - .:/app
    env_file:
      - .env
    depends_on:
      postgres:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      redis:
        condition: service_healthy
      minio:
        condition: service_healthy
    networks:
      - emerald-net

  # ============================================
  # Celery Worker
  # ============================================
  worker:
    build:
      context: .
      dockerfile: Dockerfile
      target: development
    container_name: emerald-worker
    command: celery -A emerald.pipeline.tasks worker --loglevel=info --concurrency=4
    volumes:
      - .:/app
    env_file:
      - .env
    depends_on:
      - api
      - redis
      - postgres
      - neo4j
    networks:
      - emerald-net

  # ============================================
  # Celery Beat (定时任务)
  # ============================================
  beat:
    build:
      context: .
      dockerfile: Dockerfile
      target: development
    container_name: emerald-beat
    command: celery -A emerald.pipeline.tasks beat --loglevel=info
    volumes:
      - .:/app
    env_file:
      - .env
    depends_on:
      - redis
      - postgres
    networks:
      - emerald-net

  # ============================================
  # PostgreSQL + pgvector
  # ============================================
  postgres:
    image: pgvector/pgvector:pg16
    container_name: emerald-postgres
    environment:
      POSTGRES_DB: emerald
      POSTGRES_USER: emerald
      POSTGRES_PASSWORD: emerald_dev
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./migrations/init:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U emerald"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - emerald-net

  # ============================================
  # Neo4j (知识图谱)
  # ============================================
  neo4j:
    image: neo4j:5-community
    container_name: emerald-neo4j
    environment:
      NEO4J_AUTH: neo4j/emerald_dev
      NEO4J_PLUGINS: '["apoc"]'
    ports:
      - "7474:7474"  # HTTP
      - "7687:7687"  # Bolt
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    healthcheck:
      test: ["CMD", "cypher-shell", "-u", "neo4j", "-p", "emerald_dev", "RETURN 1"]
      interval: 10s
      timeout: 10s
      retries: 10
    networks:
      - emerald-net

  # ============================================
  # Redis
  # ============================================
  redis:
    image: redis:7-alpine
    container_name: emerald-redis
    command: redis-server --appendonly yes --requirepass emerald_dev
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - emerald-net

  # ============================================
  # MinIO (文件存储)
  # ============================================
  minio:
    image: minio/minio:latest
    container_name: emerald-minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: emerald_admin
      MINIO_ROOT_PASSWORD: emerald_dev123
    ports:
      - "9000:9000"  # API
      - "9001:9001"  # Console
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - emerald-net

  # ============================================
  # MinIO 初始化 (自动创建 bucket)
  # ============================================
  minio-init:
    image: minio/mc:latest
    container_name: emerald-minio-init
    entrypoint: >
      /bin/sh -c "
      until mc alias set local http://minio:9000 emerald_admin emerald_dev123; do
        echo 'Waiting for MinIO...'; sleep 2;
      done;
      mc mb --ignore-existing local/emerald-documents;
      mc mb --ignore-existing local/emerald-temp;
      mc ilm rule add --expire-days 1 local/emerald-temp;
      echo 'Buckets created';
      exit 0;
      "
    depends_on:
      minio:
        condition: service_healthy
    networks:
      - emerald-net

  # ============================================
  # Nginx (反向代理)
  # ============================================
  nginx:
    image: nginx:alpine
    container_name: emerald-nginx
    ports:
      - "80:80"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - api
    networks:
      - emerald-net

volumes:
  postgres_data:
  neo4j_data:
  neo4j_logs:
  redis_data:
  minio_data:

networks:
  emerald-net:
    driver: bridge
```

### 1.3 Dockerfile

```dockerfile
# Dockerfile
FROM python:3.12-slim AS development

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

FROM python:3.12-slim AS production

WORKDIR /app
# 生产构建（省略详细）
COPY --from=development /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY . .
CMD ["uvicorn", "emerald.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 1.4 Nginx 配置

```nginx
# nginx.conf
events {}

http {
    upstream emerald_api {
        server api:8000;
    }

    server {
        listen 80;

        # 客户端上传大小限制
        client_max_body_size 50m;

        location /v1/upload {
            proxy_pass http://emerald_api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 120s;
        }

        location / {
            proxy_pass http://emerald_api;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
        }
    }
}
```

---

## 2. 环境变量

### 2.1 .env.example

```bash
# ============================================
# Emerald 核心配置
# ============================================
EMERALD_ENV=development              # development | production
EMERALD_LOG_LEVEL=INFO               # DEBUG | INFO | WARNING | ERROR

# ============================================
# API 密钥
# ============================================
API_KEY_SECRET=your-secret-here      # 用于生成/验证 API Key 的 HMAC 密钥
ENCRYPTION_KEY=...                   # 64 位十六进制 (32 bytes)，用于加密 connector credentials

# ============================================
# PostgreSQL
# ============================================
DATABASE_URL=postgresql+asyncpg://emerald:emerald_dev@postgres:5432/emerald
DATABASE_URL_SYNC=postgresql://emerald:emerald_dev@postgres:5432/emerald

# ============================================
# Neo4j
# ============================================
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=emerald_dev

# ============================================
# Redis
# ============================================
REDIS_URL=redis://:emerald_dev@redis:6379/0

# ============================================
# Celery
# ============================================
CELERY_BROKER_URL=redis://:emerald_dev@redis:6379/1
CELERY_RESULT_BACKEND=redis://:emerald_dev@redis:6379/2

# ============================================
# MinIO
# ============================================
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=emerald_admin
MINIO_SECRET_KEY=emerald_dev123
MINIO_BUCKET=emerald-documents
MINIO_SECURE=false

# ============================================
# 嵌入模型
# ============================================
EMBEDDING_PROVIDER=openai             # openai | bge | text2vec | local
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
BGE_MODEL_PATH=/models/bge-large-zh-v1.5

# ============================================
# OCR / 语音识别
# ============================================
TESSERACT_LANG=chi_sim+eng
WHISPER_MODEL_SIZE=small              # tiny | small | medium | large

# ============================================
# 连接器 OAuth 配置
# ============================================
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
NOTION_CLIENT_ID=...
NOTION_CLIENT_SECRET=...
GITHUB_APP_ID=...
GITHUB_APP_PRIVATE_KEY=...
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...

# ============================================
# 速率限制
# ============================================
RATE_LIMIT_MEMORIES=60
RATE_LIMIT_SEARCH=120
RATE_LIMIT_PROFILES=300
RATE_LIMIT_UPLOAD=10
```

---

## 3. 数据库初始化

### 3.1 PostgreSQL 初始化脚本

```sql
-- migrations/init/01_extensions.sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

```sql
-- migrations/init/02_tables.sql
-- 见数据模型文档中的完整建表语句
```

### 3.2 Alembic 迁移

```bash
# 初始化
alembic init migrations/alembic

# 生成迁移
alembic revision --autogenerate -m "initial schema"

# 执行迁移
alembic upgrade head

# 回滚
alembic downgrade -1
```

### 3.3 Neo4j 初始化

```cypher
-- 初始约束
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT memory_id_unique IF NOT EXISTS FOR (m:Memory) REQUIRE m.id IS UNIQUE;
CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE;

CREATE INDEX entity_external_id FOR (e:Entity) ON (e.external_id, e.type);
CREATE INDEX memory_entity FOR (m:Memory) ON (m.is_latest, m.memory_type);
CREATE INDEX memory_temporal FOR (m:Memory) ON (m.valid_until);
CREATE INDEX memory_expired FOR (m:Memory) ON (m.expired_at);
```

---

## 4. 生产环境 (Kubernetes)

### 4.1 资源需求评估

| 服务 | CPU 请求 | CPU 上限 | 内存请求 | 内存上限 | 副本数 |
|---|---|---|---|---|---|
| API | 500m | 2 | 512Mi | 2Gi | 2-4 |
| Worker | 1 | 4 | 1Gi | 8Gi | 2-4 |
| Beat | 100m | 500m | 256Mi | 512Mi | 1 |
| Neo4j | 2 | 8 | 4Gi | 16Gi | 1-3 (集群) |
| PostgreSQL | 1 | 4 | 2Gi | 8Gi | 1-3 (HA) |
| Redis | 250m | 1 | 512Mi | 2Gi | 1-3 (Sentinel) |
| MinIO | 500m | 2 | 1Gi | 4Gi | 1-4 (分布式) |

### 4.2 K8s 部署结构

```yaml
# k8s/emerald/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: emerald
---
# k8s/emerald/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: emerald-config
  namespace: emerald
data:
  EMERALD_ENV: "production"
  EMERALD_LOG_LEVEL: "INFO"
  EMBEDDING_PROVIDER: "openai"
  # ... 非敏感配置
---
# k8s/emerald/secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: emerald-secrets
  namespace: emerald
type: Opaque
stringData:
  DATABASE_URL: "postgresql+asyncpg://emerald:..."
  NEO4J_PASSWORD: "..."
  REDIS_URL: "redis://:..."
  OPENAI_API_KEY: "sk-..."
  ENCRYPTION_KEY: "..."
  # ... 敏感配置
---
# k8s/emerald/deployment-api.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: emerald-api
  namespace: emerald
spec:
  replicas: 3
  selector:
    matchLabels:
      app: emerald-api
  template:
    metadata:
      labels:
        app: emerald-api
    spec:
      containers:
        - name: api
          image: emerald-api:latest
          ports:
            - containerPort: 8000
          envFrom:
            - configMapRef:
                name: emerald-config
            - secretRef:
                name: emerald-secrets
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: 2
              memory: 2Gi
          livenessProbe:
            httpGet:
              path: /v1/health
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 15
          readinessProbe:
            httpGet:
              path: /v1/health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 10
---
# k8s/emerald/service-api.yaml
apiVersion: v1
kind: Service
metadata:
  name: emerald-api
  namespace: emerald
spec:
  selector:
    app: emerald-api
  ports:
    - port: 8000
      targetPort: 8000
---
# k8s/emerald/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: emerald-ingress
  namespace: emerald
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "120"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  tls:
    - hosts:
        - api.emerald.ai
      secretName: emerald-tls
  rules:
    - host: api.emerald.ai
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: emerald-api
                port:
                  number: 8000
---
# k8s/emerald/hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: emerald-api-hpa
  namespace: emerald
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: emerald-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
```

---

## 5. 备份策略

| 数据 | 备份工具 | 频率 | 保留 |
|---|---|---|---|
| PostgreSQL | `pg_dump` / WAL-G | 每日全量 + WAL 持续归档 | 30 天 |
| Neo4j | `neo4j-admin dump` | 每日全量 | 30 天 |
| Redis | `redis-cli BGSAVE` (RDB) | 每 6 小时 | 7 天 |
| MinIO | `mc mirror` | 每日增量 | 90 天 |

### 5.1 备份 CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: emerald-backup
  namespace: emerald
spec:
  schedule: "0 2 * * *"  # 每天凌晨 2 点
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              image: emerald-backup:latest
              env:
                - name: BACKUP_S3_BUCKET
                  value: emerald-backups
              command:
                - /bin/sh
                - -c
                - |
                  pg_dump $DATABASE_URL_SYNC | gzip > /backups/postgres_$(date +%Y%m%d).sql.gz
                  neo4j-admin dump --database=neo4j --to=/backups/neo4j_$(date +%Y%m%d).dump
                  aws s3 sync /backups/ s3://$BACKUP_S3_BUCKET/
          restartPolicy: OnFailure
```

---

## 6. 监控 (Prometheus + Grafana)

### 6.1 Prometheus 指标端点

FastAPI 应用通过 `prometheus-fastapi-instrumentator` 自动暴露指标：

| 指标 | 类型 | 标签 |
|---|---|---|
| `http_requests_total` | Counter | method, endpoint, status |
| `http_request_duration_seconds` | Histogram | method, endpoint |
| `pipeline_duration_seconds` | Histogram | stage, content_type |
| `pipeline_jobs_total` | Counter | status |
| `memory_count_total` | Gauge | entity_id |
| `profile_cache_hit_ratio` | Gauge | - |
| `celery_tasks_total` | Counter | task_name, status |
| `db_connections_active` | Gauge | database (postgres/neo4j/redis) |

### 6.2 告警规则

```yaml
# k8s/monitoring/prometheus-rules.yaml
groups:
  - name: emerald
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "HTTP 5xx 错误率超过 5%"

      - alert: PipelineBacklog
        expr: pipeline_jobs_total{status="queued"} > 100
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "管线积压任务超过 100 个"

      - alert: ProfileCacheMissHigh
        expr: profile_cache_hit_ratio < 0.8
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "画像缓存命中率低于 80%"
```

---

## 7. 日志

所有服务输出结构化 JSON 日志到 stdout，由集群日志采集器（如 Fluentd/Loki）收集。

```python
# emerald/core/logging.py
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

logger = structlog.get_logger()
```

---

## 8. 安全检查清单

- [ ] 所有服务间通信使用 TLS
- [ ] 密钥通过 K8s Secret 或 Vault 注入，不进镜像
- [ ] API Key 仅存储 SHA-256 哈希
- [ ] OAuth credentials 使用 AES-256-GCM 加密存储
- [ ] 数据库密码不写入环境变量（使用 Secret）
- [ ] 文件上传限制 50MB，MIME 类型白名单
- [ ] 定时安全更新基础镜像
- [ ] API 速率限制已启用
- [ ] 健康检查端点不暴露内部状态
