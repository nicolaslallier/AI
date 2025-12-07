# Tempo - No Data? Here's Why & How to Fix It 🔍

## TL;DR

**Problem:** Tempo dashboard shows "No Data"  
**Cause:** No apps are sending traces to Tempo  
**Quick Fix:** Enable test trace generator  
**Time:** 60 seconds to see traces

---

## 🚀 Quick Fix (3 Steps)

### 1️⃣ Edit `docker-compose.yml`

Find line ~184 and **uncomment**:

```yaml
  tempo-trace-generator:    # Remove the #
    build:                  # Remove the #
      context: ./docker/tempo
```

### 2️⃣ Start It

```bash
make tempo-start-test-generator
```

### 3️⃣ View Traces

Open: http://localhost/monitoring/grafana/

Navigate: **Dashboards** → **Tempo Overview**

Wait: 30 seconds for data to appear ⏱️

---

## 🎯 What You'll See

### Tempo Overview Dashboard
- **📊 Spans Received Rate** - Traces per second
- **🔥 Live Traces** - Active traces in memory
- **📈 Ingestion Rate** - Bytes per second
- **⏱️ Query Latency** - How fast queries run

### Explore Individual Traces
1. Click **Explore** (compass icon)
2. Select **Tempo** datasource
3. Choose **Search** tab
4. Filter: `service.name = test-service`
5. Click any trace to see timeline

---

## 📚 What Are Traces?

### Request Journey
```
User clicks button
    ↓
Frontend sends request
    ↓
API Gateway receives
    ↓
Authenticates user
    ↓
Queries database
    ↓
Checks cache
    ↓
Returns response
```

Each step = **Span**  
All steps together = **Trace**

### Example Trace Timeline
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ┌─────────────────────────────┐
    │ api-gateway (200ms)         │
    │  ┌──────────┐               │
    │  │ auth (50) │               │
    │  └──────────┘               │
    │     ┌─────────────────┐     │
    │     │ db-query (100)  │     │
    │     └─────────────────┘     │
    │              ┌───────┐      │
    │              │cache  │      │
    │              │(20ms) │      │
    │              └───────┘      │
    └─────────────────────────────┘
```

---

## 🔧 For Production: Instrument Your Apps

### Python (FastAPI)

```python
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# Setup once at startup
otlp_exporter = OTLPSpanExporter(
    endpoint="http://tempo:4318/v1/traces"
)
trace.get_tracer_provider().add_span_processor(
    BatchSpanProcessor(otlp_exporter)
)

# Auto-instrument FastAPI
FastAPIInstrumentor.instrument_app(app)
```

### Node.js (Express)

```javascript
const { NodeSDK } = require('@opentelemetry/sdk-node');

const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter({
    url: 'http://tempo:4318/v1/traces',
  }),
});
sdk.start();
```

---

## 🎮 Make Commands

```bash
make tempo-start-test-generator  # Start traces
make tempo-logs-generator        # View logs
make tempo-metrics               # Check metrics
make tempo-status                # Health check
make tempo-stop-test-generator   # Stop traces
```

---

## 🏗️ Architecture

```
┌─────────────┐
│   Your App  │ Instrumented with OpenTelemetry
└──────┬──────┘
       │ Sends traces (OTLP)
       ↓
┌─────────────┐
│    Tempo    │ Stores & processes traces
└──────┬──────┘
       │ Generates metrics
       ↓
┌─────────────┐
│ Prometheus  │ Stores trace metrics
└──────┬──────┘
       │
       ↓
┌─────────────┐
│   Grafana   │ Visualizes everything
└─────────────┘
```

---

## ✅ Checklist

After starting trace generator:

- [ ] Container running: `docker ps | grep trace-generator`
- [ ] Logs show traces: `make tempo-logs-generator`
- [ ] Metrics show data: `make tempo-metrics`
- [ ] Dashboard shows graphs (wait 60s)
- [ ] Can explore traces in Grafana

---

## 🆘 Troubleshooting

| Problem | Solution |
|---------|----------|
| Generator won't start | Uncomment service in docker-compose.yml |
| Still no data | Wait 60 seconds, check time range in Grafana |
| Dashboard errors | Set time range to "Last 1 hour" |
| Container exits | Check logs: `docker logs ai_infra_tempo_trace_generator` |

---

## 📖 More Info

| Document | Purpose |
|----------|---------|
| **TEMPO_QUICK_START.md** | Step-by-step guide |
| **TEMPO_TRACING_SETUP.md** | Full instrumentation guide |
| **TEMPO_NO_DATA_SOLUTION.md** | Detailed explanation |

---

## 🎓 Key Concepts

**Trace** = Complete request journey  
**Span** = Single operation in a trace  
**Trace ID** = Unique identifier linking spans  
**OTLP** = OpenTelemetry Protocol (how traces are sent)

---

## 🌟 Why Use Tracing?

1. **Debug Issues** - See where requests slow down
2. **Find Errors** - Trace errors to their source
3. **Optimize** - Identify bottlenecks
4. **Understand** - Visualize service dependencies
5. **Monitor** - Track SLA compliance

---

## 🎯 Next Steps

1. ✅ Enable test generator (see it work)
2. 📖 Read TEMPO_TRACING_SETUP.md
3. 🔧 Instrument your frontend
4. 🔧 Instrument your backend
5. 📊 Create custom dashboards
6. 🚨 Set up alerts

---

## 🔗 Quick Links

- **Dashboard**: http://localhost/monitoring/grafana/
- **Tempo API**: http://localhost:3200/metrics
- **Tempo Docs**: https://grafana.com/docs/tempo/latest/
- **OpenTelemetry**: https://opentelemetry.io/docs/

---

## 💡 Pro Tips

1. **Sampling**: In production, sample 10% of traces to reduce data
2. **Attributes**: Add custom attributes to spans for better filtering
3. **Errors**: Always record exceptions in spans
4. **Context**: Propagate trace context between services
5. **Logs**: Link logs to traces using trace IDs

---

**Need help?** Check TEMPO_TRACING_SETUP.md for detailed guides!

**Want to test?** Run: `make tempo-start-test-generator`

**Ready for production?** Instrument your apps with OpenTelemetry!

