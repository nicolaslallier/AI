# PostgreSQL & pgAdmin Logging Implementation - Validation Checklist

## Overview
This document provides a comprehensive checklist to validate the PostgreSQL and pgAdmin logging implementation.

---

## Pre-Deployment Validation

### Configuration Files Created ✓
- [x] `docker/postgres/postgresql.conf` - Updated with JSON logging
- [x] `docker/pgadmin/config_local.py` - Created with JSON logging configuration
- [x] `docker/promtail/promtail.yml` - Created with scrape configs and PII filters
- [x] `docker/loki/loki.yml` - Updated with retention policies
- [x] `docker/grafana/dashboards/postgresql-logs.json` - PostgreSQL dashboard
- [x] `docker/grafana/dashboards/pgadmin-audit.json` - pgAdmin audit dashboard
- [x] `docker/prometheus/alerts/database-logs-alerts.yml` - Alert rules
- [x] `docker/README-LOGGING.md` - Comprehensive documentation
- [x] `docker-compose.yml` - Updated with Promtail service and labels

### Configuration Review

#### PostgreSQL Configuration (`postgresql.conf`)
- [ ] `log_destination = 'jsonlog'` is set
- [ ] `logging_collector = on`
- [ ] `log_connections = on`
- [ ] `log_disconnections = on`
- [ ] `log_min_duration_statement` is configured (1000ms)
- [ ] `log_statement = 'ddl'` for audit trail
- [ ] Log file rotation configured

#### pgAdmin Configuration (`config_local.py`)
- [ ] JSON formatter class defined
- [ ] LOG_LEVEL configurable via environment
- [ ] Audit logging enabled
- [ ] PII masking configured
- [ ] Logging to stdout for Docker capture

#### Promtail Configuration (`promtail.yml`)
- [ ] Loki client URL configured correctly
- [ ] Docker service discovery configured
- [ ] PostgreSQL scrape config present
- [ ] pgAdmin scrape config present
- [ ] JSON parsing stages configured
- [ ] PII redaction filters present (passwords, emails, credit cards)
- [ ] Label extraction configured
- [ ] Retry and backoff configured

#### Loki Configuration (`loki.yml`)
- [ ] Retention enabled
- [ ] Compactor configured
- [ ] Retention period set (720h = 30 days)
- [ ] Ingestion rate limits appropriate
- [ ] Storage paths configured

#### Docker Compose (`docker-compose.yml`)
- [ ] Promtail service added
- [ ] Promtail depends on Loki
- [ ] Promtail has access to Docker socket
- [ ] PostgreSQL has logging labels
- [ ] pgAdmin has logging labels and config volume
- [ ] PostgreSQL environment variables added
- [ ] pgAdmin environment variables added
- [ ] All services in appropriate networks

---

## Deployment Testing

### Step 1: Start Services

```bash
cd /Users/nicolaslallier/Dev\ Nick/AI_Infra
docker-compose up -d
```

#### Validation:
- [ ] All services start successfully
- [ ] No error messages in startup logs
- [ ] All containers show as "healthy" after health checks

**Check container status:**
```bash
docker ps --filter "name=ai_infra"
```

**Expected containers:**
- ai_infra_postgres (healthy)
- ai_infra_pgadmin (healthy)
- ai_infra_promtail (healthy)
- ai_infra_loki (healthy)
- ai_infra_grafana (healthy)
- ai_infra_prometheus (healthy)

### Step 2: Verify Log Generation

#### PostgreSQL Logs
```bash
# Check if PostgreSQL is generating logs
docker logs ai_infra_postgres --tail 50

# Expected: JSON formatted logs visible
```

**Validation:**
- [ ] Logs are in JSON format (if PostgreSQL 15+)
- [ ] Timestamp field present
- [ ] Level field present
- [ ] Message field present
- [ ] No plain text logs mixed in

#### pgAdmin Logs
```bash
# Check if pgAdmin is generating logs
docker logs ai_infra_pgadmin --tail 50

# Expected: JSON formatted logs visible
```

