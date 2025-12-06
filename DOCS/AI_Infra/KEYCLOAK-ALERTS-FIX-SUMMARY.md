# Keycloak Alerts Parse Error - Fix Summary

**Date**: December 6, 2025  
**Issue**: Prometheus failing to start due to LogQL syntax in alert rules  
**Status**: ✅ RESOLVED

---

## Problem Description

Prometheus was encountering parse errors when loading `keycloak-alerts.yml`:

```
parse error: unexpected character: '|'
/etc/prometheus/alerts/keycloak-alerts.yml: 94:15: 
  group "keycloak_authentication_security", rule 3, "KeycloakAccountLockout": 
  could not parse expression: 1:37: parse error: unexpected character: '|'

/etc/prometheus/alerts/keycloak-alerts.yml: 148:15: 
  group "keycloak_database_connectivity", rule 1, "KeycloakDatabaseConnectionErrors": 
  could not parse expression: 1:52: parse error: unexpected character: '|'
```

## Root Cause Analysis

### The Issue

Several alert rules in `keycloak-alerts.yml` were using **LogQL (Loki Query Language)** syntax instead of **PromQL (Prometheus Query Language)**:

```yaml
# INCORRECT - LogQL syntax in Prometheus alert
expr: |
  count_over_time({source="keycloak"} |~ "(?i)account.*locked"[10m]) > 0
```

The `|~` operator is a LogQL pipe operator used for log filtering, not a PromQL operator.

### Why This Happened

1. **Different Query Languages**: 
   - **Prometheus (PromQL)**: Queries time-series metrics (numbers over time)
   - **Loki (LogQL)**: Queries log streams (text/JSON log entries)

2. **Incompatible Operators**:
   - LogQL uses pipe operators like `|~`, `| json`, `| unwrap`
   - PromQL uses label matchers and mathematical operators

3. **Wrong Tool for the Job**: Log-based alerts attempting to query log patterns should use **Loki Ruler**, not Prometheus

## Solution Implemented

### 1. Identified Problematic Alerts

All alerts using LogQL syntax were identified and removed from the Prometheus configuration:

**Disabled Alert Groups:**
- `keycloak_authentication_security` - Authentication failure patterns from logs
- `keycloak_admin_events` - Admin configuration changes from logs
- `keycloak_database_connectivity` - Database error patterns from logs
- `keycloak_error_rate` - Error log rate analysis

**Specific Alerts Disabled:**
- `KeycloakHighAuthenticationFailureRate`
- `KeycloakCriticalAuthenticationFailures`
- `KeycloakAccountLockout` (using `|~` operator)
- `KeycloakAdminConfigurationChange`
- `KeycloakUserManagementEvent`
- `KeycloakDatabaseConnectionErrors` (using `|~` operator)
- `KeycloakHighErrorRate`

### 2. Preserved Metric-Based Alerts

These alerts use proper PromQL and remain active:

✅ **KeycloakServiceDown** - Monitors `up{job="keycloak"}` metric  
✅ **KeycloakHighMemoryUsage** - Monitors container memory metrics  
✅ **KeycloakHighCPUUsage** - Monitors container CPU metrics

### 3. Created Backup File

All disabled log-based alerts were preserved in:
```
docker/prometheus/alerts/keycloak-alerts-logql.yml.disabled
```

This file includes:
- All original LogQL alert definitions
- Implementation instructions for Loki Ruler
- Configuration guidance

### 4. Updated Documentation

Added comprehensive notes in `keycloak-alerts.yml` explaining:
- Why alerts were disabled
- Difference between PromQL and LogQL
- How to implement log-based alerts with Loki Ruler
- Reference to `README-LOG-BASED-ALERTS.md`

## Verification

### Before Fix
```bash
$ docker logs ai_infra_prometheus 2>&1 | grep ERROR
time=2025-12-06T17:46:53.413Z level=ERROR source=main.go:662 
  msg="Error loading rule file patterns from config"
  err="parse rules from file... could not parse expression: unexpected character: '|'"
```

### After Fix
```bash
$ docker logs ai_infra_prometheus 2>&1 | grep "rule manager"
time=2025-12-06T17:49:51.708Z level=INFO source=manager.go:190 
  msg="Starting rule manager..." component="rule manager"

time=2025-12-06T17:50:23.433Z level=DEBUG source=group.go:742 
  msg="'for' state restoration completed" component="rule manager" 
  file=/etc/prometheus/alerts/keycloak-alerts.yml 
  group=keycloak_service_health
```

✅ **No parse errors**  
✅ **Rule manager started successfully**  
✅ **Keycloak alerts loaded**

## Files Modified

1. **docker/prometheus/alerts/keycloak-alerts.yml**
   - Removed all LogQL-based alert rules
   - Added comprehensive documentation
   - Kept only PromQL metric-based alerts

2. **docker/prometheus/alerts/keycloak-alerts-logql.yml.disabled** (NEW)
   - Preserved all disabled log-based alerts
   - Added implementation instructions

## Current Alert Status

