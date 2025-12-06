# Prometheus Alert Rules Fix Summary

**Date**: December 6, 2025  
**Issue**: Prometheus failing to load alert rules with parse errors  
**Status**: ✅ **RESOLVED**

---

## Problem Description

Prometheus was repeatedly failing to start with the following error:

```
parse error: unexpected character: '|'
```

The error occurred in `database-logs-alerts.yml` at line 79, rule `PostgreSQLSlowQueryPercentileHigh`.

### Root Cause

The `database-logs-alerts.yml` file contained **LogQL (Loki Query Language)** expressions instead of **PromQL (Prometheus Query Language)** expressions. All alerts in that file were attempting to query Loki log streams directly, which Prometheus cannot do.

### Example of Problematic Query

```yaml
# This is LogQL - DOES NOT WORK in Prometheus
expr: |
  quantile_over_time(0.95, {source="postgres", log_type="slow_query"} | json | unwrap duration [5m]) > 5000
```

The syntax `{source="postgres"}` with the pipe operator `| json | unwrap` is specific to Loki's log querying system.

---

## Solution Implemented

### 1. **Disabled the Problematic File**

The file remains in the alerts directory with a `.disabled` extension:

```
docker/prometheus/alerts/database-logs-alerts.yml.disabled
```

### 2. **Restarted Prometheus**

After disabling the file, Prometheus was restarted and now starts cleanly with no errors:

```bash
docker restart ai_infra_prometheus
```

**Result**: Prometheus is now **healthy** and loading only valid PromQL-based alerts from `basic-alerts.yml`.

### 3. **Created Documentation**

A comprehensive guide has been created at:

```
docker/prometheus/alerts/README-LOG-BASED-ALERTS.md
```

This document explains:
- The difference between Prometheus (metrics) and Loki (logs)
- Why the alerts failed
- Three options for implementing log-based alerts properly
- How to enable Loki Ruler for log-based alerting
- Best practices for hybrid monitoring

---

## Current State

### ✅ Working
- Prometheus is running and healthy
- `basic-alerts.yml` is loaded successfully
- No parse errors in logs
- Metrics scraping is working

### ⚠️ Pending
- Log-based alerts are currently **disabled**
- The 23 alerts defined in `database-logs-alerts.yml.disabled` are not active

### 📋 Disabled Alerts

All alerts in the disabled file fall into these categories:

1. **PostgreSQL Connection Alerts** (2 alerts)
   - Connection failure rate monitoring
   - Authentication failure spike detection

2. **PostgreSQL Performance Alerts** (2 alerts)
   - Slow query threshold detection
   - Query duration percentile monitoring

3. **PostgreSQL Error Alerts** (3 alerts)
   - High error rate detection
   - Critical FATAL/PANIC errors
   - Disk space warnings

4. **PostgreSQL Availability Alerts** (1 alert)
   - Database down detection

5. **PostgreSQL Security Alerts** (2 alerts)
   - Suspicious authentication activity
   - Unauthorized access attempts

6. **pgAdmin Security Alerts** (2 alerts)
   - Authentication failure spikes
   - Suspicious admin actions (DROP, DELETE, TRUNCATE)

7. **pgAdmin Operational Alerts** (2 alerts)
   - High error rate
   - Service availability

8. **Compliance Alerts** (2 alerts)
   - Audit log gap detection
   - High-privilege operations monitoring

---

## Recommended Next Steps

### Option 1: Enable Loki Ruler (Recommended)

This allows you to keep the log-based alerts and have them evaluated by Loki:

```bash
# 1. Create Loki rules directory
mkdir -p docker/loki/rules

# 2. Move the alerts file
mv docker/prometheus/alerts/database-logs-alerts.yml.disabled \
   docker/loki/rules/database-logs-alerts.yml

# 3. Configure Loki ruler in docker/loki/loki.yml
# 4. Update docker-compose.yml to mount the rules directory
# 5. Restart Loki
```

See `README-LOG-BASED-ALERTS.md` for detailed instructions.

### Option 2: Use Metrics-Based Alerts Only

Convert log-based alerts to use Prometheus metrics from exporters like `postgres_exporter`:

