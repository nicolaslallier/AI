# Tempo Tracing Setup Guide

## Problem: No Data in Tempo Dashboard

The Tempo dashboard shows "No Data" because **no applications are currently sending traces** to Tempo. Tempo is a distributed tracing backend that requires applications to be instrumented with OpenTelemetry to send trace data.

## Understanding Tempo

### What is Tempo?
Tempo is Grafana's distributed tracing backend that stores and queries traces. It's designed to be:
- **Cost-effective**: Stores traces in object storage (local, S3, GCS)
- **Scalable**: Designed for high-throughput tracing
- **Integrated**: Works seamlessly with Grafana, Prometheus, and Loki

### Current Setup Status

✅ **Tempo is running and healthy**
- Service: `ai_infra_tempo` on port 3200
- OTLP HTTP receiver: `tempo:4318`
- OTLP gRPC receiver: `tempo:4317`
- Jaeger receivers: `14250` (gRPC), `14268` (HTTP)

✅ **Grafana datasource configured**
- Tempo datasource is provisioned in Grafana
- Dashboard exists: "Tempo Overview"
- Linked to Prometheus for service graphs

❌ **No traces are being ingested**
- No applications are instrumented with OpenTelemetry
- No traces being sent to Tempo endpoints
- Dashboard shows empty metrics

## Solutions

### Option 1: Enable Test Trace Generator (Quick Testing)

To see Tempo in action immediately, enable the test trace generator:

#### Step 1: Uncomment the trace generator service

Edit `docker-compose.yml` and uncomment the `tempo-trace-generator` service (lines ~184-202):

```yaml
# Change this:
  # tempo-trace-generator:
  #   build:
  #     context: ./docker/tempo

# To this:
  tempo-trace-generator:
    build:
      context: ./docker/tempo
```

#### Step 2: Start the trace generator

```bash
# Rebuild and start the trace generator
docker-compose up -d --build tempo-trace-generator

# Check logs to verify it's sending traces
docker logs -f ai_infra_tempo_trace_generator
```

You should see output like:
```
🚀 Starting trace generator for Tempo...
📡 Sending traces to: http://tempo:4318/v1/traces
✅ Generated trace #1: user-request
✅ Generated trace #2: order-processing
✅ Generated trace #3: error
```

#### Step 3: View traces in Grafana

1. Open Grafana: http://localhost/monitoring/grafana/
2. Navigate to: **Dashboards** → **Tempo Overview**
3. Wait 30-60 seconds for data to appear
4. You should see:
   - Spans received rate
   - Live traces count
   - Ingestion rate
   - Request latency

#### Step 4: Explore traces

1. In Grafana, go to **Explore** (compass icon)
2. Select **Tempo** datasource from dropdown
3. Choose **Search** tab
4. Filter by:
   - Service Name: `test-service`
   - Operation Name: `user-request`, `order-processing`, or `failed-request`
5. Click on any trace to see the full trace timeline

#### Step 5: Stop the trace generator (when done testing)

```bash
# Stop the trace generator
docker-compose stop tempo-trace-generator

# Or remove it entirely
docker-compose rm -f tempo-trace-generator
```

---

### Option 2: Instrument Your Applications (Production Use)

For production use, instrument your actual applications with OpenTelemetry.

#### Python/FastAPI Example

**Install dependencies:**
```bash
pip install opentelemetry-api \
            opentelemetry-sdk \
            opentelemetry-instrumentation-fastapi \
            opentelemetry-exporter-otlp-proto-http
```

**Add instrumentation to your FastAPI app:**

