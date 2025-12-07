# Loki Dashboard "No Data" Issue - Root Cause & Solution

**Issue**: Grafana Loki dashboard shows "No data" even though Loki and Promtail are running.

**Date**: December 7, 2025

---

## Root Cause Analysis

### What We Found

1. **Loki is running correctly** and receiving queries from Grafana
2. **Promtail is running but not transferring logs** after restart
3. **All queries show zero data**: `total_lines=0`, `total_entries=0`, `ingester_chunk_refs=0`

### Why This Happened

**Promtail Position Tracking**: Promtail tracks its reading position in Docker container logs using a positions file (`/tmp/positions.yaml`). When Promtail restarts:

- It discovers all Docker containers successfully
- It restores its last reading position for each container
- **It only reads NEW logs from that position forward**
- If containers haven't produced new logs since the restart, the dashboard shows "No data"

### Evidence from Logs

```bash
# Promtail successfully transferred logs BEFORE restart (Dec 6th)
level=info ts=2025-12-06T22:21:33Z msg="finished transferring logs" written=363604
level=info ts=2025-12-06T22:25:48Z msg="finished transferring logs" written=290737

# After restart (Dec 7th), Promtail discovered targets but hasn't transferred logs yet
level=info ts=2025-12-07T09:56:22Z msg="added Docker target" containerID=f516f0c9...
level=info ts=2025-12-07T09:56:22Z msg="added Docker target" containerID=c3098066...
# No "finished transferring logs" messages = no new logs generated
```

---

## Solutions

### Option 1: Wait for New Log Activity (Recommended)

**Best for production**: Let the system naturally generate new logs

```bash
# The system WILL start collecting logs when:
# - Users authenticate via Keycloak
# - Database queries are executed  
# - API requests are made
# - Any container logs new activity

# Loki dashboard will populate automatically within minutes as activity occurs
```

**Why this is recommended**:
- No disruption to running services
- Preserves log history and positions
- Natural, production-safe approach

### Option 2: Force Log Generation

**For immediate testing**: Trigger log activity manually

```bash
# Generate Postgres logs
docker exec ai_infra_postgres psql -U postgres -c "SELECT version();"

# Generate Keycloak logs (visit in browser)
open http://localhost/auth/admin

# Generate pgAdmin logs
open http://localhost/pgadmin

# Check MinIO logs
docker logs ai_infra_minio1 --tail 10

# Wait 30 seconds, then check Promtail
docker logs ai_infra_promtail --since 1m | grep "finished transferring"
```

### Option 3: Restart Promtail with Fresh Position File

**For development/testing**: Reset Promtail's position tracking

```bash
# Stop Promtail
docker stop ai_infra_promtail

# Clear position file (forces reading from container start)
docker exec ai_infra_promtail rm -f /tmp/positions.yaml 2>/dev/null || true

# Restart Promtail
docker start ai_infra_promtail

# Monitor log collection
docker logs -f ai_infra_promtail
```

**⚠️ Warning**: This will re-ingest recent logs, potentially creating duplicates in Loki

### Option 4: Restart All Services

**Nuclear option**: Full stack restart to ensure fresh logs

```bash
# In AI_Infra directory
cd "/Users/nicolaslallier/Dev Nick/AI_Infra"

# Restart the monitoring stack
docker-compose restart loki promtail

# Or restart specific services to generate logs
docker-compose restart postgres keycloak pgadmin
```

---

## Verification Steps

### 1. Check Promtail is Collecting Logs

```bash
# Watch for "finished transferring logs" messages
docker logs ai_infra_promtail --since 5m | grep "finished transferring"

# Expected output:
# level=info ... msg="finished transferring logs" written=12345 container=...
```

### 2. Query Loki Directly