### Active (Prometheus)
- ✅ Keycloak service health monitoring (3 alerts)
  - Service down detection
  - Memory usage monitoring
  - CPU usage monitoring

### Disabled (Require Loki Ruler)
- ⏸️ Authentication security monitoring (3 alerts)
- ⏸️ Admin events monitoring (2 alerts)
- ⏸️ Database connectivity monitoring (1 alert)
- ⏸️ Error rate monitoring (1 alert)

**Total:** 3 active alerts, 7 disabled alerts

## Future Implementation: Enabling Log-Based Alerts

To enable the disabled log-based alerts, implement **Loki Ruler**:

### Step 1: Configure Loki Ruler

Edit `docker/loki/loki.yml`:

```yaml
ruler:
  storage:
    type: local
    local:
      directory: /loki/rules
  rule_path: /tmp/loki/rules-temp
  alertmanager_url: http://alertmanager:9093
  ring:
    kvstore:
      store: inmemory
  enable_api: true
  enable_alertmanager_v2: true
```

### Step 2: Create Rules Directory

```bash
mkdir -p docker/loki/rules
```

### Step 3: Move Alert Definitions

```bash
mv docker/prometheus/alerts/keycloak-alerts-logql.yml.disabled \
   docker/loki/rules/keycloak-alerts.yml
```

### Step 4: Update docker-compose.yml

```yaml
loki:
  volumes:
    - ./docker/loki/loki.yml:/etc/loki/local-config.yaml:ro
    - ./docker/loki/rules:/loki/rules:ro  # Add this
    - loki-data:/loki
```

### Step 5: Restart Loki

```bash
docker-compose restart loki
```

### Step 6: Verify

```bash
# Check if rules are loaded
curl http://localhost:3100/loki/api/v1/rules

# Check active alerts
curl http://localhost:3100/prometheus/api/v1/alerts
```

## Best Practices Applied

### Separation of Concerns
✅ **Metrics-based alerts** → Prometheus (time-series data)  
✅ **Log-based alerts** → Loki Ruler (log pattern matching)

### Clear Documentation
✅ Inline comments explaining why alerts were disabled  
✅ Reference to implementation guide  
✅ Preserved original alert definitions for future use

### Graceful Degradation
✅ Core service health monitoring remains active  
✅ No service disruption during fix  
✅ Path forward for full monitoring implementation

## Impact Assessment

### Immediate Impact (Positive)
- ✅ Prometheus starts successfully
- ✅ No configuration errors
- ✅ Core Keycloak health monitoring active
- ✅ System stability restored

### Temporary Limitation
- ⚠️ Authentication failure pattern detection disabled
- ⚠️ Admin event monitoring disabled
- ⚠️ Database error pattern detection disabled
- ⚠️ Log-based error rate analysis disabled

### Mitigation
- Manual log review still available via Grafana/Loki UI
- Core metrics-based monitoring active
- Clear path to re-enable via Loki Ruler

## Related Documentation

- `docker/prometheus/alerts/README-LOG-BASED-ALERTS.md` - Comprehensive guide on LogQL vs PromQL
- `docker/prometheus/alerts/keycloak-alerts-logql.yml.disabled` - Preserved alert definitions
- `docker/prometheus/VALIDATION-CHECKLIST.md` - Prometheus validation procedures

## Testing Performed

1. ✅ Prometheus restart successful
2. ✅ Configuration validation passed
3. ✅ Rule manager initialization successful
4. ✅ No parse errors in logs
5. ✅ Keycloak alerts group loaded
6. ✅ Metric-based alerts functional

## Lessons Learned

### Query Language Selection
- Always verify which query language is appropriate for the data source
- LogQL for logs (Loki)
- PromQL for metrics (Prometheus)
- Don't mix them in the same alert file

### Alert Architecture
- Use the right tool for the job:
  - **Prometheus**: Resource metrics, application metrics, performance data
  - **Loki Ruler**: Log patterns, audit events, text-based analysis

### Testing Strategy
- Validate alert syntax before deployment
- Use separate disabled files for incompatible alerts
- Keep clear migration paths for future enhancements

## Architectural Recommendation

For production deployment, implement a **hybrid monitoring approach**:

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│ Prometheus  │────▶│ Alertmanager │────▶│ Notifications  │
│ (Metrics)   │     │              │     │ (Email, Slack) │
└─────────────┘     └──────────────┘     └────────────────┘
                           ▲
                           │
┌─────────────┐           │
│ Loki Ruler  │───────────┘
│ (Logs)      │
└─────────────┘
```

**Benefits:**
- Comprehensive monitoring coverage
- Proper separation of concerns
- Centralized alert management
- Best practice observability architecture

---

## Summary

**Problem:** LogQL syntax in Prometheus alert rules causing parse errors  
**Root Cause:** Wrong query language for the monitoring system  
**Solution:** Disabled log-based alerts, preserved metric-based alerts  
**Status:** ✅ Resolved - Prometheus operational with 3 active alerts  
**Next Steps:** Implement Loki Ruler for comprehensive log-based monitoring