```python
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Configure OpenTelemetry
resource = Resource(attributes={
    "service.name": "my-api-service",
    "service.version": "1.0.0",
    "deployment.environment": "production"
})

# Create tracer provider
trace.set_tracer_provider(TracerProvider(resource=resource))

# Configure OTLP exporter to send to Tempo
otlp_exporter = OTLPSpanExporter(
    endpoint="http://tempo:4318/v1/traces"
)

# Add span processor
span_processor = BatchSpanProcessor(otlp_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

# Create FastAPI app
app = FastAPI()

# Instrument FastAPI (auto-generates spans for all endpoints)
FastAPIInstrumentor.instrument_app(app)

# Your routes here
@app.get("/api/users")
async def get_users():
    # Add custom spans for specific operations
    tracer = trace.get_tracer(__name__)
    
    with tracer.start_as_current_span("database-query") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.statement", "SELECT * FROM users")
        # Your database query here
        result = fetch_users()
    
    return result
```

#### Node.js/Express Example

**Install dependencies:**
```bash
npm install @opentelemetry/api \
            @opentelemetry/sdk-node \
            @opentelemetry/auto-instrumentations-node \
            @opentelemetry/exporter-trace-otlp-http
```

**Create tracing configuration (tracing.js):**

```javascript
const { NodeSDK } = require('@opentelemetry/sdk-node');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');
const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
const { Resource } = require('@opentelemetry/resources');
const { SemanticResourceAttributes } = require('@opentelemetry/semantic-conventions');

const sdk = new NodeSDK({
  resource: new Resource({
    [SemanticResourceAttributes.SERVICE_NAME]: 'my-node-service',
    [SemanticResourceAttributes.SERVICE_VERSION]: '1.0.0',
  }),
  traceExporter: new OTLPTraceExporter({
    url: 'http://tempo:4318/v1/traces',
  }),
  instrumentations: [getNodeAutoInstrumentations()],
});

sdk.start();

// Graceful shutdown
process.on('SIGTERM', () => {
  sdk.shutdown()
    .then(() => console.log('Tracing terminated'))
    .catch((error) => console.log('Error terminating tracing', error))
    .finally(() => process.exit(0));
});
```

**Load tracing in your app:**

```javascript
// Import tracing FIRST (before any other imports)
require('./tracing');

const express = require('express');
const app = express();

// Your routes here
app.get('/api/users', (req, res) => {
  // Auto-instrumented by OpenTelemetry
  res.json({ users: [] });
});

app.listen(3000);
```

#### Docker Compose Integration

Add tracing environment variables to your services:

```yaml
services:
  your-service:
    environment:
      # OpenTelemetry configuration
      OTEL_SERVICE_NAME: "your-service-name"
      OTEL_EXPORTER_OTLP_ENDPOINT: "http://tempo:4318"
      OTEL_EXPORTER_OTLP_PROTOCOL: "http/protobuf"
      OTEL_TRACES_EXPORTER: "otlp"
    networks:
      - monitoring-net  # Important: must be on monitoring network
```

---

### Option 3: Manual Trace Testing with curl

Send a test trace directly to Tempo using the OTLP HTTP endpoint:

```bash
# From inside a container on the monitoring network
docker exec -it ai_infra_prometheus sh

# Send a test trace (simplified OTLP format)
curl -X POST http://tempo:4318/v1/traces \
  -H "Content-Type: application/json" \
  -d '{
    "resourceSpans": [{
      "resource": {
        "attributes": [{
          "key": "service.name",
          "value": {"stringValue": "test-service"}
        }]
      },
      "scopeSpans": [{
        "spans": [{
          "traceId": "5B8EFFF798038103D269B633813FC60C",
          "spanId": "EEE19B7EC3C1B174",
          "name": "test-span",
          "kind": 1,
          "startTimeUnixNano": "1544712660000000000",
          "endTimeUnixNano": "1544712661000000000"
        }]
      }]
    }]
  }'
```

---

## Verifying Tempo Data Ingestion

### Check Prometheus Metrics

Tempo exposes metrics to Prometheus. Check if data is being received:

```bash
# From prometheus container
docker exec -it ai_infra_prometheus sh

# Check for spans received
wget -qO- http://tempo:3200/metrics | grep tempo_distributor_spans_received_total

# Check for live traces
wget -qO- http://tempo:3200/metrics | grep tempo_ingester_live_traces
```