```bash
# Check what labels Loki has indexed
curl -s 'http://localhost:3100/loki/api/v1/labels' | jq

# Check available jobs
curl -s 'http://localhost:3100/loki/api/v1/label/job/values' | jq

# Query for any logs from last hour
curl -s -G 'http://localhost:3100/loki/api/v1/query' \
  --data-urlencode 'query={job=~".+"}' \
  --data-urlencode 'limit=10' | jq
```

### 3. Check Grafana Dashboard

1. Open: http://localhost/monitoring/grafana/d/loki-overview
2. Verify:
   - "Loki Service Status" panel shows **green (1)** = Loki is up
   - "Log Lines Ingestion Rate" shows **activity** = logs flowing
   - "Active Streams" shows **non-zero** = log streams exist
   - "Recent Errors" panel shows **log entries** = data available

### 4. Explore Logs in Grafana

1. Go to: http://localhost/monitoring/grafana/explore
2. Select: **Loki** data source (top dropdown)
3. Try these queries:
   ```logql
   # All logs from postgres
   {source="postgres"}
   
   # All logs from keycloak  
   {source="keycloak"}
   
   # All logs from any source
   {job=~".+"}
   
   # Error logs only
   {level="ERROR"}
   ```

---

## Technical Details

### Promtail Configuration

Located: `docker/promtail/promtail.yml`

**Scrape Jobs Configured**:
- `postgres` - Filters: `com.docker.compose.service=postgres`
- `pgadmin` - Filters: `com.docker.compose.service=pgadmin`
- `keycloak` - Filters: `com.docker.compose.service=keycloak`
- `minio` - Filters: `logging.source=minio`
- `system` - Local `/var/log/*log` files

### How Docker Log Discovery Works

```yaml
# Promtail discovers containers via Docker daemon
docker_sd_configs:
  - host: unix:///var/run/docker.sock
    filters:
      - name: label
        values: ["com.docker.compose.service=postgres"]

# Then streams logs from discovered containers
# Position tracking ensures no duplicate logs
```

### Loki Query Performance

Loki only indexes **labels**, not log content. When querying:

✅ **Fast**: `{source="postgres"}` - uses label index  
✅ **Fast**: `{job="postgres", level="ERROR"}` - uses label index  
❌ **Slow**: `{source="postgres"} |= "SELECT"` - scans log content  

---

## Monitoring Promtail Health

### Health Check Endpoint

```bash
# Promtail health check (inside container)
docker exec ai_infra_promtail wget --spider -q http://localhost:9080/ready
echo $?  # 0 = healthy, non-zero = unhealthy
```

### Metrics Endpoint

```bash
# Promtail metrics (Prometheus format)
curl -s http://localhost:9080/metrics | grep promtail

# Key metrics to watch:
# - promtail_targets_active_total - Number of active targets
# - promtail_sent_bytes_total - Total bytes sent to Loki
# - promtail_dropped_entries_total - Dropped log entries (should be 0)
```

### Docker Container Status

```bash
# Check Promtail status
docker ps --filter "name=promtail" --format "table {{.Names}}\t{{.Status}}"

# Expected: Up X minutes (healthy)
# Unhealthy means health check is failing
```

---

## Common Issues & Troubleshooting

### Issue: Promtail shows "unhealthy" status

**Symptoms**: `docker ps` shows `(unhealthy)` status

