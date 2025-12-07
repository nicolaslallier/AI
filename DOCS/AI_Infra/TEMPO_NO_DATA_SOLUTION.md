# Tempo Dashboard - No Data Solution

## Issue Summary

**Problem:** The Tempo dashboard in Grafana shows "No Data"

**Root Cause:** Tempo is a distributed tracing backend that requires applications to send trace data. Currently, no applications are instrumented with OpenTelemetry, so there are no traces being ingested.

**Status:**
- ✅ Tempo service is running and healthy
- ✅ Grafana datasource is configured correctly
- ✅ Dashboard exists and is properly configured
- ❌ No applications are sending traces to Tempo

## Quick Fix (Testing)

To see Tempo working immediately, enable the test trace generator:

### Step 1: Edit docker-compose.yml

Uncomment the `tempo-trace-generator` service (around line 184-202):

```yaml
# From:
  # tempo-trace-generator:
  #   build:
  #     context: ./docker/tempo

# To:
  tempo-trace-generator:
    build:
      context: ./docker/tempo
      dockerfile: Dockerfile.test
```

### Step 2: Start the generator

```bash
make tempo-start-test-generator
# or
docker-compose up -d --build tempo-trace-generator
```

### Step 3: View traces

Wait 30-60 seconds, then open:
- Dashboard: http://localhost/monitoring/grafana/ → Dashboards → Tempo Overview
- Explorer: http://localhost/monitoring/grafana/ → Explore → Select Tempo datasource

### Step 4: Stop when done

```bash
make tempo-stop-test-generator
# or
docker-compose stop tempo-trace-generator
```

## Production Solution (Instrument Your Apps)

For production use, instrument your applications with OpenTelemetry:

### Python Example
```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# Configure tracer
trace.set_tracer_provider(TracerProvider())
otlp_exporter = OTLPSpanExporter(endpoint="http://tempo:4318/v1/traces")
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(otlp_exporter))
```

### Node.js Example
```javascript
const { NodeSDK } = require('@opentelemetry/sdk-node');
const { OTLPTraceExporter } = require('@opentelemetry/exporter-trace-otlp-http');

const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter({
    url: 'http://tempo:4318/v1/traces',
  }),
});
sdk.start();
```

## Files Created

1. **docker/tempo/test-traces.py** - Python script that generates sample traces
2. **docker/tempo/requirements.txt** - Python dependencies for trace generator
3. **docker/tempo/Dockerfile.test** - Docker image for trace generator
4. **TEMPO_TRACING_SETUP.md** - Comprehensive setup and instrumentation guide
5. **TEMPO_QUICK_START.md** - Quick reference for getting started
6. **TEMPO_NO_DATA_SOLUTION.md** - This file

## Make Commands Added

```bash
make tempo-start-test-generator  # Start the test trace generator
make tempo-stop-test-generator   # Stop the test trace generator
make tempo-logs                  # View Tempo service logs
make tempo-logs-generator        # View trace generator logs
make tempo-metrics               # Check Tempo metrics
make tempo-status                # Check Tempo health and status
```

## Understanding the Architecture

```
┌─────────────────────────────────────────┐
│        Applications (Instrumented)      │
│  - Frontend (Browser OpenTelemetry)     │
│  - Backend APIs (Python/Node.js)        │
│  - Workers (Background jobs)            │
└─────────────────┬───────────────────────┘
                  │
                  │ OTLP Protocol
                  │ HTTP: tempo:4318
                  │ gRPC: tempo:4317
                  │
┌─────────────────▼───────────────────────┐
│              Tempo                      │
│  ┌──────────────────────────────┐      │
│  │ Distributor (Receives)       │      │
│  │ Ingester (Processes)         │      │
│  │ Querier (Searches)           │      │
│  │ Compactor (Optimizes)        │      │
│  │ Metrics Generator (Exports)  │      │
│  └──────────┬───────────────────┘      │
└─────────────┼──────────────────────────┘
              │
              ├─► Storage (Local/S3)
              │
              └─► Prometheus (Span Metrics)
                  │
                  └─► Grafana (Visualization)
```

## Key Concepts

### What is Distributed Tracing?

Distributed tracing tracks requests as they flow through microservices:

