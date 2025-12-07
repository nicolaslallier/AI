# Grafana & Keycloak Monitoring Fix

**Date**: December 6, 2025  
**Status**: ✅ Grafana FIXED | ⚠️ Keycloak Disabled (requires rebuild)

## Problem Summary

Grafana dashboard was showing both Grafana and Keycloak as "down" even though both containers were running and healthy. This was a **metrics scraping configuration issue**, not a service availability issue.

## Root Causes

### 1. Grafana Metrics Endpoint ✅ FIXED

**Issue**: Prometheus was trying to scrape `http://grafana:3000/metrics` directly, but Grafana is configured with `serve_from_sub_path = true` and redirects all requests to `/monitoring/grafana/*`.

**Symptoms**:
- Prometheus logs showed: `"Get \"http://localhost/monitoring/grafana/metrics\": dial tcp [::1]:80: connect: connection refused"`
- Grafana health status: `"down"` in Prometheus targets

**Solution**: Updated Prometheus configuration to scrape through nginx with the correct subpath.

**Changed in** `docker/prometheus/prometheus.yml`:
```yaml
# Before:
- job_name: 'grafana'
  static_configs:
    - targets: ['grafana:3000']
      labels:
        service: 'grafana'

# After:
- job_name: 'grafana'
  metrics_path: '/monitoring/grafana/metrics'
  static_configs:
    - targets: ['nginx:80']
      labels:
        service: 'grafana'
```

**Verification**:
```bash
# Check metrics are accessible
curl http://localhost/monitoring/grafana/metrics

# Check Prometheus targets
curl 'http://localhost/monitoring/prometheus/api/v1/targets' | jq '.data.activeTargets[] | select(.labels.job=="grafana")'
```

**Result**: ✅ Grafana now showing as **UP** with `"health": "up"` and no errors.

---

### 2. Keycloak Metrics Endpoint ⚠️ DISABLED

**Issue**: Keycloak 26 in `start-dev` mode doesn't expose metrics endpoints even with `KC_METRICS_ENABLED=true`.

**Symptoms**:
- Prometheus logs showed: `server returned HTTP status 404 Not Found` for `/metrics`
- Tried multiple paths: `/metrics`, `/q/metrics`, `/health/ready` on ports 8080 and 9000
- All returned: `<html><body><h1>Resource not found</h1></body></html>`

**Root Cause**: 
In Keycloak 26 using Quarkus, metrics are a **build-time feature**. When running `start-dev`, Keycloak needs to be explicitly built with the metrics feature enabled. The `KC_METRICS_ENABLED` environment variable only works if metrics were included in the build.

**Temporary Solution**: Commented out Keycloak scraping in Prometheus configuration to prevent false "down" alerts.

**Changed in** `docker/prometheus/prometheus.yml`:
```yaml
# Keycloak Metrics - DISABLED: Keycloak 26 in start-dev mode doesn't expose metrics
# even with KC_METRICS_ENABLED=true unless explicitly built with metrics feature
# To enable: Change command to 'start --optimized' and add build step with metrics
# - job_name: 'keycloak'
#   metrics_path: '/q/metrics'
#   static_configs:
#     - targets: ['keycloak:9000']
#       labels:
#         service: 'keycloak'
#         tier: 'identity_provider'
```

---

## Permanent Solution for Keycloak Metrics

To enable Keycloak metrics properly, you need to rebuild Keycloak with metrics enabled:

### Option 1: Use Production Mode (Recommended)

Update `docker-compose.yml`:

```yaml
keycloak:
  image: quay.io/keycloak/keycloak:latest
  container_name: ai_infra_keycloak
  restart: unless-stopped
  # Build Keycloak with metrics enabled
  command: 
    - "start"
    - "--optimized"
    - "--import-realm"
  environment:
    # ... existing environment variables ...
    KC_METRICS_ENABLED: true
    KC_HEALTH_ENABLED: true
    # Additional build-time options can be set via KC_FEATURES
    # KC_FEATURES: metrics-endpoint
```

Then rebuild:
```bash
docker-compose stop keycloak
docker-compose rm -f keycloak
docker-compose up -d keycloak
```

### Option 2: Custom Dockerfile with Build Step

Create `docker/keycloak/Dockerfile`:

```dockerfile
FROM quay.io/keycloak/keycloak:latest

# Set build options
ENV KC_METRICS_ENABLED=true
ENV KC_HEALTH_ENABLED=true
ENV KC_DB=postgres

# Build Keycloak with features
RUN /opt/keycloak/bin/kc.sh build \
    --health-enabled=true \
    --metrics-enabled=true

# Copy realm import
COPY realm-export.json /opt/keycloak/data/import/

# Run in optimized mode
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start", "--optimized", "--import-realm"]
```

Update `docker-compose.yml`:
```yaml
keycloak:
  build:
    context: ./docker/keycloak
    dockerfile: Dockerfile
  container_name: ai_infra_keycloak
  # ... rest of configuration ...
```

### Option 3: Keep Dev Mode but Accept No Metrics

