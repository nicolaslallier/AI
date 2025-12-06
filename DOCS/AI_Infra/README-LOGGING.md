# PostgreSQL & pgAdmin Logging Infrastructure

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Log Collection Flow](#log-collection-flow)
4. [Log Schema](#log-schema)
5. [Querying Logs in Grafana](#querying-logs-in-grafana)
6. [Dashboards](#dashboards)
7. [Alert Rules](#alert-rules)
8. [Compliance & Security](#compliance--security)
9. [Configuration](#configuration)
10. [Troubleshooting](#troubleshooting)
11. [Performance Impact](#performance-impact)
12. [Best Practices](#best-practices)

---

## Overview

This document describes the centralized logging infrastructure for PostgreSQL and pgAdmin, integrated with the AI Infrastructure monitoring stack (Loki/Grafana/Prometheus).

### Key Features
- **Structured JSON Logging**: All logs are in JSON format for easy parsing and analysis
- **Centralized Collection**: Promtail collects logs from all sources and sends to Loki
- **PII Minimization**: Automatic redaction of sensitive data (passwords, emails, etc.)
- **Comprehensive Dashboards**: Pre-built Grafana dashboards for monitoring and analysis
- **Alerting**: Automated alerts for security incidents, performance issues, and errors
- **Compliance**: Designed to meet Loi 25 (Quebec privacy law) requirements

### Components
- **PostgreSQL 16**: Database with JSON structured logging enabled
- **pgAdmin 4**: Web admin interface with custom JSON logging
- **Promtail**: Log collection agent that scrapes Docker container logs
- **Loki**: Log aggregation and storage system
- **Grafana**: Visualization and querying interface
- **Prometheus**: Alert management and metrics

---

## Architecture

```
┌─────────────┐     ┌─────────────┐
│ PostgreSQL  │     │   pgAdmin   │
│  (JSON logs)│     │ (JSON logs) │
└──────┬──────┘     └──────┬──────┘
       │                   │
       │   Docker Logs     │
       │   (JSON-file)     │
       └──────┬────────────┘
              │
       ┌──────▼──────┐
       │  Promtail   │
       │  (Collector)│
       │  - Parse    │
       │  - Enrich   │
       │  - Filter   │
       └──────┬──────┘
              │
       ┌──────▼──────┐
       │    Loki     │
       │  (Storage)  │
       │  - Index    │
       │  - Compress │
       │  - Retain   │
       └──────┬──────┘
              │
       ┌──────▼──────┐
       │   Grafana   │
       │  (Query &   │
       │  Visualize) │
       └─────────────┘
```

---

## Log Collection Flow

### 1. PostgreSQL Log Generation
- PostgreSQL generates JSON structured logs (configured via `postgresql.conf`)
- Logs include: connections, disconnections, errors, slow queries, authentication events
- Output to Docker's json-file logging driver

### 2. pgAdmin Log Generation
- pgAdmin configured with custom JSON logging (via `config_local.py`)
- Logs include: authentication events, administrative actions, query executions, errors
- Output to stdout (captured by Docker)

### 3. Promtail Collection
- Promtail scrapes Docker container logs via Docker socket
- Identifies containers by labels (`com.docker.compose.service`)
- Parses JSON logs and extracts fields
- Applies PII redaction filters
- Enriches with metadata (environment, source, tier)
- Sends to Loki

### 4. Loki Storage
- Stores logs with configurable retention policies
- Indexes by labels for fast querying
- Compresses historical data
- Retention: Security logs (90d), Operational logs (30d)

### 5. Grafana Visualization
- Queries Loki using LogQL
- Displays in pre-built dashboards
- Enables ad-hoc log exploration
- Triggers alerts based on log patterns

---

## Log Schema

### PostgreSQL Log Fields

**Standard Fields:**
```json
{
  "timestamp": "2024-01-15T10:30:45.123Z",
  "level": "ERROR|WARNING|INFO|LOG|FATAL|PANIC",
  "message": "Log message content",
  "source": "postgres",
  "environment": "development",
  "container": "ai_infra_postgres"
}
```

**PostgreSQL-Specific Fields:**
```json
{
  "user": "postgres",
  "database": "app_db",
  "application_name": "myapp",
  "session_id": "abc123",
  "query_id": "xyz789",
  "error_code": "42P01",
  "backend_type": "client backend",
  "command_tag": "SELECT",
  "duration": "1234.56"
}
```

**Enriched Labels:**
- `log_type`: connection, slow_query, error, admin_log
- `security_event`: auth_failure, admin_action (if applicable)

### pgAdmin Log Fields

**Standard Fields:**
```json
{
  "timestamp": "2024-01-15T10:30:45.123Z",
  "level": "INFO|WARNING|ERROR|DEBUG",
  "source": "pgadmin",
  "message": "Log message content",
  "environment": "development",
  "container": "ai_infra_pgadmin"
}
```

**pgAdmin-Specific Fields:**
```json
{
  "user": "admin@example.com",
  "database": "app_db",
  "module": "pgadmin.browser",
  "function": "login",
  "line": 123,
  "request_id": "req-abc123"
}
```

**Enriched Labels:**
- `log_type`: authentication, admin_action, query_execution, error
- `event_type`: authentication, admin_action, query_execution
- `security_event`: auth_failure, admin_action (if applicable)

---

## Querying Logs in Grafana

### LogQL Basics

LogQL is the query language for Loki. It has two main parts:
1. **Log Stream Selector**: Filters logs by labels
2. **Log Pipeline**: Processes and filters log lines

### Example Queries

#### All PostgreSQL logs
```logql
{source="postgres"}
```

#### PostgreSQL errors only
```logql
{source="postgres", level=~"ERROR|FATAL|PANIC"}
```

#### Slow queries
```logql
{source="postgres", log_type="slow_query"}
```

#### Authentication failures
```logql
{source="postgres", security_event="auth_failure"}
```

#### pgAdmin administrative actions
```logql
{source="pgadmin", security_event="admin_action"}
```

#### Search for specific text in logs
```logql
{source="postgres"} |= "connection refused"
```

#### Parse JSON and filter by database
```logql
{source="postgres"} | json | database="app_db"
```

#### Calculate slow query rate
```logql
sum(rate({source="postgres", log_type="slow_query"}[5m]))
```

#### Top 10 error codes
```logql
topk(10, sum by (error_code) (count_over_time({source="postgres", error_code!=""}[1h])))
```

#### Authentication failures by user
```logql
sum by (user) (count_over_time({source="postgres", security_event="auth_failure"}[1h]))
```

### Advanced Queries

#### Calculate query duration percentiles
```logql
quantile_over_time(0.95, {source="postgres", log_type="slow_query"} | json | unwrap duration [5m])
```

#### Pattern extraction
```logql
{source="postgres"} | regexp "ERROR: (?P<error_msg>.*)"
```

#### Multi-line log parsing
```logql
{source="postgres"} | json | message =~ ".*deadlock.*" or message =~ ".*timeout.*"
```

---

## Dashboards

### PostgreSQL Logs Dashboard (`postgresql-logs`)

**Location**: `docker/grafana/dashboards/postgresql-logs.json`

**Panels:**
1. **Connection Events**: Timeline of connection attempts (success/failure)
2. **Errors & Warnings**: Stacked view of error severity over time
3. **Slow Queries (5m)**: Gauge showing current slow query count
4. **Auth Failures (5m)**: Gauge showing authentication failures
5. **Critical Errors (5m)**: Gauge for FATAL/PANIC errors
6. **Recent Critical Errors**: Live log stream of critical errors
7. **Slow Query Duration Percentiles**: p95 and p99 query duration
8. **Top Active Databases**: Table of most active databases
9. **Top Error Codes**: Table of most common SQL error codes
10. **Authentication Failures**: Log stream of security events
11. **Database Activity by User**: User activity timeline
12. **Slow Query Log Details**: Detailed slow query logs

**Variables:**
- `$environment`: Filter by environment (development/staging/production)

**Refresh Rate**: 30 seconds

### pgAdmin Audit Dashboard (`pgadmin-audit`)

**Location**: `docker/grafana/dashboards/pgadmin-audit.json`

**Panels:**
1. **Total Login Events (24h)**: Count of authentication events
2. **Admin Actions (24h)**: Count of administrative operations
3. **Errors (1h)**: Current error count
4. **Failed Login Attempts (1h)**: Authentication failure gauge
5. **Activity by Event Type**: Timeline of different event types
6. **Log Levels**: Distribution of log severity
7. **Most Active Users**: Table of users by activity
8. **Most Accessed Databases**: Table of database access frequency
9. **Administrative Actions**: Audit trail of admin operations
10. **Failed Authentication Attempts**: Security event log
11. **Operations by Type**: Activity breakdown
12. **Recent Errors**: Error log stream
13. **Query Execution Activity**: User query activity

**Variables:**
- `$environment`: Filter by environment

**Refresh Rate**: 30 seconds

---

## Alert Rules

### Configuration File
**Location**: `docker/prometheus/alerts/database-logs-alerts.yml`

### Alert Groups

#### 1. PostgreSQL Connection Alerts
- **PostgreSQLConnectionFailureRateHigh**: Connection failure rate > 10%
- **PostgreSQLConnectionFailureSpike**: >5 failures/sec (potential attack)

#### 2. PostgreSQL Performance Alerts
- **PostgreSQLSlowQueryThresholdExceeded**: >100 slow queries in 10 minutes
- **PostgreSQLSlowQueryPercentileHigh**: p95 duration >5000ms

#### 3. PostgreSQL Error Alerts
- **PostgreSQLErrorRateHigh**: >50 errors/minute
- **PostgreSQLCriticalError**: Any FATAL/PANIC error
- **PostgreSQLDiskSpaceWarning**: Disk space warnings detected

#### 4. PostgreSQL Availability Alerts
- **PostgreSQLDatabaseDown**: No logs received for 2 minutes

#### 5. PostgreSQL Security Alerts
- **PostgreSQLSuspiciousActivity**: >5 auth failures per user in 5 minutes
- **PostgreSQLUnauthorizedAccessAttempt**: Repeated permission failures

#### 6. pgAdmin Security Alerts
- **pgAdminAuthenticationFailureSpike**: >3 auth failures/sec
- **pgAdminSuspiciousAdminAction**: High rate of DROP/DELETE operations

#### 7. pgAdmin Operational Alerts
- **pgAdminHighErrorRate**: >10 errors/minute
- **pgAdminDown**: No logs received for 2 minutes

#### 8. Compliance Alerts
- **DatabaseAuditLogGap**: No audit logs for 1 hour
- **HighPrivilegeOperations**: >50 privilege operations in 1 hour

### Alert Severity Levels
- **Critical**: Immediate action required, service disruption
- **Warning**: Potential issue, should be investigated
- **Info**: Informational, for awareness and compliance

### Alert Annotations
Each alert includes:
- `summary`: Brief description
- `description`: Detailed explanation
- `impact`: Business/technical impact
- `action`: Recommended remediation steps
- `runbook_url`: Link to detailed runbook (configure your own)

---

## Compliance & Security

### Loi 25 (Quebec Privacy Law) Compliance

#### PII Minimization
Promtail automatically redacts:
- Passwords and secrets (`password=***REDACTED***`)
- Email addresses (`***EMAIL_REDACTED***`)
- Credit card numbers (`***CC_REDACTED***`)
- Connection strings (credentials removed)

#### Retention Policies
- **Security/Audit Logs**: 90 days (configurable via Loki retention)
- **Operational Logs**: 30 days (default)
- **Compliance**: Can be extended to 1 year for audit purposes

#### Access Control
- Grafana authentication required
- Role-based access to dashboards
- Audit trail of who accessed what logs

#### Data Location
- All logs stored locally in Docker volumes
- No external transmission by default
- Encryption in transit within Docker networks

### Security Best Practices

1. **Rotate Credentials**: Change default passwords for pgAdmin, Grafana
2. **Enable TLS**: Configure HTTPS for production (currently disabled)
3. **Restrict Access**: Use firewall rules to limit access to monitoring interfaces
4. **Monitor Alerts**: Set up alert notification channels (email, Slack, Teams)
5. **Regular Audits**: Review security logs weekly
6. **Backup Logs**: Consider backing up critical security logs externally

---

## Configuration

### Environment Variables

Add to `.env` file or docker-compose:

```bash
# PostgreSQL Logging
POSTGRES_LOG_LEVEL=WARNING              # Minimum log level
POSTGRES_SLOW_QUERY_MS=1000            # Slow query threshold in ms

# pgAdmin Logging
PGADMIN_LOG_LEVEL=INFO                 # Log level: DEBUG|INFO|WARNING|ERROR

# Loki Retention
LOKI_RETENTION_DAYS_SECURITY=90        # Security log retention
LOKI_RETENTION_DAYS_OPERATIONAL=30     # Operational log retention

# Alerting
ALERT_NOTIFICATION_CHANNEL=email       # Alert channel (configure in Prometheus)

# Environment Tag
ENVIRONMENT=development                # development|staging|production
```

### Adjusting Log Levels

#### PostgreSQL
Edit `docker/postgres/postgresql.conf`:
```conf
log_min_messages = warning             # warning|info|notice|log
log_min_error_statement = error        # error|log|warning
log_min_duration_statement = 1000      # Slow query threshold (ms)
```

#### pgAdmin
Edit `docker/pgadmin/config_local.py`:
```python
LOG_LEVEL = 'INFO'  # DEBUG|INFO|WARNING|ERROR|CRITICAL
```

#### Promtail
Edit `docker/promtail/promtail.yml` to adjust:
- PII redaction rules
- Label extraction
- Pipeline stages

### Changing Retention Policies

Edit `docker/loki/loki.yml`:
```yaml
limits_config:
  retention_period: 720h  # 30 days in hours

compactor:
  retention_enabled: true
  retention_delete_delay: 2h
```

---

## Troubleshooting

### No Logs Appearing in Grafana

**Check 1: Verify Promtail is running**
```bash
docker ps | grep promtail
docker logs ai_infra_promtail
```

**Check 2: Verify logs are being generated**
```bash
docker logs ai_infra_postgres | head -20
docker logs ai_infra_pgadmin | head -20
```

**Check 3: Check Loki connectivity**
```bash
curl http://localhost:3100/ready
```

**Check 4: Check Promtail targets**
Navigate to: `http://localhost:9080/targets`

**Check 5: Verify Docker socket access**
```bash
docker exec ai_infra_promtail ls -la /var/run/docker.sock
```

### Logs Not in JSON Format

**PostgreSQL**: Verify PostgreSQL version is 15+
```bash
docker exec ai_infra_postgres psql -U postgres -c "SELECT version();"
```

If PostgreSQL < 15, JSON logging is not available. Promtail will parse text logs instead.

**pgAdmin**: Verify config file is mounted
```bash
docker exec ai_infra_pgadmin ls -la /pgadmin4/config_local.py
```

### High Resource Usage

**Promtail CPU/Memory High:**
- Reduce log volume by increasing `log_min_messages` in PostgreSQL
- Adjust `readline_rate` in Promtail config
- Increase resource limits in docker-compose

**Loki Disk Usage High:**
- Reduce retention period
- Enable compaction
- Consider using object storage (S3) for older logs

**Query Performance Slow:**
- Add more specific label filters
- Reduce time range
- Use `| json` parser only when needed
- Consider upgrading Loki resources

### Alert Not Triggering

**Check 1: Verify alert rule syntax**
```bash
docker exec ai_infra_prometheus promtool check rules /etc/prometheus/alerts/database-logs-alerts.yml
```

**Check 2: Check Prometheus targets**
Navigate to: `http://localhost:9090/targets`

**Check 3: Query Loki directly**
Use Grafana Explore to test the alert query

**Check 4: Check alert evaluation**
Navigate to: `http://localhost:9090/alerts`

### PII Still Visible in Logs

**Check 1: Verify Promtail pipeline**
Review pipeline stages in `promtail.yml`

**Check 2: Test regex patterns**
```bash
echo 'password=secret123' | sed -E 's/(password|secret|token)=[^ ]+/\1=***REDACTED***/g'
```

**Check 3: Add custom redaction rules**
Edit Promtail pipeline stages to add more patterns

---

## Performance Impact

### PostgreSQL Performance

**JSON Logging Overhead:**
- CPU: ~2-5% increase for JSON formatting
- Disk I/O: ~10-15% increase due to larger log size
- Negligible impact on query performance

**Recommendations:**
- Set `log_min_duration_statement` appropriately (1000ms default)
- Avoid logging all statements (`log_statement = 'none'` or `'ddl'`)
- Use log rotation to prevent disk filling

### Promtail Performance

**Resource Usage:**
- CPU: 0.1-0.5 cores (depending on log volume)
- Memory: 64-256 MB
- Network: Minimal (compressed transmission to Loki)

**Optimization:**
- Adjust `readline_rate` to limit ingestion speed
- Use batch processing for high-volume scenarios
- Monitor Promtail metrics

### Loki Performance

**Storage Estimates:**
- PostgreSQL: ~10-50 MB/day per database (varies with activity)
- pgAdmin: ~5-20 MB/day
- Total: ~50-200 MB/day for typical usage

**Query Performance:**
- Label-based queries: < 1 second
- Full-text search: 1-5 seconds (depends on time range)
- Complex aggregations: 5-15 seconds

---

## Best Practices

### Logging

1. **Log Appropriate Levels**: Don't log everything; focus on errors, security events, and slow queries
2. **Use Structured Logging**: Always use JSON format for easy parsing
3. **Include Context**: Add correlation IDs, request IDs, user IDs when available
4. **Avoid Sensitive Data**: Never log passwords, API keys, PII unless absolutely necessary and encrypted

### Monitoring

1. **Review Dashboards Regularly**: Check dashboards daily for anomalies
2. **Set Up Alerts**: Configure notification channels (email, Slack) for critical alerts
3. **Test Alerts**: Regularly test alert rules by simulating conditions
4. **Dashboard Customization**: Customize dashboards to your specific needs

### Security

1. **Regular Audits**: Review security logs weekly
2. **Investigate Anomalies**: Don't ignore unusual patterns
3. **Update Regularly**: Keep all components up to date
4. **Backup Logs**: Back up critical audit logs externally
5. **Access Control**: Restrict who can view sensitive logs

### Compliance

1. **Document Retention**: Maintain documentation of retention policies
2. **Audit Access**: Track who accesses audit logs
3. **PII Inventory**: Document what PII is logged and why
4. **Data Minimization**: Regularly review and minimize logged data
5. **Privacy Reviews**: Conduct periodic privacy impact assessments

### Performance

1. **Monitor Resource Usage**: Track Loki/Promtail resource consumption
2. **Optimize Queries**: Use specific labels and time ranges
3. **Archive Old Logs**: Consider moving old logs to cold storage
4. **Capacity Planning**: Monitor growth trends and plan for scaling

---

## Useful Commands

### View Live Logs
```bash
# PostgreSQL logs
docker logs -f ai_infra_postgres

# pgAdmin logs
docker logs -f ai_infra_pgadmin

# Promtail logs
docker logs -f ai_infra_promtail
```

### Query Loki Directly
```bash
# Check Loki ready status
curl http://localhost:3100/ready

# Query logs via API
curl -G -s "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={source="postgres"}' \
  --data-urlencode 'limit=10' | jq .
```

### Check Disk Usage
```bash
# Loki data size
docker exec ai_infra_loki du -sh /loki

# Promtail position file
docker exec ai_infra_promtail cat /tmp/positions.yaml
```

### Restart Services
```bash
# Restart Promtail
docker restart ai_infra_promtail

# Restart Loki
docker restart ai_infra_loki

# Reload Prometheus config
docker exec ai_infra_prometheus kill -HUP 1
```

---

## Support and Resources

### Internal Documentation
- Architecture: `/docs/ARCHITECTURE.md`
- Environment Variables: `/docs/ENV_VARIABLES.md`
- CI/CD Setup: `/docs/CICD_SETUP.md`

### External Resources
- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [LogQL Query Language](https://grafana.com/docs/loki/latest/logql/)
- [Promtail Configuration](https://grafana.com/docs/loki/latest/clients/promtail/)
- [PostgreSQL Logging](https://www.postgresql.org/docs/current/runtime-config-logging.html)

### Contact
For questions or issues:
- Internal DevOps Team
- Security Team (for security-related issues)
- DBA Team (for database-specific issues)

---

## Version History

- **v1.0** (2024-12): Initial implementation
  - PostgreSQL JSON logging
  - pgAdmin structured logging
  - Promtail collection
  - Loki storage with retention
  - Grafana dashboards
  - Alert rules
  - PII minimization
  - Compliance documentation