1. **Trace**: Complete journey of a request
2. **Span**: Single operation within a trace
3. **Trace ID**: Unique identifier linking all spans
4. **Span ID**: Unique identifier for each span

### Example Trace

```
Request: GET /api/orders/123

Trace ID: abc123...

├─ Span: api-gateway (200ms)
│  ├─ Span: authenticate (50ms)
│  ├─ Span: database-query (100ms)
│  │  └─ Span: postgres-connect (10ms)
│  └─ Span: cache-check (20ms)
└─ Span: response-format (30ms)
```

## Why Use Tempo?

### Benefits

1. **Debug Production Issues**: See exactly where requests slow down or fail
2. **Performance Optimization**: Identify bottlenecks across services
3. **Service Dependencies**: Visualize how services interact
4. **Error Investigation**: Trace errors back to their source
5. **Cost Effective**: Stores traces in object storage, not expensive databases

### Use Cases

- **Troubleshooting**: "Why is this endpoint slow?"
- **Optimization**: "Which database query takes the longest?"
- **Dependencies**: "Which services does this API call?"
- **Error Investigation**: "Where did this error originate?"
- **SLA Monitoring**: "Are we meeting our latency targets?"

## Integration with Other Tools

### Tempo + Prometheus
- Tempo generates metrics from traces (span metrics, service graphs)
- These metrics are written to Prometheus
- Use Prometheus to alert on trace-derived metrics

### Tempo + Loki
- Correlate traces with logs
- Click a trace span → jump to related logs
- Click a log entry → jump to related trace

### Tempo + Grafana
- Visualize traces in timeline view
- Search traces by tags/attributes
- Explore service graphs
- Create dashboards from trace metrics

## Next Steps

1. ✅ **Understand the problem** - You're here!
2. 🚀 **Enable test generator** - See Tempo working immediately
3. 📚 **Read setup guide** - Learn instrumentation (TEMPO_TRACING_SETUP.md)
4. 🔧 **Instrument your apps** - Add OpenTelemetry to your code
5. 📊 **Create dashboards** - Build custom views in Grafana
6. 🚨 **Set up alerts** - Alert on trace-derived metrics

## Resources

- **Full Setup Guide**: [TEMPO_TRACING_SETUP.md](./TEMPO_TRACING_SETUP.md)
- **Quick Start**: [TEMPO_QUICK_START.md](./TEMPO_QUICK_START.md)
- **Tempo Docs**: https://grafana.com/docs/tempo/latest/
- **OpenTelemetry**: https://opentelemetry.io/docs/
- **OpenTelemetry Python**: https://opentelemetry.io/docs/instrumentation/python/
- **OpenTelemetry JavaScript**: https://opentelemetry.io/docs/instrumentation/js/

## Verification Checklist

After enabling the trace generator, verify:

- [ ] Trace generator container is running: `docker ps | grep tempo-trace-generator`
- [ ] Traces are being generated: `docker logs ai_infra_tempo_trace_generator`
- [ ] Tempo is receiving spans: `make tempo-metrics`
- [ ] Dashboard shows data in Grafana (wait 60s)
- [ ] Can search traces in Grafana Explore
- [ ] Can view individual trace timelines

## Common Questions

**Q: Why not use Jaeger?**
A: Tempo is more cost-effective (uses object storage), simpler to operate, and integrates better with Grafana stack.

**Q: Do I need to instrument all services?**
A: No, but you'll get more value with more services instrumented. Start with critical paths.

**Q: What about frontend tracing?**
A: Yes! Use OpenTelemetry in the browser to trace user interactions.

**Q: How much data will this generate?**
A: Use sampling in production (e.g., 10% of traces). The test generator is for demonstration only.

**Q: Can I search traces by custom attributes?**
A: Yes! Add attributes to spans, then search by them in Grafana.

**Q: How long are traces stored?**
A: Configurable. Default is 48 hours. Adjust in `docker/tempo/tempo.yml`.

---

## Summary

**The Tempo dashboard has no data because no applications are sending traces.** This is expected behavior for a new setup. Enable the test trace generator to see Tempo working, then instrument your applications for production use.

For immediate results:
```bash
make tempo-start-test-generator
```

For production setup, see [TEMPO_TRACING_SETUP.md](./TEMPO_TRACING_SETUP.md).

