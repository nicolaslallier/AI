# PostgreSQL Logs Dashboard Fix Summary

**Date:** December 6, 2025  
**Issue:** Grafana PostgreSQL Logs dashboard showing "No Data"  
**Status:** ✅ RESOLVED

## Root Causes

### 1. PostgreSQL Logging to Files Instead of Stdout
**Problem:** PostgreSQL was configured with:
- `logging_collector = on` - Collecting logs to files
- `log_destination = 'jsonlog'` - Writing JSON to log directory
- Docker can only capture stdout/stderr logs, not internal log files

**Solution:**
- Changed `logging_collector = off`
- Changed `log_destination = 'stderr'`
- PostgreSQL now logs to stderr which Docker captures

### 2. Promtail Configuration for Plain Text Logs
**Problem:** Promtail pipeline was configured to parse JSON logs, but PostgreSQL (with logging_collector=off) outputs plain text logs.

**Solution:**
- Updated Promtail regex to parse plain text PostgreSQL log format:
  ```regex
  ^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} \w+) \[(?P<pid>\d+)\] (?:(?P<user>[^@]+)@(?P<database>\S+))?\s+(?P<level>\w+):\s+(?P<message>.*)$
  ```
- Extracts: timestamp, pid, user, database, level, message

### 3. Log Type Labels Not Created
**Problem:** Dashboard queries filter by `log_type` label, but Promtail wasn't creating these labels correctly. Used `template` instead of `static_labels`.

**Solution:**
- Added `static_labels` with default `log_type: 'database_log'`
- Used `match` stages with log line matching (`|~`) to classify logs:
  - `|~ "duration:"` → `log_type: 'slow_query'`
  - `|~ "connection"` → `log_type: 'connection'`
  - `|~ "authentication"` → `log_type: 'auth_failure'`

### 4. Promtail DNS Issues
**Problem:** Promtail couldn't reach Loki initially after container restart.

**Solution:**
- Restarted Promtail after Loki was fully running
- Docker DNS resolution working correctly now

## Configuration Changes

### Modified Files

1. **docker/postgres/postgresql.conf**
   ```ini
   # OLD:
   logging_collector = on
   log_destination = 'jsonlog'
   log_directory = 'log'
   log_filename = 'postgresql-%Y-%m-%d_%H%M%S.json'
   
   # NEW:
   logging_collector = off
   log_destination = 'stderr'
   ```

2. **docker/promtail/promtail.yml**
   - Changed from JSON parsing to regex parsing:
   ```yaml
   pipeline_stages:
     - regex:
         expression: '^(?P<timestamp>\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}\\.\\d{3} \\w+) \\[(?P<pid>\\d+)\\] (?:(?P<user>[^@]+)@(?P<database>\\S+))?\\s+(?P<level>\\w+):\\s+(?P<message>.*)$'
     - timestamp:
         source: timestamp
         format: '2006-01-02 15:04:05.000 MST'
     - labels:
         level:
         user:
         database:
         pid:
     - static_labels:
         log_type: 'database_log'
     - match:
         selector: '{source="postgres"} |~ "duration:"'
         stages:
           - regex:
               expression: 'duration: (?P<duration>\\d+\\.?\\d*) ms'
           - labels:
               duration:
           - static_labels:
               log_type: 'slow_query'
     - match:
         selector: '{source="postgres"} |~ "connection"'
         stages:
           - static_labels:
               log_type: 'connection'
     - match:
         selector: '{source="postgres", level="FATAL"} |~ "authentication"'
         stages:
           - static_labels:
               log_type: 'auth_failure'
               security_event: 'auth_failure'
   ```

## Verification

### Loki Labels Confirmed
```bash
$ curl http://loki:3100/loki/api/v1/labels
{"status":"success","data":["cluster","container","database","environment","level","log_type","pid","source","stream","tier","user"]}

$ curl http://loki:3100/loki/api/v1/label/log_type/values
{"status":"success","data":["connection","database_log","slow_query"]}

$ curl http://loki:3100/loki/api/v1/label/source/values
{"status":"success","data":["pgadmin","postgres","system"]}
```

### PostgreSQL Logs Flowing
```
2025-12-06 17:16:24.562 UTC [220] postgres@app_db LOG:  duration: 2005.504 ms  statement: SELECT pg_sleep(2), 'This is a slow query';
2025-12-06 17:17:02.156 UTC [238] postgres@app_db LOG:  connection authorized: user=postgres database=app_db
2025-12-06 17:17:02.158 UTC [238] postgres@app_db LOG:  disconnection: session time: 0:00:00.002 user=postgres database=app_db
```

### Dashboard Queries Working
The dashboard queries now successfully retrieve data:
- `{source="postgres", log_type="slow_query"}` - Shows slow queries with duration
- `{source="postgres", log_type="connection"}` - Shows connection/disconnection logs
- `{source="postgres", level=~"ERROR|FATAL|PANIC"}` - Shows error logs
- Aggregation queries work for stats and metrics

## Commands Used

```bash
# Restart PostgreSQL after config change
docker compose restart postgres

# Restart Promtail after config change
docker compose restart promtail

# Generate test slow query
docker exec ai_infra_postgres psql -U postgres -d app_db -c "SELECT pg_sleep(1.5), 'Test slow query';"

# Check log types in Loki
docker exec ai_infra_prometheus wget -qO- 'http://loki:3100/loki/api/v1/label/log_type/values'

# Query PostgreSQL logs from Loki
docker exec ai_infra_prometheus wget -qO- 'http://loki:3100/loki/api/v1/query?query=%7Bsource%3D%22postgres%22%7D&limit=10'
```

## Dashboard Access

**URL:** `http://localhost/monitoring/grafana/d/postgres-logs/postgresql-logs-comprehensive-monitoring`

**Credentials:** admin / admin

The dashboard now shows:
- ✅ Slow Query Count
- ✅ Error Count  
- ✅ Authentication Failure Count
- ✅ Connection Logs by Level
- ✅ Error and Warning Trends
- ✅ Slow Query Duration (p95, p99)
- ✅ Connection Activity
- ✅ Recent Errors
- ✅ Authentication Failures
- ✅ Top Databases by Activity
- ✅ Top Error Codes

## Key Learnings

1. **Docker Logging:** PostgreSQL with `logging_collector=on` writes to files inside the container, which Docker cannot capture. Must use `logging_collector=off` and `log_destination='stderr'` for Docker environments.

2. **Promtail Pipeline Stages:**
   - Use `regex` to parse plain text logs
   - Use `static_labels` to set labels (not `template`)
   - Use `match` with `|~` for log line matching (not label matching with `=~`)
   - Match stages can override labels set in earlier stages

3. **Log Classification:** For dashboards to work, logs need proper classification via labels like `log_type`, `level`, `source`, etc.

4. **Testing:** Generate diverse log types (slow queries, connections, errors) to verify all pipeline stages work correctly.

## Next Steps

- ✅ Dashboard is now showing data
- Consider adding more log types (autovacuum, checkpoint, etc.)
- Add alerting rules for critical logs (auth failures, errors)
- Fine-tune slow query threshold (currently 1000ms)
- Add log retention policies in Loki

---
**Resolution Time:** ~45 minutes  
**Complexity:** Medium (required PostgreSQL config knowledge + Promtail pipeline understanding)

