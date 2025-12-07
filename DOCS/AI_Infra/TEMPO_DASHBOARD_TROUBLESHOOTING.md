# Tempo Dashboard Troubleshooting - Data Is There!

## ✅ Current Status (VERIFIED)

Your monitoring stack is working correctly:

```
✅ Trace Generator: Running and sending traces
✅ Tempo: Receiving traces (1037+ spans)
✅ Prometheus: Scraping Tempo metrics successfully  
✅ Grafana: Can query Prometheus
✅ Data flow: Complete and working
```

**Metrics Confirmed:**
- **1037 spans received** by Tempo
- **~3.6 spans/second** current rate
- **20 live traces** in memory

## 🎯 How to View the Dashboard

### Step 1: Open Grafana

http://localhost/monitoring/grafana/

**Login:** admin / admin (default)

### Step 2: Navigate to Tempo Dashboard

1. Click **Dashboards** in the left sidebar (four squares icon)
2. Click **Browse**
3. Find and click **"Tempo Overview"**

OR use direct link:
http://localhost/monitoring/grafana/d/tempo-overview/tempo-overview

### Step 3: Fix Time Range (IMPORTANT!)

The dashboard might be showing old time ranges. Fix this:

1. **Top right corner**: Look for the time range selector
2. **Click it** (probably says "Last 24 hours" or similar)
3. **Change to**: **"Last 5 minutes"** or **"Last 15 minutes"**
4. **Click "Apply"**

### Step 4: Refresh the Dashboard

1. **Click the refresh icon** (circular arrow) in top right
2. **Or set auto-refresh**: Click dropdown next to refresh → Select "10s"

### Step 5: Wait and Verify

Wait 10-15 seconds for data to load. You should see:

- **Tempo Service Status**: Green (value: 1)
- **Spans Received Rate by Protocol**: Graph showing ~3-4 spans/sec
- **Live Traces**: ~20
- **Ingestion Rate**: Bytes per second

## 🔧 If Dashboard Still Shows "No Data"

### Solution 1: Force Refresh

1. Press **Ctrl+Shift+R** (or Cmd+Shift+R on Mac) to hard refresh browser
2. Clear browser cache
3. Try in incognito/private window

### Solution 2: Check Time Range

The most common issue! Make sure:
- Time range is set to **recent** time (Last 5m, Last 15m, Last 1h)
- NOT set to a specific date in the past
- The "To" time should be "now"

### Solution 3: Test Prometheus Directly

1. Open: http://localhost/monitoring/prometheus/
2. In query box, type: `tempo_distributor_spans_received_total`
3. Click **Execute**
4. Should show value: ~1000+

If this works, Prometheus has data. The issue is dashboard configuration.

### Solution 4: Check Grafana Datasource

1. Grafana → **Configuration** (gear icon) → **Data sources**
2. Click **Prometheus**
3. Scroll down, click **"Save & test"**
4. Should show: "Data source is working"

### Solution 5: Rebuild Dashboard

If the dashboard is corrupted, import a fresh one:

1. Grafana → **Dashboards** → **Browse**
2. Find "Tempo Overview"
3. Click the three dots (...) → **Delete**
4. The dashboard will be recreated on next Grafana restart

OR manually:
1. **Create** → **Import**
2. Upload: `/Users/nicolaslallier/Dev Nick/AI_Infra/docker/grafana/dashboards/tempo-overview.json`

## 📊 Alternative: Use Explore View

If dashboard doesn't work, use Explore:

### Method 1: Query Prometheus Metrics

1. Grafana → **Explore** (compass icon)
2. **Select datasource**: Prometheus
3. **Query**: `rate(tempo_distributor_spans_received_total[5m])`
4. **Run query**
5. Should see graph with ~3-4 spans/sec

### Method 2: Search Traces Directly

1. Grafana → **Explore** (compass icon)
2. **Select datasource**: Tempo (not Prometheus!)
3. **Tab**: Search
4. **Service Name**: test-service
5. **Click**: Run query
6. Should see list of traces

Click any trace to see:
- Full trace timeline
- All spans
- Span attributes
- Duration details

## 🧪 Verify Data is Actually There

Run these commands to confirm:

### Check Trace Generator is Running
```bash
docker ps --filter name=tempo-trace-generator
# Should show: ai_infra_tempo_trace_generator (Up)
```

### Check Tempo Received Spans
```bash
docker exec ai_infra_prometheus sh -c \
  "wget -qO- 'http://localhost:9090/api/v1/query?query=tempo_distributor_spans_received_total' 2>/dev/null"
# Should show: value > 1000
```

### Check Spans Rate
```bash
docker exec ai_infra_prometheus sh -c \
  "wget -qO- 'http://localhost:9090/api/v1/query?query=rate(tempo_distributor_spans_received_total[5m])' 2>/dev/null"
# Should show: value ~3-4 (spans per second)
```