If you see non-zero values, Tempo is receiving data!

### Check Tempo Logs

```bash
# View Tempo logs
docker logs ai_infra_tempo --tail 100

# Look for messages like:
# "msg"="Starting GRPC server"
# "msg"="Starting HTTP server"
```

### Query Tempo API Directly

```bash
# List trace IDs (requires traces to exist)
curl http://localhost:3200/api/traces

# Search for traces by tag
curl 'http://localhost:3200/api/search?tags=service.name=test-service'
```

---

## Architecture: How Tracing Works

```
┌─────────────────────────────────────────────────────────────────┐
│                     Application Services                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Frontend   │  │   API        │  │   Worker     │          │
│  │  (Browser)   │  │  (Python)    │  │  (Node.js)   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                  │                  │                  │
│         │ OpenTelemetry    │ OpenTelemetry    │ OpenTelemetry    │
│         │ SDK              │ SDK              │ SDK              │
│         └──────────────────┴──────────────────┘                  │
└─────────────────────────────────────────────────────────────────┘
                             ││
                             ││ OTLP Protocol
                             ││ (HTTP: 4318 or gRPC: 4317)
                             ▼▼
         ┌──────────────────────────────────────────┐
         │          Tempo (Tracing Backend)         │
         │                                           │
         │  ┌────────────┐  ┌─────────────────┐    │
         │  │ Distributor│  │   Ingester      │    │
         │  │ (Receives) │──│   (Processes)   │    │
         │  └────────────┘  └─────────┬───────┘    │
         │                             │            │
         │  ┌────────────┐  ┌─────────▼───────┐    │
         │  │  Querier   │──│   Storage       │    │
         │  │ (Queries)  │  │   (Local/S3)    │    │
         │  └──────┬─────┘  └─────────────────┘    │
         │         │                                │
         │  ┌──────▼──────────────────────────┐    │
         │  │  Metrics Generator              │    │
         │  │  (Service Graphs, Span Metrics) │    │
         │  └──────┬──────────────────────────┘    │
         └─────────┼─────────────────────────────────┘
                   │
                   │ Remote Write (span metrics)
                   ▼
         ┌─────────────────────────────────────────┐
         │           Prometheus                    │
         │      (Stores Trace Metrics)             │
         └─────────────────────────────────────────┘
                   ▲
                   │
         ┌─────────┴─────────────────────────────────┐
         │              Grafana                       │
         │  ┌──────────────────────────────────────┐ │
         │  │  Tempo Dashboard                     │ │
         │  │  - Spans received rate               │ │
         │  │  - Live traces                       │ │
         │  │  - Ingestion rate                    │ │
         │  │  - Query latency                     │ │
         │  └──────────────────────────────────────┘ │
         │  ┌──────────────────────────────────────┐ │
         │  │  Trace Explorer                      │ │
         │  │  - Search traces by tags             │ │
         │  │  - View trace timelines              │ │
         │  │  - Jump to logs (via Loki)          │ │
         │  └──────────────────────────────────────┘ │
         └────────────────────────────────────────────┘
```

---

## Tempo Configuration Reference

### Current Tempo Setup

**File:** `docker/tempo/tempo.yml`

```yaml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        http:
          endpoint: 0.0.0.0:4318  # OpenTelemetry HTTP
        grpc:
          endpoint: 0.0.0.0:4317  # OpenTelemetry gRPC
    jaeger:
      protocols:
        thrift_http:
          endpoint: 0.0.0.0:14268  # Jaeger HTTP
        grpc:
          endpoint: 0.0.0.0:14250  # Jaeger gRPC

metrics_generator:
  remote_write:
    - url: http://prometheus:9090/api/v1/write
      send_exemplars: true
  storage:
    path: /var/tempo/generator/wal
```

### Key Ports