**Cause**: Health check failing (can't reach Loki or internal error)

**Solution**:
```bash
# Check Promtail logs for errors
docker logs ai_infra_promtail --tail 50 | grep -i error

# Verify Loki is reachable from Promtail network
docker exec ai_infra_promtail nslookup loki

# Restart Promtail
docker restart ai_infra_promtail
```

### Issue: "unexpected EOF" errors

**Symptoms**: Promtail logs show `msg="could not transfer logs" err="unexpected EOF"`

**Cause**: Docker daemon connection issues or containers restarting

**Solution**:
```bash
# Check Docker socket permissions
docker exec ai_infra_promtail ls -la /var/run/docker.sock

# Restart Promtail to re-establish connections
docker restart ai_infra_promtail
```

### Issue: "context deadline exceeded" errors

**Symptoms**: `error="Post \"http://loki:3100/loki/api/v1/push\": context deadline exceeded"`

**Cause**: Loki is overloaded or not responding

**Solution**:
```bash
# Check Loki status
docker logs ai_infra_loki --tail 20

# Check Loki health
curl http://localhost:3100/ready

# Restart Loki if needed
docker restart ai_infra_loki

# Wait 10 seconds, then restart Promtail
docker restart ai_infra_promtail
```

### Issue: No logs from specific service

**Symptoms**: Postgres logs appear but Keycloak logs don't

**Solution**:
```bash
# Verify container has the required label
docker inspect ai_infra_keycloak --format '{{index .Config.Labels "com.docker.compose.service"}}'
# Should output: keycloak

# Check if container is logging
docker logs ai_infra_keycloak --tail 5

# Verify Promtail discovered it
docker logs ai_infra_promtail 2>&1 | grep "added Docker target" | grep -v promtail

# If not discovered, check filters in promtail.yml
```

---

## Prevention & Best Practices

### 1. Monitor Promtail Health

Add alerts in Prometheus/Grafana for:
- `up{job="promtail"} == 0` - Promtail is down
- `rate(promtail_sent_bytes_total[5m]) == 0` - No logs being sent
- `promtail_targets_active_total == 0` - No targets discovered

### 2. Regular Log Activity

Ensure services generate regular logs:
- Health check endpoints
- Scheduled jobs/cron
- Periodic metrics collection
- Keepalive connections

### 3. Graceful Restarts

When restarting services:
```bash
# Restart one service at a time
docker-compose restart postgres
sleep 30  # Allow time for logs to be collected

docker-compose restart keycloak  
sleep 30

# Monitor Promtail during restarts
docker logs -f ai_infra_promtail
```

### 4. Position File Persistence

Current setup stores positions in container's `/tmp/positions.yaml` (ephemeral).

**For production**, consider:
```yaml
# In docker-compose.yml
promtail:
  volumes:
    - promtail_positions:/etc/promtail/positions

volumes:
  promtail_positions:
    driver: local
```

Then update `promtail.yml`:
```yaml
positions:
  filename: /etc/promtail/positions/positions.yaml
```

---

## Quick Reference

### Start Fresh (Development)

```bash
# Stop everything
docker-compose down

# Remove Loki data (clears all logs)
docker volume rm ai_infra_loki_data

# Start everything
docker-compose up -d

# Generate test logs
docker exec ai_infra_postgres psql -U postgres -c "SELECT 1;"
curl -I http://localhost/auth

# Wait 30 seconds
sleep 30

# Check Loki has data
curl -s 'http://localhost:3100/loki/api/v1/labels' | jq
```

### Production Restart (Minimal Disruption)

```bash
# Restart only log collection components
docker-compose restart promtail loki

# Monitor for errors
docker logs -f ai_infra_promtail &
docker logs -f ai_infra_loki &

# Wait for services to stabilize (30-60 seconds)
sleep 60

# Verify data collection resumed
docker logs ai_infra_promtail | grep "finished transferring" | tail -5
```

---

## Summary

**The Loki dashboard shows "No data" because Promtail hasn't collected new logs since its restart.**

✅ **System is working correctly** - Loki and Promtail are configured properly  
✅ **Data will appear** - As soon as containers generate new log entries  
✅ **No action required** - For production, just wait for natural log activity  
✅ **Optional**: Use force log generation methods above for immediate testing  

The dashboard will automatically populate within minutes as:
- Users authenticate
- Databases query
- Services process requests
- Background jobs run

**Current Status** (as of 09:56 Dec 7, 2025):
- ✅ Loki: Running, healthy
- ✅ Promtail: Running, discovered 7 Docker targets
- ⏳ Log Collection: Waiting for new log activity
- ⏳ Dashboard: Will populate when logs arrive