**Validation:**
- [ ] Logs contain JSON objects
- [ ] Custom logging configuration is active
- [ ] Startup logs visible

### Step 3: Verify Promtail Collection

```bash
# Check Promtail logs
docker logs ai_infra_promtail --tail 100

# Check Promtail targets
curl http://localhost:9080/targets | jq
```

**Validation:**
- [ ] Promtail successfully connected to Loki
- [ ] Docker service discovery finding PostgreSQL container
- [ ] Docker service discovery finding pgAdmin container
- [ ] No error messages about parsing
- [ ] Targets endpoint shows both services

**Expected output in targets:**
```json
{
  "activeTargets": [
    {
      "labels": {
        "source": "postgres",
        ...
      }
    },
    {
      "labels": {
        "source": "pgadmin",
        ...
      }
    }
  ]
}
```

### Step 4: Verify Loki Storage

```bash
# Check Loki health
curl http://localhost:3100/ready

# Query Loki for PostgreSQL logs
curl -G -s "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={source="postgres"}' \
  --data-urlencode 'limit=10' | jq '.data.result | length'

# Query Loki for pgAdmin logs
curl -G -s "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={source="pgadmin"}' \
  --data-urlencode 'limit=10' | jq '.data.result | length'
```

**Validation:**
- [ ] Loki returns "ready" status
- [ ] PostgreSQL logs are queryable (count > 0)
- [ ] pgAdmin logs are queryable (count > 0)
- [ ] Query response time < 2 seconds

### Step 5: Verify Grafana Dashboards

**Access Grafana:**
```
http://localhost/monitoring/grafana/
```

**Login:**
- Username: admin (or as configured)
- Password: admin (or as configured)

#### PostgreSQL Logs Dashboard
Navigate to: Dashboards → PostgreSQL Logs - Comprehensive Monitoring

**Validation:**
- [ ] Dashboard loads without errors
- [ ] All panels show data
- [ ] "Connection Events" panel shows activity
- [ ] "Errors & Warnings" panel displays correctly
- [ ] "Slow Queries" gauge has data (may be 0, which is okay)
- [ ] "Top Active Databases" table populated
- [ ] Log panels show actual log entries
- [ ] Time range selector works
- [ ] Environment variable selector present

#### pgAdmin Audit Dashboard
Navigate to: Dashboards → pgAdmin Audit & Security Logs

**Validation:**
- [ ] Dashboard loads without errors
- [ ] Stat panels show metrics (may be low initially)
- [ ] "Activity by Event Type" shows data
- [ ] "Most Active Users" table has entries
- [ ] Log panels display pgAdmin logs
- [ ] All visualizations render correctly

### Step 6: Test Log Exploration

In Grafana, navigate to: Explore → Select "Loki" data source

**Test Queries:**

1. All PostgreSQL logs:
```logql
{source="postgres"}
```
- [ ] Returns logs

2. PostgreSQL errors:
```logql
{source="postgres", level=~"ERROR|FATAL"}
```
- [ ] Returns only error logs (or none if no errors)

3. pgAdmin logs:
```logql
{source="pgadmin"}
```
- [ ] Returns pgAdmin logs

4. Test JSON parsing:
```logql
{source="postgres"} | json
```
- [ ] Parses JSON fields successfully

**Validation:**
- [ ] All queries execute within 5 seconds
- [ ] Log lines are properly formatted
- [ ] Labels are correctly applied
- [ ] JSON fields are parsed

---

## Functional Testing

### Test 1: PostgreSQL Connection Logging

**Action:** Connect to PostgreSQL
```bash
docker exec -it ai_infra_postgres psql -U postgres -d app_db -c "SELECT 1;"
```

**Validation in Grafana:**
- [ ] Connection event appears in logs
- [ ] User is logged (postgres)
- [ ] Database is logged (app_db)
- [ ] Timestamp is correct
- [ ] Connection Events panel shows increase

