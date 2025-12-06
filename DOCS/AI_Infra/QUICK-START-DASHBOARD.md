# Quick Start: AI Infrastructure Dashboard

## ✅ Dashboard is Now Working!

Your Grafana dashboard is now properly configured and displaying real-time metrics.

## Access the Dashboard

**URL**: http://localhost/monitoring/grafana/d/ai-infra-overview/ai-infrastructure-system-overview

**Credentials**:
- Username: `admin`
- Password: `admin`

## What You'll See

### 1. Service Health Status (Top Panel)
Shows UP/DOWN status for all 6 infrastructure services:
- Prometheus (metrics)
- Grafana (dashboards)
- Loki (logs)
- Tempo (traces)
- PostgreSQL (database)
- Keycloak (identity - commented out in dev mode)

### 2. PostgreSQL Metrics
- **Database Size**: Real-time size of all 5 databases
  - app_db: ~7.7 MB
  - postgres: ~7.7 MB
  - keycloak: ~13.5 MB
  - template0, template1: ~7.5 MB
- **Active Locks**: Database locking metrics

### 3. Loki Metrics
- **Request Rate**: Log ingestion requests per second
- **Active Streams**: Number of active log streams

### 4. Prometheus Metrics
- **Storage Size**: TSDB storage (~7 MB currently)
- **Symbol Table**: Internal metric storage
- **HTTP Requests**: API request rate by status code

### 5. Grafana Metrics
- **API Response Status**: Dashboard API health metrics

## Current Metrics Status

✅ **All Working**:
```bash
# Service Health
Prometheus: UP
Grafana: UP
Loki: UP
Tempo: UP
PostgreSQL: UP

# Database Metrics
5 PostgreSQL databases tracked
Total size: ~44 MB

# Storage Metrics
Prometheus TSDB: ~7 MB
```

## Refresh Interval

The dashboard auto-refreshes every **10 seconds** to show real-time data.

Time range: **Last 1 hour** (adjustable in top-right corner)

## Troubleshooting

### If Dashboard Shows "No Data"

1. **Wait 15-30 seconds** - First scrape may take time
2. **Check Prometheus targets**:
   ```bash
   # All should show "up"
   docker exec ai_infra_prometheus wget -qO- http://localhost:9090/api/v1/targets
   ```

3. **Verify services are running**:
   ```bash
   docker-compose ps
   ```

4. **Check Grafana logs**:
   ```bash
   docker logs ai_infra_grafana --tail 50
   ```

5. **Restart services if needed**:
   ```bash
   docker-compose restart prometheus grafana
   ```

### If Specific Panel Shows "No Data"

Check if the metric exists in Prometheus:
```bash
# Test a specific query
docker exec ai_infra_prometheus wget -qO- \
  'http://localhost:9090/api/v1/query?query=pg_database_size_bytes'
```

## Available Metrics

### PostgreSQL (from postgres-exporter)
- `pg_database_size_bytes` - Database sizes
- `pg_locks_count` - Active locks
- `pg_settings_*` - Configuration settings
- Plus 100+ other PostgreSQL metrics

### Prometheus
- `prometheus_tsdb_storage_blocks_bytes` - Storage size
- `prometheus_tsdb_symbol_table_size_bytes` - Symbol table
- `prometheus_http_requests_total` - API requests
- `prometheus_build_info` - Version info

### Loki
- `loki_request_duration_seconds_count` - Request count
- `loki_ingester_memory_streams` - Active streams
- `loki_distributor_bytes_received_total` - Bytes ingested

### Grafana
- `grafana_api_response_status_total` - API responses
- `grafana_alerting_active_alerts` - Active alerts
- Plus 200+ other Grafana metrics

### Service Health
- `up` - Service availability (1=UP, 0=DOWN)

## Customize the Dashboard

### Edit Panels
1. Click panel title → Edit
2. Modify query, visualization, or settings
3. Save dashboard

### Add New Panels
1. Click "Add panel" (top-right)
2. Select visualization type
3. Write PromQL query
4. Configure display options

### Example PromQL Queries

```promql
# CPU usage per container (requires cAdvisor)
rate(container_cpu_usage_seconds_total[5m])

# Memory usage per container (requires cAdvisor)
container_memory_usage_bytes

# PostgreSQL connections
pg_stat_database_numbackends

# Loki ingestion rate
rate(loki_distributor_bytes_received_total[5m])

# Prometheus scrape duration
prometheus_target_interval_length_seconds
```

## Next Steps

### Add More Metrics (Optional)

1. **Node Exporter** - System metrics (CPU, memory, disk)
   - See `GRAFANA-DASHBOARD-FIX.md` for setup instructions

2. **cAdvisor** - Container metrics
   - Per-container CPU, memory, network, disk

3. **Keycloak Metrics** - Authentication metrics
   - Requires production mode configuration

### Explore Other Dashboards

Your Grafana instance has 4 other pre-configured dashboards:
- **Keycloak Dashboard** - Authentication monitoring
- **pgAdmin Audit** - Database access audit
- **PostgreSQL Logs** - Database log analysis
- **PostgreSQL Overview** - Detailed database metrics

Access them via the Grafana dashboard search (top-left).

## Architecture Reference

```
User Browser
    ↓
Nginx Reverse Proxy (port 80)
    ↓
Grafana (port 3000) ← Queries → Prometheus (port 9090)
                                      ↓
                                  Scrapes metrics from:
                                  - PostgreSQL Exporter
                                  - Loki
                                  - Tempo
                                  - Grafana itself
```

## Support

For more details, see:
- **GRAFANA-DASHBOARD-FIX.md** - Complete fix documentation
- **QUICK-ACCESS-GUIDE.md** - All service URLs and credentials
- **docker/README.md** - Docker infrastructure overview

---

**Last Updated**: December 6, 2025  
**Status**: ✅ Fully Operational

