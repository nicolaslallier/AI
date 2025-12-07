# MinIO Administration Guide

Comprehensive guide for MinIO cluster administration, maintenance, and operations.

## Table of Contents

1. [Daily Operations](#daily-operations)
2. [Monitoring](#monitoring)
3. [Backup & Recovery](#backup--recovery)
4. [Security Management](#security-management)
5. [Performance Tuning](#performance-tuning)
6. [Troubleshooting](#troubleshooting)
7. [Disaster Recovery](#disaster-recovery)

## Daily Operations

### Check Cluster Health

**Via mc (MinIO Client)**:
```bash
mc alias set myalias http://localhost/storage admin changeme123
mc admin info myalias
```

Expected output:
- All 4 nodes online
- Sufficient disk space
- No errors

**Via Grafana Dashboard**:
1. Open http://localhost/monitoring/grafana/
2. Navigate to "MinIO Overview"
3. Check "Nodes Online" panel (should show 4)

### Monitor Storage Usage

```bash
# Check total capacity
mc admin info myalias

# Check per-bucket usage
./scripts/minio/list-buckets.sh

# Check specific bucket
mc du myalias/backups-postgresql
```

### Review Logs

**Via Loki (Grafana Explore)**:
```logql
# All MinIO logs from last hour
{source="minio"} |= ``

# Errors only
{source="minio", level="error"}

# Failed authentication
{source="minio", security_event="access_denied"}
```

**Via Docker logs**:
```bash
# Specific node
docker-compose logs --tail=100 minio1

# All nodes
docker-compose logs --tail=100 minio1 minio2 minio3 minio4
```

### Manage Service Accounts

**List all service accounts**:
```bash
mc admin user svcacct list myalias admin
```

**Create new service account**:
```bash
./scripts/minio/create-service-account.sh <account-name>
```

**Disable service account**:
```bash
mc admin user svcacct disable myalias <access-key>
```

**Enable service account**:
```bash
mc admin user svcacct enable myalias <access-key>
```

**Remove service account**:
```bash
mc admin user svcacct rm myalias <access-key>
```

## Monitoring

### Key Metrics to Watch

**Cluster Health**:
- `minio_cluster_nodes_online_total`: Should equal 4
- `minio_cluster_nodes_offline_total`: Should be 0

**Storage**:
- `minio_cluster_capacity_usable_total_bytes`: Total capacity
- `minio_cluster_capacity_usable_free_bytes`: Free space
- Storage usage > 85%: Warning
- Storage usage > 90%: Critical

**Performance**:
- `minio_s3_requests_total`: Total request rate
- `minio_s3_requests_errors_total`: Error rate
- `minio_s3_traffic_sent_bytes`: Download bandwidth
- `minio_s3_traffic_received_bytes`: Upload bandwidth

**Errors**:
- `minio_s3_requests_4xx_errors_total`: Client errors
- `minio_s3_requests_5xx_errors_total`: Server errors

### Setting Up Alerts

Add to `docker/prometheus/alerts/minio-alerts.yml`:

```yaml
groups:
  - name: minio
    rules:
      - alert: MinIONodeDown
        expr: minio_cluster_nodes_online_total < 4
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "MinIO cluster has node(s) down"
          description: "Only {{ $value }} nodes are online"
      
      - alert: MinIOHighStorageUsage
        expr: >
          (minio_cluster_capacity_usable_total_bytes - minio_cluster_capacity_usable_free_bytes)
          / minio_cluster_capacity_usable_total_bytes > 0.85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "MinIO storage usage is high"
          description: "Storage is {{ $value | humanizePercentage }} full"
      
      - alert: MinIOHighErrorRate
        expr: rate(minio_s3_requests_errors_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "MinIO error rate is high"
          description: "{{ $value }} errors per second"
      
      - alert: MinIOSlowRequests
        expr: >
          histogram_quantile(0.99,
            rate(minio_s3_requests_ttfb_seconds_bucket[5m])
          ) > 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "MinIO requests are slow"
          description: "99th percentile latency is {{ $value }}s"
```

### Log Retention

Configure log retention in Promtail or Loki:
- **Recommended**: 30 days for operational logs
- **Compliance**: 90+ days for audit logs
- **Long-term**: Archive to MinIO bucket for historical analysis

## Backup & Recovery

### Bucket Configuration Backup

**Export all policies**:
```bash
mc admin policy list myalias > minio-policies-backup.txt

for policy in $(mc admin policy list myalias); do
    mc admin policy info myalias $policy > "minio-policy-${policy}.json"
done
```

**Export service accounts** (note: secrets cannot be recovered):
```bash
mc admin user svcacct list myalias admin > minio-service-accounts.txt
```

**Export bucket settings**:
```bash
for bucket in $(mc ls myalias | awk '{print $NF}' | sed 's/\///'); do
    mc ilm export myalias/$bucket > "minio-lifecycle-${bucket}.json"
done
```

### Data Backup

**Option 1: mc mirror (active replication)**:
```bash
# Setup alias for offsite storage
mc alias set offsite <endpoint> <key> <secret>

# Mirror entire MinIO
mc mirror myalias offsite

# Mirror specific bucket
mc mirror myalias/backups-postgresql offsite/backups-postgresql
```

**Option 2: Scheduled sync**:
```bash
#!/bin/bash
# /etc/cron.daily/minio-sync.sh

mc alias set myalias http://localhost/storage <key> <secret>
mc alias set offsite <offsite-endpoint> <key> <secret>

mc mirror --remove --preserve myalias offsite >> /var/log/minio-sync.log 2>&1
```

### Disaster Recovery Procedures

**Scenario 1: Single Node Failure**

1. **Identify failed node**:
   ```bash
   mc admin info myalias
   ```

2. **Check cluster is still operational** (needs 3/4 nodes):
   ```bash
   mc ls myalias
   ```

3. **Restart failed node**:
   ```bash
   docker-compose restart minio<N>
   ```

4. **Verify recovery**:
   ```bash
   mc admin heal myalias
   ```

**Scenario 2: Complete Cluster Loss**

1. **Deploy new cluster**:
   ```bash
   docker-compose up -d minio1 minio2 minio3 minio4
   ```

2. **Initialize buckets**:
   ```bash
   ./scripts/minio/init-buckets.sh
   ```

3. **Restore data from offsite**:
   ```bash
   mc mirror offsite myalias
   ```

4. **Restore policies and accounts**:
   ```bash
   # Re-create policies
   for policy_file in minio-policy-*.json; do
       policy_name=$(basename $policy_file .json | sed 's/minio-policy-//')
       mc admin policy create myalias $policy_name $policy_file
   done
   
   # Re-create service accounts (users must save new credentials)
   # Manual process required as secrets cannot be recovered
   ```

5. **Verify data integrity**:
   ```bash
   mc ls myalias
   mc du myalias
   ```

**Scenario 3: Data Corruption**

1. **Run healing process**:
   ```bash
   mc admin heal myalias
   ```

2. **Check for inconsistencies**:
   ```bash
   mc admin trace myalias
   ```

3. **Restore from backup if healing fails**:
   ```bash
   mc mirror --overwrite offsite/affected-bucket myalias/affected-bucket
   ```

## Security Management

### Rotate Root Credentials

1. **Generate new password**:
   ```bash
   NEW_PASSWORD=$(openssl rand -base64 32)
   ```

2. **Update environment**:
   ```bash
   # Update .env file
   MINIO_ROOT_PASSWORD=$NEW_PASSWORD
   ```

3. **Restart cluster**:
   ```bash
   docker-compose restart minio1 minio2 minio3 minio4
   ```

4. **Update all client configurations**

### Audit Security

**Review access logs**:
```logql
{source="minio"} |= "access"
```

**Check for suspicious activity**:
```logql
# Failed authentication attempts
{source="minio", security_event="access_denied"}

# Unusual deletion activity
{source="minio", operation_type="delete"}

# Bulk operations
{source="minio"} |~ "bulk"
```

**Review service account permissions**:
```bash
for account in $(mc admin user svcacct list myalias admin); do
    echo "Account: $account"
    mc admin user svcacct info myalias $account
    echo "---"
done
```

### Keycloak Integration Maintenance

1. **Verify client configuration**:
   - Login to Keycloak admin console
   - Check `minio-console` client settings
   - Verify redirect URIs are correct

2. **Rotate client secret**:
   - Generate new secret in Keycloak
   - Update `MINIO_IDENTITY_OPENID_CLIENT_SECRET` in environment
   - Restart MinIO cluster

3. **Test SSO login**:
   - Access http://localhost/minio-console/
   - Click "Login with SSO"
   - Verify redirect to Keycloak works
   - Verify successful authentication

## Performance Tuning

### Optimize for Large Files

```yaml
# docker-compose.yml - add to MinIO services
environment:
  # Increase read/write buffers
  MINIO_API_REQUESTS_MAX: "1000"
  MINIO_API_REQUESTS_DEADLINE: "10m"
```

### Optimize for Many Small Files

```yaml
environment:
  # Optimize for high concurrency
  MINIO_API_REQUESTS_MAX: "10000"
  MINIO_API_REQUESTS_DEADLINE: "1m"
```

### Network Optimization

NGINX configuration (already applied):
- Proxy buffering disabled for streaming
- Chunked transfer encoding enabled
- HTTP/1.1 with keep-alive

### Storage Optimization

**Run periodic optimization**:
```bash
# Removes old versions and cleans up
mc admin heal myalias --scan deep
```

**Monitor disk performance**:
```bash
docker stats | grep minio
```

**Check for slow disks**:
```bash
mc admin speedtest myalias
```

## Troubleshooting

### High Memory Usage

**Symptoms**:
- OOM kills in logs
- Slow performance
- Unresponsive nodes

**Solutions**:
1. Check memory limits in docker-compose.yml
2. Increase memory allocation if needed
3. Reduce concurrent connections
4. Review query patterns

### Network Timeouts

**Symptoms**:
- Timeout errors in logs
- Failed uploads/downloads
- Intermittent connectivity

**Solutions**:
1. Check NGINX timeouts (already set to 3600s)
2. Verify network connectivity between nodes
3. Check for MTU mismatches
4. Review firewall rules

### Slow Performance

**Diagnosis**:
```bash
# Check resource usage
docker stats

# Run speedtest
mc admin speedtest myalias

# Check for disk issues
docker exec minio1 df -h

# Review slow queries
mc admin trace myalias --filter slow
```

**Solutions**:
1. Add more nodes to distribute load
2. Upgrade storage to faster disks (SSD)
3. Optimize application patterns
4. Enable caching at application layer

### Split-Brain Recovery

**Rare scenario**: Network partition causes data divergence

1. **Stop all nodes**:
   ```bash
   docker-compose stop minio1 minio2 minio3 minio4
   ```

2. **Identify data source of truth**:
   ```bash
   # Check data consistency
   docker exec minio1 ls -lh /data
   ```

3. **Choose authoritative node set**

4. **Restart cluster with clean slate if necessary**

## Disaster Recovery

### Recovery Time Objectives (RTO)

- **Single node failure**: < 5 minutes (automatic)
- **Complete cluster failure**: < 30 minutes (with backup)
- **Data corruption**: < 1 hour (with offsite backup)

### Recovery Point Objectives (RPO)

- **Continuous replication**: RPO = 0 (no data loss)
- **Daily sync**: RPO = 24 hours
- **Hourly sync**: RPO = 1 hour

### DR Testing Schedule

**Monthly**:
- Test node failure and recovery
- Verify backups are accessible
- Test service account rotation

**Quarterly**:
- Full cluster restore test
- Disaster recovery drill
- Update DR documentation

**Annually**:
- Complete infrastructure rebuild from scratch
- Validate all recovery procedures
- Update and test all runbooks

## Maintenance Windows

### Planned Maintenance

1. **Schedule downtime** (if required)
2. **Notify users**
3. **Create checkpoint backup**
4. **Perform maintenance**
5. **Verify cluster health**
6. **Monitor for issues**

### Rolling Updates (Zero Downtime)

```bash
# Update one node at a time
docker-compose stop minio1
docker-compose pull minio1
docker-compose up -d minio1

# Wait for node to be healthy
sleep 30

# Repeat for other nodes
docker-compose restart minio2
# ... and so on
```

### Post-Maintenance Checklist

- [ ] All 4 nodes online
- [ ] No errors in logs
- [ ] Metrics show normal operation
- [ ] Test upload/download operations
- [ ] Verify monitoring is working
- [ ] Document any changes made

## Capacity Planning

### Current Capacity

```bash
# Get current usage
mc admin info myalias | grep "Capacity"
```

### Growth Projections

Monitor storage growth rate:
```promql
# Weekly growth rate
delta(minio_cluster_capacity_usable_total_bytes - minio_cluster_capacity_usable_free_bytes[1w])
```

### Scaling Plan

**When to scale**:
- Storage usage > 70%: Plan expansion
- Storage usage > 85%: Execute expansion
- Performance degradation: Add nodes

**How to scale**:
1. Plan new node deployment
2. Update docker-compose.yml
3. Add new volumes
4. Restart cluster (requires brief downtime)
5. Verify data rebalancing

## Support & Escalation

### Level 1: Self-Service
- Check this guide
- Review logs in Grafana
- Consult MinIO documentation

### Level 2: Team Support
- Create issue in repository
- Share logs and metrics
- Provide reproduction steps

### Level 3: MinIO Support
- MinIO community forums
- MinIO Slack channel
- Commercial support (if licensed)

## Additional Resources

- [MINIO_IMPLEMENTATION.md](MINIO_IMPLEMENTATION.md) - Architecture details
- [MINIO_QUICK_START.md](MINIO_QUICK_START.md) - Getting started
- MinIO Documentation: https://min.io/docs/minio/linux/
- MinIO Best Practices: https://min.io/docs/minio/linux/operations/concepts.html