### Test 2: PostgreSQL Error Logging

**Action:** Generate an error
```bash
docker exec -it ai_infra_postgres psql -U postgres -d app_db -c "SELECT * FROM nonexistent_table;"
```

**Validation in Grafana:**
- [ ] Error appears in "Recent Critical Errors" or error logs
- [ ] Error level is "ERROR"
- [ ] Error code is captured (42P01 - undefined table)
- [ ] "Errors & Warnings" panel shows increase
- [ ] "Top Error Codes" table includes the error

### Test 3: PostgreSQL Slow Query Logging

**Action:** Execute a slow query
```bash
docker exec -it ai_infra_postgres psql -U postgres -d app_db -c "SELECT pg_sleep(2);"
```

**Validation in Grafana:**
- [ ] Slow query appears in logs
- [ ] Duration is captured (~2000ms)
- [ ] "Slow Query Duration Percentiles" panel updates
- [ ] "Slow Queries (5m)" gauge increases
- [ ] Log type is "slow_query"

### Test 4: PostgreSQL Authentication Failure

**Action:** Attempt connection with wrong password
```bash
docker exec -it ai_infra_postgres psql -U postgres -d app_db -c "ALTER USER postgres PASSWORD 'temporary_test_pwd';"
docker run --rm --network ai_infra_database-net postgres:16-alpine psql -h postgres -U postgres -d app_db -c "SELECT 1;" || true
docker exec -it ai_infra_postgres psql -U postgres -d app_db -c "ALTER USER postgres PASSWORD 'postgres';"
```

**Validation in Grafana:**
- [ ] Authentication failure logged
- [ ] Security event label present (auth_failure)
- [ ] "Auth Failures (5m)" gauge increases
- [ ] Appears in "Authentication Failures (Security)" log panel
- [ ] User is captured

### Test 5: pgAdmin Access Logging

**Action:** Access pgAdmin interface
1. Navigate to: http://localhost/pgadmin
2. Login with credentials
3. Connect to PostgreSQL server
4. Run a simple query

**Validation in Grafana:**
- [ ] Login event appears in pgAdmin logs
- [ ] Authentication event type is set
- [ ] User is captured in logs
- [ ] "Total Login Events (24h)" increases
- [ ] Activity appears in "Activity by Event Type" panel

### Test 6: pgAdmin Administrative Action

**Action:** Perform admin operation in pgAdmin
1. In pgAdmin, create a test table:
```sql
CREATE TABLE test_logging (id serial, name text);
```
2. Drop the test table:
```sql
DROP TABLE test_logging;
```

**Validation in Grafana:**
- [ ] CREATE statement logged
- [ ] DROP statement logged
- [ ] Security event labeled as "admin_action"
- [ ] Appears in "Administrative Actions (Audit Trail)"
- [ ] "Admin Actions (24h)" count increases

---

## Security & Compliance Testing

### Test 7: PII Redaction - Passwords

**Action:** Check if passwords are redacted
```bash
# This should be redacted in logs
docker exec -it ai_infra_postgres psql -U postgres -d app_db -c "CREATE USER test_user WITH PASSWORD 'secret123';"
docker exec -it ai_infra_postgres psql -U postgres -d app_db -c "DROP USER test_user;"
```

**Validation in Grafana:**
- [ ] Query logs in Grafana: `{source="postgres"} |= "PASSWORD"`
- [ ] Password value is redacted (shows `***REDACTED***`)
- [ ] SQL statement is partially visible (CREATE USER part)

### Test 8: PII Redaction - Emails

**Action:** Insert data with email (if applicable)
```bash
docker exec -it ai_infra_postgres psql -U postgres -d app_db -c "CREATE TABLE IF NOT EXISTS test_pii (email text); INSERT INTO test_pii VALUES ('user@example.com'); SELECT * FROM test_pii; DROP TABLE test_pii;"
```

**Validation in Grafana:**
- [ ] Check logs for email addresses
- [ ] Email should be redacted if it appears in logs
- [ ] Pattern: `***EMAIL_REDACTED***`