| Port  | Protocol      | Purpose                          |
|-------|---------------|----------------------------------|
| 3200  | HTTP          | Tempo API, metrics, health       |
| 4317  | gRPC          | OTLP receiver (recommended)      |
| 4318  | HTTP          | OTLP receiver                    |
| 14250 | gRPC          | Jaeger receiver                  |
| 14268 | HTTP          | Jaeger receiver                  |

---

## Best Practices

### 1. Sampling Strategy

For production, implement sampling to reduce data volume:

```python
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

# Sample 10% of traces
sampler = TraceIdRatioBased(0.1)

trace.set_tracer_provider(TracerProvider(
    resource=resource,
    sampler=sampler
))
```

### 2. Span Attributes

Add meaningful attributes to spans:

```python
span.set_attribute("user.id", user_id)
span.set_attribute("http.method", "GET")
span.set_attribute("http.status_code", 200)
span.set_attribute("db.statement", sql_query)
```

### 3. Error Handling

Record exceptions in spans:

```python
try:
    result = risky_operation()
except Exception as e:
    span.record_exception(e)
    span.set_status(Status(StatusCode.ERROR, str(e)))
    raise
```

### 4. Correlation with Logs

Add trace context to logs:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)
span = trace.get_current_span()

logger.info(
    "Processing request",
    extra={
        "trace_id": span.get_span_context().trace_id,
        "span_id": span.get_span_context().span_id
    }
)
```

---

## Troubleshooting

### Problem: Still no data after instrumenting

**Check 1: Network connectivity**
```bash
# From your app container
curl http://tempo:4318/v1/traces
# Should return: 405 Method Not Allowed (POST required)
```

**Check 2: Verify app is on monitoring network**
```yaml
services:
  your-app:
    networks:
      - monitoring-net  # Must include this!
```

**Check 3: Check application logs**
```bash
docker logs your-app-container | grep -i "trace\|telemetry\|otlp"
```

### Problem: Traces not visible in Grafana

**Check 1: Wait for data to appear**
- Traces are batched and sent every few seconds
- Grafana dashboard refreshes every 10 seconds
- Wait 30-60 seconds after generating traces

**Check 2: Check time range**
- In Grafana, ensure time range includes recent data
- Default: "Last 1 hour" (top right)

**Check 3: Query Tempo directly**
```bash
# List recent traces
curl 'http://localhost:3200/api/search?limit=10'
```

### Problem: High memory usage

Tempo stores traces in memory before flushing. Adjust retention:

```yaml
# docker/tempo/tempo.yml
ingester:
  trace_idle_period: 10s
  max_block_bytes: 1_000_000
  max_block_duration: 5m
```

---

## Next Steps

1. **Start with test generator** to see Tempo working immediately
2. **Instrument your frontend** with OpenTelemetry for browser tracing
3. **Instrument your API services** for backend tracing
4. **Add custom spans** for critical business operations
5. **Set up alerts** based on trace metrics in Prometheus
6. **Correlate traces with logs** using trace IDs in log entries

---

## Resources

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [Tempo Documentation](https://grafana.com/docs/tempo/latest/)
- [OpenTelemetry Python Guide](https://opentelemetry.io/docs/instrumentation/python/)
- [OpenTelemetry JavaScript Guide](https://opentelemetry.io/docs/instrumentation/js/)
- [Grafana Tempo Best Practices](https://grafana.com/docs/tempo/latest/operations/best-practices/)

---

## Quick Commands Reference

```bash
# Enable test trace generator
docker-compose up -d --build tempo-trace-generator

# View trace generator logs
docker logs -f ai_infra_tempo_trace_generator

# Check Tempo metrics
docker exec -it ai_infra_prometheus wget -qO- http://tempo:3200/metrics | grep tempo_distributor

# Query traces via API
curl 'http://localhost:3200/api/search?tags=service.name=test-service'

# Stop trace generator
docker-compose stop tempo-trace-generator

# View Tempo logs
docker logs ai_infra_tempo --tail 100
```