### Search Traces via API
```bash
docker exec ai_infra_grafana sh -c \
  "curl -s 'http://tempo:3200/api/search?tags=service.name=test-service&limit=5'"
# Should show: JSON with list of traces
```

## 📸 What You Should See

### Panel 1: Tempo Service Status
- **Type**: Stat
- **Value**: 1 (green)
- **Meaning**: Tempo is up and running

### Panel 2: Spans Received Rate by Protocol  
- **Type**: Time series graph
- **Value**: ~3-4 spans/second
- **Legend**: Should show "receiver" types (likely otlp)

### Panel 3: Live Traces
- **Type**: Stat
- **Value**: ~20
- **Meaning**: Active traces being processed

### Panel 4: Ingestion Rate (bytes/s)
- **Type**: Stat  
- **Value**: Several KB/s
- **Meaning**: Data throughput

## 🐛 Common Issues & Fixes

### Issue: "No data" or empty graphs

**Cause**: Time range is wrong  
**Fix**: Set time range to "Last 5 minutes"

---

### Issue: Dashboard loads but shows old data

**Cause**: Prometheus was restarted  
**Fix**: Wait 1-2 minutes for Prometheus to scrape new data

---

### Issue: Some panels show data, others don't

**Cause**: Different panels use different metrics  
**Fix**: Check which panels work:
- If "Service Status" works → Prometheus is scraping
- If "Spans Received" doesn't → Check time range

---

### Issue: Can't access Grafana

**Cause**: nginx or Grafana not running  
**Fix**:
```bash
docker ps --filter name=grafana
docker ps --filter name=nginx
```

---

### Issue: Dashboard shows "Prometheus query timeout"

**Cause**: Prometheus is overloaded or unhealthy  
**Fix**:
```bash
docker logs ai_infra_prometheus --tail 50
docker restart ai_infra_prometheus
```

## 🎯 Quick Verification Checklist

Run through this checklist:

- [ ] Trace generator is running: `docker ps | grep trace-generator`
- [ ] Tempo is running: `docker ps | grep ai_infra_tempo`
- [ ] Prometheus is running: `docker ps | grep prometheus`
- [ ] Grafana is running: `docker ps | grep grafana`
- [ ] Can access Grafana: http://localhost/monitoring/grafana/
- [ ] Time range set to "Last 5 minutes"
- [ ] Dashboard auto-refresh enabled (10s)
- [ ] Waited 30 seconds after opening dashboard
- [ ] Hard refreshed browser (Ctrl+Shift+R)

## 📞 Still Not Working?

### Debug Step 1: Test Prometheus Query in Grafana

1. Grafana → **Explore**
2. Datasource: **Prometheus**
3. Query: `up{job="tempo"}`
4. Should return: 1

If this doesn't work, Prometheus datasource issue.

### Debug Step 2: Test Direct Prometheus Access

http://localhost/monitoring/prometheus/

If you can't access this, nginx or Prometheus issue.

### Debug Step 3: Check All Services

```bash
docker-compose ps
```

All services should show "Up" status.

### Debug Step 4: Restart Grafana

```bash
docker-compose restart grafana
# Wait 30 seconds
```

Then try dashboard again.

### Debug Step 5: Check Grafana Logs

```bash
docker logs ai_infra_grafana --tail 100
```

Look for errors related to:
- Datasource connections
- Dashboard loading
- Query execution

## 💡 Pro Tips

### Tip 1: Use Explore for Debugging
Explore view is more reliable than dashboards for troubleshooting.

### Tip 2: Check Prometheus First
If Prometheus doesn't have data, dashboard won't work.

### Tip 3: Time Range is Critical
90% of "no data" issues are wrong time ranges.

### Tip 4: Watch Auto-Refresh
Enable 10s auto-refresh to see data updating live.

### Tip 5: Use Incognito Mode
Eliminates cache issues completely.

## 📚 Resources

- **TEMPO_WORKING_NOW.md** - Confirmation data is flowing
- **TEMPO_QUICK_START.md** - Basic setup
- **TEMPO_ONE_PAGER.md** - Visual reference
- **TEMPO_TRACING_SETUP.md** - Production guide

## 🎯 Summary

**Your data pipeline is working!**

```
Trace Generator → Tempo (1037+ spans) → Prometheus (scraping) → Grafana (ready)
```

**To see the dashboard:**
1. Open: http://localhost/monitoring/grafana/d/tempo-overview
2. Set time range: "Last 5 minutes"
3. Click refresh icon
4. Wait 15 seconds

**If dashboard doesn't work:**
1. Use Explore → Prometheus → Query: `tempo_distributor_spans_received_total`
2. Use Explore → Tempo → Search → Service: test-service

**The data IS there** - it's just a matter of viewing it correctly!

---

**Last Verified**: 2025-12-06 20:50 UTC  
**Spans in Tempo**: 1037+  
**Current Rate**: ~3.6 spans/second  
**Status**: ✅ ALL SYSTEMS OPERATIONAL