### Test 9: Retention Policy Verification

**Check Loki Configuration:**
```bash
docker exec ai_infra_loki cat /etc/loki/loki.yml | grep -A 5 retention
```

**Validation:**
- [ ] `retention_enabled: true`
- [ ] `retention_period: 720h` (30 days)
- [ ] Compactor configured
- [ ] Delete delay configured

### Test 10: Access Control

**Validation:**
- [ ] Grafana requires authentication
- [ ] Cannot access Loki directly without proper network access
- [ ] pgAdmin requires authentication
- [ ] Promtail metrics endpoint is not publicly exposed

---

## Alert Testing

### Test 11: Connection Failure Alert (Simulated)

**Note:** This requires generating 10%+ connection failures over 5 minutes, which is difficult to simulate safely. Skip this test if unable to generate safely.

**Alternative:** Verify alert configuration
```bash
docker exec ai_infra_prometheus cat /etc/prometheus/alerts/database-logs-alerts.yml | grep -A 20 "ConnectionFailureRateHigh"
```

**Validation:**
- [ ] Alert rule exists
- [ ] Threshold is 0.1 (10%)
- [ ] Duration is 5m
- [ ] Severity is "warning"
- [ ] Annotations are present

### Test 12: Slow Query Alert

**Check alert rule:**
```bash
docker exec ai_infra_prometheus cat /etc/prometheus/alerts/database-logs-alerts.yml | grep -A 20 "SlowQueryThresholdExceeded"
```

**Validation:**
- [ ] Alert rule exists
- [ ] Threshold is 100 queries in 10m
- [ ] Alert includes recommended actions

### Test 13: Critical Error Alert

**Check alert rule:**
```bash
docker exec ai_infra_prometheus cat /etc/prometheus/alerts/database-logs-alerts.yml | grep -A 20 "CriticalError"
```

**Validation:**
- [ ] Alert rule exists
- [ ] Triggers on FATAL or PANIC
- [ ] Immediate trigger (for: 0m)
- [ ] Severity is "critical"

### Test 14: Alert Manager Integration (Optional)

If AlertManager is configured:
- [ ] Alerts are visible in Prometheus: http://localhost:9090/alerts
- [ ] AlertManager receives alerts: http://localhost:9093 (if configured)
- [ ] Notification channels are working (email, Slack, etc.)

---

## Performance Testing

### Test 15: Resource Usage Baseline

**Measure before heavy load:**
```bash
docker stats --no-stream ai_infra_promtail
docker stats --no-stream ai_infra_loki
docker stats --no-stream ai_infra_postgres
```

**Validation:**
- [ ] Promtail CPU < 5%
- [ ] Promtail Memory < 256MB
- [ ] Loki CPU < 10%
- [ ] Loki Memory < 1GB
- [ ] PostgreSQL performance not significantly degraded

### Test 16: Query Performance

**Test query speed in Grafana Explore:**

1. Simple label query:
```logql
{source="postgres"}
```
- [ ] Returns in < 2 seconds

2. JSON parsing query:
```logql
{source="postgres"} | json | database="app_db"
```
- [ ] Returns in < 3 seconds

3. Aggregation query:
```logql
sum(count_over_time({source="postgres"}[5m]))
```
- [ ] Returns in < 2 seconds

### Test 17: Log Volume Test

**Generate moderate log volume:**
```bash
for i in {1..100}; do
  docker exec ai_infra_postgres psql -U postgres -d app_db -c "SELECT $i;"
done
```

**Validation:**
- [ ] All logs collected
- [ ] No errors in Promtail logs
- [ ] Loki ingestion rate within limits
- [ ] Query performance remains acceptable
- [ ] No memory spikes

---

## Documentation Validation

### Test 18: Documentation Completeness

**Review documentation file:**
```bash
cat docker/README-LOGGING.md
```

