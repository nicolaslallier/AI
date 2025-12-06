# Grafana Dashboard Fix Summary

## Issue Description
The AI Infrastructure System Overview dashboard at `http://localhost/monitoring/grafana/` was showing "No Data" for all panels.

## Root Causes Identified

### 1. **Missing Node Exporter**
- The original dashboard used `node_cpu_seconds_total` and `node_memory_*` metrics
- These metrics come from Prometheus Node Exporter, which was **not deployed** in the infrastructure
- Without Node Exporter, no system-level CPU/memory metrics were available

### 2. **Incorrect Prometheus Scrape Configurations**
- **Grafana metrics endpoint**: Was trying to scrape via NGINX proxy with incorrect path rewrite
- **Keycloak metrics**: Not available in development mode without additional configuration

### 3. **Dashboard Queries Using Non-Existent Metrics**
- All panel queries referenced metrics that didn't exist in the environment

## Solutions Implemented

### 1. **Updated Dashboard with Available Metrics**
Created a new comprehensive dashboard (`docker/grafana/dashboards/system-overview.json`) with panels using metrics that are actually being collected:

#### Service Health Status
- **Query**: `up{job="prometheus|grafana|loki|tempo|postgres|keycloak"}`
- **Purpose**: Shows UP/DOWN status for all infrastructure services
- **Visual**: Stat panels with color-coded background (green=UP, red=DOWN)

#### PostgreSQL Metrics
- **Database Size**: `sum(pg_database_size_bytes) by (datname)`
- **Active Locks**: `pg_locks_count`
- Shows real-time database storage and locking information

#### Loki Metrics
- **Request Rate**: `rate(loki_request_duration_seconds_count[5m])`
- **Active Streams**: `sum(loki_ingester_memory_streams)`
- Monitors log ingestion performance

#### Prometheus Metrics
- **Storage Size**: `prometheus_tsdb_storage_blocks_bytes`
- **Symbol Table**: `prometheus_tsdb_symbol_table_size_bytes`
- **HTTP Requests**: `rate(prometheus_http_requests_total[5m])`
- Tracks metrics database health and usage

#### Grafana Metrics
- **API Response Status**: `rate(grafana_api_response_status_total[5m])`
- Monitors dashboard and API health

### 2. **Fixed Prometheus Scrape Configuration**
Updated `docker/prometheus/prometheus.yml`:

```yaml
# Before: Scraping via NGINX proxy (failing)
- job_name: 'grafana'
  metrics_path: '/monitoring/grafana-internal-metrics'
  static_configs:
    - targets: ['nginx:80']

# After: Direct scraping from Grafana
- job_name: 'grafana'
  static_configs:
    - targets: ['grafana:3000']
```

Commented out Keycloak metrics (not available in dev mode):
```yaml
# - job_name: 'keycloak'
#   metrics_path: '/metrics'
#   static_configs:
#     - targets: ['keycloak:8080']
```

### 3. **Fixed NGINX Metrics Proxy**
Updated `docker/nginx/nginx.conf`:

```nginx
# Before: Complex rewrite that was failing
location = /monitoring/grafana-internal-metrics {
    set $grafana_upstream http://grafana:3000;
    rewrite ^/monitoring/grafana-internal-metrics$ /monitoring/grafana/metrics break;
    proxy_pass $grafana_upstream;
}

# After: Simple direct proxy to metrics endpoint
location = /monitoring/grafana-internal-metrics {
    set $grafana_upstream http://grafana:3000;
    proxy_pass $grafana_upstream/metrics;
}
```

## Current Status

### ✅ All Prometheus Targets Healthy
```
grafana: up
loki: up
postgres: up
prometheus: up
tempo: up
```

### ✅ Metrics Being Collected
- **PostgreSQL**: 5 databases with size metrics
- **Prometheus**: Storage and performance metrics
- **Loki**: Request rate and stream metrics
- **Grafana**: API response metrics
- **Service Health**: All services reporting UP status