If you prefer to keep `start-dev` for faster development iterations, you can:
1. Keep Keycloak metrics disabled in Prometheus (current state)
2. Monitor Keycloak health through:
   - Application logs: `docker logs ai_infra_keycloak -f`
   - Health endpoint: `http://localhost/auth/` (should return 302 redirect)
   - Docker health checks: `docker ps | grep keycloak`

---

## Testing & Verification

### 1. Check Prometheus Targets

```bash
# View all targets
curl -s 'http://localhost/monitoring/prometheus/api/v1/targets' | python3 -m json.tool

# Check specific target (Grafana)
curl -s 'http://localhost/monitoring/prometheus/api/v1/targets' | \
  python3 -c "import sys, json; data = json.load(sys.stdin); \
  targets = [t for t in data['data']['activeTargets'] if t['labels']['job'] == 'grafana']; \
  print(json.dumps(targets, indent=2))"
```

### 2. Check Metrics Query

```bash
# Query if Grafana is up (should return 1)
curl -s 'http://localhost/monitoring/prometheus/api/v1/query?query=up{job="grafana"}' | python3 -m json.tool
```

### 3. Grafana Dashboard

1. Navigate to: http://localhost/monitoring/grafana/
2. Login: `admin` / `admin`
3. Go to "AI Infrastructure System Overview" dashboard
4. Check the "Service Health Status" panel
5. **Grafana should show as UP** (green)
6. **Keycloak will not appear** (since scraping is disabled)

---

## Current Status

### ✅ Working Services
- **Prometheus**: Scraping itself ✅
- **Grafana**: Metrics being scraped successfully ✅
- **Loki**: Metrics being scraped ✅
- **Tempo**: Metrics being scraped ✅
- **PostgreSQL**: Via postgres-exporter ✅
- **MinIO**: All 4 nodes with cluster + node metrics ✅

### ⚠️ Disabled Services
- **Keycloak**: Metrics endpoint not available in start-dev mode
  - Container is healthy and operational
  - Authentication working correctly
  - Just not being monitored in Prometheus

---

## Next Steps

### Immediate (Current State - STABLE)
- ✅ Grafana monitoring restored
- ✅ False "down" alerts eliminated
- ⚠️ Keycloak excluded from monitoring (service still works)

### Short-term (Recommended)
1. Implement Option 1 or Option 2 above to enable Keycloak metrics
2. Test in development environment first
3. Update Prometheus configuration to uncomment Keycloak scraping
4. Verify in Grafana dashboard

### Long-term (Production Ready)
1. Use `start --optimized` for production deployments
2. Enable all Quarkus production features
3. Set up proper health checks for all services
4. Configure alerting rules in Prometheus
5. Create dashboards for service-specific metrics

---

## Files Modified

1. **docker/prometheus/prometheus.yml**
   - Fixed Grafana scraping configuration
   - Commented out Keycloak scraping with explanation

## Services Restarted

```bash
docker-compose restart prometheus
```

---

## Architectural Notes

### Why Grafana Uses Subpath

Grafana is configured with `serve_from_sub_path = true` because:
- It's behind nginx reverse proxy
- Accessed via `http://localhost/monitoring/grafana/`
- All Grafana routes must include the `/monitoring/grafana` prefix
- This includes the `/metrics` endpoint

This is **correct architecture** for a multi-service reverse proxy setup.

### Why Keycloak Metrics Don't Work in Dev Mode

Keycloak 26 uses Quarkus 3.27.1, which requires build-time configuration for certain features:
- Metrics endpoint (`/q/metrics`)
- Health endpoints (`/q/health`)
- Other management features

The `start-dev` command:
- ✅ Skips the build step for faster startup
- ✅ Enables auto-reload of configuration
- ✅ Perfect for development and testing
- ❌ Doesn't include metrics unless explicitly built
- ❌ Management interface (port 9000) returns 404 for metrics

This is **by design** in Keycloak to optimize development experience.

---

## Additional Resources

- [Keycloak Metrics Documentation](https://www.keycloak.org/server/configuration-metrics)
- [Quarkus Micrometer Documentation](https://quarkus.io/guides/micrometer)
- [Grafana Metrics Configuration](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/#metrics)
- [Prometheus Configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)

---

## Troubleshooting

### If Grafana shows as "down" again

1. Check nginx is routing correctly:
   ```bash
   curl -I http://localhost/monitoring/grafana/metrics
   ```
   Should return `200 OK` with Prometheus metrics

2. Check Prometheus can reach nginx:
   ```bash
   docker exec ai_infra_prometheus wget -O- http://nginx:80/monitoring/grafana/metrics
   ```

3. Restart Prometheus:
   ```bash
   docker-compose restart prometheus
   ```

### If you want to quickly enable Keycloak monitoring

Uncomment the Keycloak job in `prometheus.yml` and update the target:
```yaml
- job_name: 'keycloak'
  metrics_path: '/q/metrics'
  static_configs:
    - targets: ['keycloak:9000']
```

Then rebuild Keycloak with metrics as described in "Permanent Solution" section above.

---

**End of Document**