```yaml
# Example: Use postgres_exporter metrics instead of logs
- alert: PostgreSQLHighRollbackRate
  expr: |
    rate(pg_stat_database_xact_rollback[5m]) > 10
```

### Option 3: Hybrid Approach (Best for Production)

- **Prometheus**: Metrics-based alerts (CPU, memory, latency, throughput)
- **Loki Ruler**: Log-based alerts (auth failures, error patterns, audit events)
- **Alertmanager**: Centralized routing for both

---

## Architecture Impact

### Before Fix
```
Prometheus → [Loading LogQL alerts] → ❌ Parse Error → Crash Loop
```

### After Fix
```
Prometheus → [PromQL alerts only] → ✅ Running Healthy
Loki       → [LogQL alerts disabled] → ⚠️ No log-based alerting
```

### Future State (Recommended)
```
Prometheus → [PromQL alerts] ──┐
                               ├──→ Alertmanager → Notifications
Loki Ruler → [LogQL alerts] ───┘
```

---

## Key Learnings

### 1. **Metrics vs. Logs**

| Aspect | Prometheus (Metrics) | Loki (Logs) |
|--------|---------------------|-------------|
| **Data Type** | Time-series numbers | Text/JSON logs |
| **Query Language** | PromQL | LogQL |
| **Alert On** | CPU, memory, rates, percentiles | Error messages, patterns, events |
| **Performance** | Highly optimized for aggregation | Optimized for search |
| **Storage** | Compressed time-series | Compressed log streams |

### 2. **When to Use Each**

**Use Prometheus Alerts When**:
- Monitoring system resources (CPU, memory, disk)
- Tracking application metrics (request rates, latency)
- Measuring business metrics (orders/sec, active users)
- Alerting on numerical thresholds

**Use Loki Alerts When**:
- Detecting specific log patterns
- Monitoring authentication failures
- Tracking error messages
- Audit trail monitoring
- Compliance logging

### 3. **Best Practices**

✅ **DO**:
- Keep metrics alerts in Prometheus
- Keep log alerts in Loki Ruler
- Use Alertmanager for centralized routing
- Document your alerting strategy
- Test alerts before deploying to production

❌ **DON'T**:
- Mix LogQL in Prometheus rule files
- Try to parse logs in Prometheus
- Use Loki for high-cardinality metrics
- Create alerts without proper thresholds
- Ignore alert fatigue

---

## Files Modified

### Created
- `docker/prometheus/alerts/README-LOG-BASED-ALERTS.md` - Comprehensive guide
- `PROMETHEUS-FIX-SUMMARY.md` - This summary document

### Renamed
- `database-logs-alerts.yml` → `database-logs-alerts.yml.disabled`

### Unchanged
- `docker/prometheus/prometheus.yml` - Still loads `*.yml` files
- `docker/prometheus/alerts/basic-alerts.yml` - Still active
- All service configurations remain the same

---

## Verification

### Check Prometheus Status
```bash
docker ps --filter name=prometheus --format "table {{.Names}}\t{{.Status}}"
# Expected: ai_infra_prometheus   Up X seconds (healthy)
```

### Check Loaded Rules
```bash
docker logs ai_infra_prometheus 2>&1 | grep -i error
# Expected: No ERROR lines related to alert parsing
```

### Access Prometheus UI
```
http://localhost:9090/alerts
http://localhost:9090/rules
```

---

## Support

For questions or issues:

1. **Review**: `docker/prometheus/alerts/README-LOG-BASED-ALERTS.md`
2. **Check logs**: `docker logs ai_infra_prometheus`
3. **Prometheus docs**: https://prometheus.io/docs/
4. **Loki docs**: https://grafana.com/docs/loki/

---

## Conclusion

The immediate issue is **resolved** - Prometheus is now stable and running without errors. However, to restore the comprehensive log-based alerting capabilities, you should implement **Option 1 (Loki Ruler)** as described in the README.

The alerts in the disabled file are valuable for security, compliance, and operational monitoring. They should be re-enabled through the proper channel (Loki Ruler) rather than deleted.

**Status**: 
- ✅ Prometheus: Fixed and healthy
- ⚠️ Log alerts: Disabled, awaiting Loki Ruler implementation
- 📚 Documentation: Complete