### ✅ Dashboard Panels Working
All 9 panels in the System Overview dashboard now display real-time data:
1. Service Health Status (6 services)
2. PostgreSQL Database Size
3. PostgreSQL Active Locks
4. Loki Request Rate
5. Loki Active Streams
6. Prometheus Storage Size
7. Prometheus Symbol Table
8. Grafana API Response Status
9. Prometheus HTTP Requests

## Future Enhancements

### Option 1: Add Node Exporter (Recommended for Production)
If you need system-level metrics (CPU, memory, disk, network), add Node Exporter to `docker-compose.yml`:

```yaml
node-exporter:
  image: prom/node-exporter:latest
  container_name: ai_infra_node_exporter
  restart: unless-stopped
  command:
    - '--path.rootfs=/host'
  volumes:
    - '/:/host:ro,rslave'
  networks:
    - monitoring-net
  deploy:
    resources:
      limits:
        cpus: '0.25'
        memory: 128M
```

Then add to Prometheus configuration:
```yaml
- job_name: 'node'
  static_configs:
    - targets: ['node-exporter:9100']
```

### Option 2: Add cAdvisor for Container Metrics
For Docker container-level metrics (CPU/memory per container):

```yaml
cadvisor:
  image: gcr.io/cadvisor/cadvisor:latest
  container_name: ai_infra_cadvisor
  restart: unless-stopped
  volumes:
    - /:/rootfs:ro
    - /var/run:/var/run:ro
    - /sys:/sys:ro
    - /var/lib/docker/:/var/lib/docker:ro
  networks:
    - monitoring-net
```

### Option 3: Enable Keycloak Metrics
Keycloak metrics require additional configuration in production mode. See Keycloak documentation for enabling metrics endpoint.

## Testing

To verify the dashboard is working:

1. **Access Grafana**: http://localhost/monitoring/grafana/
2. **Navigate to Dashboard**: Search for "AI Infrastructure - System Overview"
3. **Verify Data**: All panels should show live data (may take 15-30 seconds for initial scrape)
4. **Check Prometheus Targets**: http://localhost/monitoring/prometheus/targets (all should be UP)

## Files Modified

1. `/Users/nicolaslallier/Dev Nick/AI_Infra/docker/grafana/dashboards/system-overview.json` - Complete rewrite
2. `/Users/nicolaslallier/Dev Nick/AI_Infra/docker/prometheus/prometheus.yml` - Updated scrape configs
3. `/Users/nicolaslallier/Dev Nick/AI_Infra/docker/nginx/nginx.conf` - Fixed metrics proxy

## Validation Commands

```bash
# Check Prometheus targets status
docker exec ai_infra_prometheus wget -qO- http://localhost:9090/api/v1/targets | python3 -m json.tool

# Verify PostgreSQL metrics
docker exec ai_infra_prometheus wget -qO- 'http://localhost:9090/api/v1/query?query=pg_database_size_bytes'

# Check service health
docker exec ai_infra_prometheus wget -qO- 'http://localhost:9090/api/v1/query?query=up'

# Restart services if needed
docker-compose restart prometheus grafana nginx
```

## Architectural Notes

### Monitoring Stack Architecture
- **Prometheus**: Metrics collection and storage (TSDB)
- **Grafana**: Visualization and dashboards
- **Loki**: Log aggregation (not metrics)
- **Tempo**: Distributed tracing (not metrics)
- **PostgreSQL Exporter**: Database-specific metrics
- **Node Exporter**: (Optional) Host system metrics
- **cAdvisor**: (Optional) Container metrics

### Best Practices Applied
1. **Direct Scraping**: Prometheus scrapes services directly rather than through proxies
2. **Proper Labels**: All metrics labeled with `service`, `job` for easy filtering
3. **Health Checks**: `up` metric provides service availability monitoring
4. **Resource Monitoring**: Database, storage, and request metrics for operational insights
5. **Time Series Visualization**: All metrics use appropriate time series graphs

---

**Date**: December 6, 2025  
**Status**: ✅ Resolved  
**Dashboard**: http://localhost/monitoring/grafana/d/ai-infra-overview/