**Validation:**
- [ ] Architecture diagram present
- [ ] Log schema documented
- [ ] Example queries provided
- [ ] Dashboard descriptions complete
- [ ] Alert rules documented
- [ ] Compliance section present
- [ ] Troubleshooting guide included
- [ ] Configuration examples provided
- [ ] Performance impact discussed

### Test 19: Runbook Links

**Validation:**
- [ ] Alert annotations include action items
- [ ] Runbook URLs are defined (even if placeholder)
- [ ] Remediation steps are clear
- [ ] Contact information provided

---

## Compliance Validation

### Test 20: Loi 25 Compliance

**Validation:**
- [ ] PII minimization implemented (redaction filters)
- [ ] Retention policies defined and documented
- [ ] Access controls in place (Grafana auth)
- [ ] Data location documented (local only)
- [ ] Audit trail for administrative actions
- [ ] Documentation of data processing purposes
- [ ] User rights procedures documented (if applicable)

### Test 21: Security Audit Trail

**Validation:**
- [ ] All authentication attempts logged
- [ ] Administrative actions logged
- [ ] DDL operations logged
- [ ] Privilege changes logged
- [ ] Logs include timestamps and user IDs
- [ ] Logs are tamper-evident (write-once to Loki)

---

## Final Validation

### Checklist Summary

**Configuration:** ___/10 checks passed
**Deployment:** ___/6 checks passed
**Functional Tests:** ___/6 tests passed
**Security Tests:** ___/4 tests passed
**Alert Tests:** ___/4 tests passed
**Performance Tests:** ___/3 tests passed
**Documentation:** ___/2 checks passed
**Compliance:** ___/2 checks passed

**TOTAL:** ___/37 validations passed

### Sign-Off

**Implementation Date:** ________________

**Tested By:** ________________

**Approved By:** ________________

**Notes:**
_________________________________________________________________
_________________________________________________________________
_________________________________________________________________

### Known Issues

List any issues discovered during testing:
1. _________________________________________________________________
2. _________________________________________________________________
3. _________________________________________________________________

### Next Steps

- [ ] Schedule production deployment
- [ ] Configure alert notification channels
- [ ] Set up backup for critical logs
- [ ] Train team on dashboard usage
- [ ] Schedule regular audit reviews
- [ ] Document custom modifications

---

## Quick Start Testing Script

For rapid validation, use this script:

```bash
#!/bin/bash
# Quick validation script

echo "=== PostgreSQL & pgAdmin Logging Validation ==="

echo -n "1. Checking containers... "
if docker ps | grep -q "ai_infra_postgres.*healthy" && \
   docker ps | grep -q "ai_infra_promtail.*healthy" && \
   docker ps | grep -q "ai_infra_loki.*healthy"; then
    echo "✓ PASS"
else
    echo "✗ FAIL"
fi

echo -n "2. Checking Loki... "
if curl -s http://localhost:3100/ready | grep -q "ready"; then
    echo "✓ PASS"
else
    echo "✗ FAIL"
fi

echo -n "3. Checking PostgreSQL logs in Loki... "
if curl -s -G "http://localhost:3100/loki/api/v1/query_range" \
    --data-urlencode 'query={source="postgres"}' | grep -q "result"; then
    echo "✓ PASS"
else
    echo "✗ FAIL"
fi

echo -n "4. Checking pgAdmin logs in Loki... "
if curl -s -G "http://localhost:3100/loki/api/v1/query_range" \
    --data-urlencode 'query={source="pgadmin"}' | grep -q "result"; then
    echo "✓ PASS"
else
    echo "✗ FAIL"
fi

echo -n "5. Checking Promtail targets... "
if curl -s http://localhost:9080/targets | grep -q "postgres"; then
    echo "✓ PASS"
else
    echo "✗ FAIL"
fi

echo ""
echo "=== Validation Complete ==="
echo "For detailed testing, follow the full checklist in VALIDATION-CHECKLIST.md"
```

Save as `validate-logging.sh` and run:
```bash
chmod +x validate-logging.sh
./validate-logging.sh
```

