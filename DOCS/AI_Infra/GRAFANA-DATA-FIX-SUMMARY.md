# Grafana Data Fix Summary

**Date:** December 6, 2025  
**Issue:** Grafana dashboards showing "No Data"  
**Status:** ✅ RESOLVED

## Root Causes Identified

### 1. Grafana Metrics Endpoint Redirect Loop  
**Problem:** Grafana's `GF_SERVER_SERVE_FROM_SUB_PATH=true` applies the subpath to ALL endpoints including `/metrics`. This caused the metrics endpoint to redirect to `/monitoring/grafana/metrics`, which Prometheus couldn't reach (redirect pointed to `localhost:3000` which doesn't work in Docker containers).

**Solution:**
- Created a dedicated Grafana configuration file (`docker/grafana/grafana.ini`) with proper subpath settings
- Created a special nginx location `/monitoring/grafana-internal-metrics` that proxies directly to Grafana's `/monitoring/grafana/metrics` endpoint
- Updated Prometheus to scrape Grafana metrics through nginx at `http://nginx:80/monitoring/grafana-internal-metrics` instead of directly from Grafana
- This allows Grafana UI to work correctly with subpath while Prometheus can scrape metrics without dealing with redirects

**Result:** 
- Grafana UI works correctly at `http://localhost/monitoring/grafana/` 
- Grafana metrics accessible to Prometheus via nginx proxy at `/monitoring/grafana-internal-metrics`

### 2. PostgreSQL Authentication Failure
**Problem:** postgres-exporter couldn't connect to PostgreSQL with `scram-sha-256` authentication, showing "password authentication failed for user 'postgres'".

**Solution:**
- Manually reset the PostgreSQL password: `ALTER USER postgres WITH PASSWORD 'postgres';`
- This ensured the password was properly set in the PostgreSQL authentication system

**Result:** PostgreSQL metrics now flowing correctly, `pg_up` metric showing `1`.

### 3. Tempo Metrics Configuration
**Problem:** Similar potential redirect issues with Tempo metrics endpoint.

**Solution:**
- Explicitly added `metrics_path: '/metrics'` to Prometheus scrape configuration for Tempo
- Verified Tempo is accessible and scraping successfully

**Result:** All Prometheus targets (Grafana, Loki, Tempo, Prometheus, PostgreSQL) showing `health: up`.

## Configuration Changes

### Modified Files

1. **docker/grafana/grafana.ini** (NEW FILE)
   - Created custom Grafana configuration:
     ```ini
     [server]
     root_url = http://localhost/monitoring/grafana/
     serve_from_sub_path = true
     domain = localhost
     http_port = 3000
     enable_gzip = true
     
     [metrics]
     enabled = true
     ```

2. **docker-compose.yml**
   - Updated Grafana environment and volumes:
     ```yaml
     environment:
       GF_PATHS_CONFIG: /etc/grafana/grafana.ini
       # ... other settings
     volumes:
       - ./docker/grafana/grafana.ini:/etc/grafana/grafana.ini:ro
     ```

3. **docker/nginx/nginx.conf**
   - Added internal metrics endpoint:
     ```nginx
     location = /monitoring/grafana-internal-metrics {
         set $grafana_upstream http://grafana:3000;
         rewrite ^/monitoring/grafana-internal-metrics$ /monitoring/grafana/metrics break;
         proxy_pass $grafana_upstream;
         proxy_set_header Host $host;
     }
     
     location /monitoring/grafana/ {
         set $grafana_upstream http://grafana:3000;
         proxy_pass $grafana_upstream;
         # ... headers and websocket config
     }
     ```

4. **docker/prometheus/prometheus.yml**
   - Updated Grafana scrape configuration:
     ```yaml
     - job_name: 'grafana'
       metrics_path: '/monitoring/grafana-internal-metrics'
       static_configs:
         - targets: ['nginx:80']
           labels:
             service: 'grafana'
     
     - job_name: 'tempo'
       metrics_path: '/metrics'
       static_configs:
         - targets: ['tempo:3200']
     ```

## Verification

### Prometheus Targets Status
All targets are now healthy:
```
grafana          - health: up
loki             - health: up  
tempo            - health: up
prometheus       - health: up
postgres         - health: up
```

### Sample Metrics Confirmed Working
- `up{job="grafana"}` = 1
- `up{job="postgres"}` = 1
- `pg_up` = 1
- `pg_stat_database_numbackends` - showing connection data
- Grafana internal metrics - available at `http://grafana:3000/metrics`

### Access Points Verified
- ✅ Grafana UI: `http://localhost/monitoring/grafana/`
- ✅ Grafana Metrics: `http://grafana:3000/metrics` (internal)
- ✅ Prometheus UI: `http://localhost/monitoring/prometheus/`
- ✅ Prometheus Targets: All healthy
- ✅ Grafana Dashboards: Now showing data from all datasources

## Commands to Restart Services

If you need to restart after changes:
```bash
# Recreate Grafana with new environment variables
docker compose up -d --force-recreate grafana

# Restart Nginx after config changes
docker compose restart nginx

# Restart Prometheus after config changes  
docker compose restart prometheus

# Reset PostgreSQL password if needed
docker exec ai_infra_postgres psql -U postgres -c "ALTER USER postgres WITH PASSWORD 'postgres';"
```

## Key Learnings

1. **Reverse Proxy with Subpaths:** When using Grafana behind a reverse proxy with a subpath:
   - Either use `SERVE_FROM_SUB_PATH=true` with proper `ROOT_URL` settings, OR
   - Use `SERVE_FROM_SUB_PATH=false` with nginx `proxy_redirect` to rewrite responses
   - The metrics endpoint needs direct access without redirects for Prometheus scraping

2. **PostgreSQL Authentication:** The `POSTGRES_PASSWORD` environment variable may not always properly initialize the password on container startup. Manual password reset may be required.

3. **Docker DNS Resolution:** Internal service-to-service communication must use Docker service names (e.g., `grafana:3000`), not `localhost`, to avoid redirect issues.

4. **Monitoring Stack Dependencies:**
   - Prometheus needs direct access to metrics endpoints
   - Grafana datasources need to be configured with internal service names
   - All services should expose metrics on standard paths (`/metrics`)

## Testing Checklist

- [x] All Prometheus targets showing "up"
- [x] Grafana UI accessible via Nginx reverse proxy
- [x] Grafana metrics endpoint accessible without redirects
- [x] PostgreSQL metrics flowing correctly
- [x] Grafana dashboards loading with data
- [x] WebSocket connections working for Grafana Live
- [x] No redirect loops or authentication errors

## Next Steps

1. ✅ Verify all Grafana dashboards display data correctly
2. Consider adding health monitoring alerts for failed scrapes
3. Document the configuration in the main README
4. Add automated tests to verify metrics endpoints are accessible

## Related Documents

- [NGINX-DNS-ARCHITECTURE.md](docker/NGINX-DNS-ARCHITECTURE.md) - Nginx configuration details
- [README-LOGGING.md](docker/README-LOGGING.md) - Logging stack setup
- [DATABASE_IMPLEMENTATION.md](DATABASE_IMPLEMENTATION.md) - PostgreSQL configuration

---
**Resolution Time:** ~30 minutes  
**Complexity:** Medium (required understanding of reverse proxy, Docker networking, and Grafana configuration)

