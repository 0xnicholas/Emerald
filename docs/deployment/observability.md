# Emerald 可观测性配置

## OpenTelemetry 架构

```
┌─────────────────┐
│ emerald-api     │──┐
│ (FastAPI+OTEL)  │  │
└─────────────────┘  │   OTLP gRPC (4317)
                     ├──→ ┌──────────────────────┐
┌─────────────────┐  │    │ OTel Collector        │
│ emerald-worker  │──┘    │ (DaemonSet/Deployment)│
│ (Celery+OTEL)   │       └──────────────────────┘
└─────────────────┘              │
                                 ├──→ Jaeger / Tempo (traces)
┌─────────────────┐              ├──→ Prometheus (metrics)
│ emerald-beat    │──────────────┤
│ (Celery Beat)   │              └──→ Loki / ES (logs)
└─────────────────┘
```

## 启用方式

### 自动 instrumentation

默认启用 httpx、asyncpg、redis、celery 四个库的自动追踪（FastAPI 已在 app 启动时强制接入）。

通过环境变量控制：

```bash
# 禁用某个 instrumentation
OTEL_INSTRUMENT_HTTPX=false
OTEL_INSTRUMENT_ASYNCPG=false

# 本地开发：span 打印到 stdout
OTEL_CONSOLE_EXPORTER=true

# 生产：发送到 OTLP collector
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

### 手动 span

```python
from emerald.core.tracing import get_tracer

tracer = get_tracer()

with tracer.start_as_current_span("pipeline.extract", attributes={
    "content_type": "markdown",
    "entity_id": "user_123",
}):
    # extraction work here
    pass
```

## Trace 服务映射

| Span name pattern | 组件 | 关键属性 |
|---|---|---|
| `POST /v1/memories` | emerald-api | entity_id, memory_type |
| `pipeline.extract` | emerald-worker | content_type |
| `pipeline.chunk` | emerald-worker | chunk_count |
| `pipeline.embed` | emerald-worker | embedding_dim |
| `pipeline.index` | emerald-worker | memory_ids |
| `search.expand_relationships` | emerald-api | expansion_count |
| `graph.get_related_memories` | emerald-api | rel_types |

## Collector 部署

最小配置示例：

```yaml
# otel-collector.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

exporters:
  prometheusremotewrite:
    endpoint: http://prometheus:9090/api/v1/write
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [otlp/jaeger]
    metrics:
      receivers: [otlp]
      exporters: [prometheusremotewrite]
```

## 告警规则建议

```yaml
# alerts.yaml
- alert: EmeraldAPILatencyHigh
  expr: histogram_quantile(0.99, http_server_request_duration_seconds_bucket{service="emerald-api"}) > 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Emerald API P99 > 1s"

- alert: EmeraldPipelineFailureRate
  expr: rate(emerald_pipeline_jobs_total{status="failed"}[5m]) > 0.05
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Pipeline failure rate > 5%"
```

## 本地开发（无需 collector）

```bash
# 所有 spans 直接打印到 stdout
export OTEL_CONSOLE_EXPORTER=true
uvicorn emerald.api.app:app --reload
# 每次请求会看到 spans 输出到控制台
```

## 日志关联

structlog 自动在每个日志记录中注入 `trace_id` 和 `span_id`。在 Jaeger/Tempo 中可以直接通过 trace_id 查到对应日志行，反之亦然。

示例日志输出：

```json
{
  "event": "pipeline.complete",
  "level": "info",
  "trace_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
  "span_id": "1234567890abcdef",
  "entity_id": "user_123",
  "memory_count": 5
}
```
