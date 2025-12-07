# Tempo Quick Start - See Traces in 60 Seconds

## Why No Data?

Tempo is a **distributed tracing backend** that needs applications to send trace data. Currently, no applications are instrumented, so there's no data to display.

## Quick Solution: Enable Test Trace Generator

### 1. Uncomment the trace generator in docker-compose.yml

Find this section (around line 184) and uncomment it:

```yaml
# Change from:
  # tempo-trace-generator:
  #   build:

# To:
  tempo-trace-generator:
    build:
```

### 2. Start the trace generator

```bash
# Option A: Using Make
make tempo-start-test-generator

# Option B: Using Docker Compose
docker-compose up -d --build tempo-trace-generator
```

### 3. Verify it's working

```bash
# Check logs (should show traces being generated)
docker logs -f ai_infra_tempo_trace_generator

# You should see:
# ✅ Generated trace #1: user-request
# ✅ Generated trace #2: order-processing
```

### 4. View traces in Grafana

1. Open: http://localhost/monitoring/grafana/
2. Go to: **Dashboards** → **Tempo Overview**
3. Wait 30-60 seconds for data to appear
4. You'll see:
   - 📊 Spans received rate
   - 🔥 Live traces count
   - 📈 Ingestion rate
   - ⏱️ Query latency

### 5. Explore individual traces

1. In Grafana, click **Explore** (compass icon)
2. Select **Tempo** datasource
3. Choose **Search** tab
4. Filter by service: `test-service`
5. Click any trace to see the full timeline with spans

### 6. Stop when done testing

```bash
# Option A: Using Make
make tempo-stop-test-generator

# Option B: Using Docker Compose
docker-compose stop tempo-trace-generator
```

## Make Commands Reference

```bash
make tempo-start-test-generator  # Start generating test traces
make tempo-stop-test-generator   # Stop generating test traces
make tempo-logs                  # View Tempo service logs
make tempo-logs-generator        # View trace generator logs
make tempo-metrics               # Check Tempo metrics
make tempo-status                # Check Tempo health and status
```

## For Production: Instrument Your Apps

See [TEMPO_TRACING_SETUP.md](./TEMPO_TRACING_SETUP.md) for:
- Python/FastAPI instrumentation
- Node.js/Express instrumentation
- OpenTelemetry configuration
- Best practices
- Troubleshooting

## Architecture Overview

```
Your Apps          Tempo           Grafana
   |                |                |
   |  Send Traces   |                |
   |--------------->|                |
   |  (OTLP)        |                |
   |                | Store &        |
   |                | Process        |
   |                |                |
   |                | Query Traces   |
   |                |<---------------|
   |                |                |
```

## Quick Checks

**Is Tempo running?**
```bash
docker ps | grep tempo
# Should show: ai_infra_tempo
```

**Are traces being received?**
```bash
make tempo-metrics
# Should show non-zero spans_received_total
```

**Can I query Tempo directly?**
```bash
curl http://localhost:3200/ready
# Should return: 200 OK
```

## Troubleshooting

**Problem:** Trace generator won't start

**Solution:** Uncomment the service in docker-compose.yml first

---

**Problem:** Still no data after starting generator

**Solution:** Wait 30-60 seconds, traces are batched

---

**Problem:** Dashboard shows errors

**Solution:** Check time range (top right) - set to "Last 1 hour"

---

## Need More Help?

- Full documentation: [TEMPO_TRACING_SETUP.md](./TEMPO_TRACING_SETUP.md)
- Tempo docs: https://grafana.com/docs/tempo/latest/
- OpenTelemetry: https://opentelemetry.io/docs/

