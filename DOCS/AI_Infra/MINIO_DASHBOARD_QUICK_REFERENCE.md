# MinIO Dashboard - Quick Reference Guide

## Access

**URL**: http://localhost/monitoring/grafana/d/minio-overview

**Default Credentials**: admin / admin

## Dashboard Sections

### 1. Overview & Health 🏥
**Purpose**: At-a-glance cluster health status

- **Nodes Online**: Should show 4 (green = healthy)
- **Error Rate**: Should be <1% (green)
- **Storage Usage**: Watch for >70% (yellow) or >85% (red)
- **Total Objects**: Current object count across all buckets
- **Instance Health**: Per-node uptime and memory usage
- **Error Timeline**: Spike detection for API errors

### 2. Performance & S3 Requests ⚡
**Purpose**: Request patterns and latency analysis

- **Request Volume**: GET/PUT/DELETE/LIST/HEAD operations per second
- **Request Latency**: P50/P90/P99 latency percentiles
- **Network Bandwidth**: Upload/download traffic
- **Top Buckets**: Most active buckets by request volume

### 3. Capacity & Storage 💾
**Purpose**: Capacity planning and FinOps

- **Storage Capacity**: Usage with 80%/90% threshold lines
- **Storage by Bucket**: Top 20 buckets with size and object count
- **Growth Trends**: Historical storage usage (spot trends)

### 4. Security & Audit 🔒
**Purpose**: Security monitoring and compliance

- **Access Denied**: Count of 403 errors (investigate if >5)
- **Access Denied Timeline**: Which buckets are affected
- **Suspicious Activity**: DELETE/PUT spikes (ransomware detection)
- **Logs Explorer**: Full MinIO logs with filtering

### 5. Distributed Tracing 🔍
**Purpose**: End-to-end request tracking (optional)

- **Recent Traces**: Shows traces touching MinIO (if instrumented)

## Dashboard Variables

Use the dropdowns at the top to filter data:

### $environment
- **Options**: All, development, staging, production
- **Effect**: Filters all panels by environment
- **Default**: All

### $instance  
- **Options**: All, minio1, minio2, minio3, minio4
- **Effect**: Filter by specific node
- **Default**: All

### $bucket
- **Options**: All, [actual bucket names]
- **Effect**: Filter by specific bucket
- **Default**: All

## Common Use Cases

### 🔍 Investigating Errors

1. Check **Error Rate** stat - is it elevated?
2. Look at **Error Timeline** - which APIs are failing?
3. Check **Instance Health** - is a node down?
4. Go to **Logs Explorer** - filter by error level

### 📊 Capacity Planning

1. Check **Storage Usage** stat
2. Look at **Storage Capacity** graph for threshold proximity
3. Review **Storage by Bucket** table - which buckets are growing?
4. Analyze **Growth Trends** - project future capacity needs

### 🚨 Security Investigation

1. Check **Access Denied** stat - unusual spikes?
2. Review **Access Denied Timeline** - which buckets?
3. Check **Suspicious Activity** - mass deletion detected?
4. Use **Logs Explorer** with filters: `{security_event="access_denied"}`

### ⚡ Performance Analysis

1. Check **Request Latency** - are P99 latencies acceptable?
2. Review **Request Volume** - which operations are dominant?
3. Check **Network Bandwidth** - is there saturation?
4. Review **Top Buckets** - where is the load?

## Alert Thresholds

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Storage Usage | 70% | 85% | Add capacity or cleanup |
| Error Rate | 1% | 5% | Investigate errors |
| Nodes Online | 3 | <2 | Check node health |
| Access Denied | 5 | 20 | Security investigation |

## Keyboard Shortcuts (in Grafana)

- `d` + `k` - Toggle kiosk mode (full screen)
- `t` + `z` - Zoom out time range
- `?` - Show all shortcuts
- `Ctrl/Cmd + S` - Save dashboard (if you have edit permissions)

## Troubleshooting

### No Data in Panels

**Symptom**: Panels show "No Data"

**Solutions**:
1. Check if MinIO is running: `docker ps | grep minio`
2. Verify Prometheus is scraping: `make validate-minio-dashboard`
3. Check metric availability: Visit http://localhost/monitoring/prometheus

### Variables Don't Populate

**Symptom**: Dropdowns are empty

**Solutions**:
1. Wait 30 seconds for Prometheus to scrape
2. Check metrics exist: `curl http://localhost/monitoring/prometheus/api/v1/query?query=minio_cluster_nodes_online_total`
3. Restart Grafana: `make restart-grafana`

### Loki Panels Empty

**Symptom**: Security/Audit panels show no data

**Solutions**:
1. Check Promtail is running: `docker ps | grep promtail`
2. Verify MinIO logs are collected: `docker logs ai_infra_promtail | grep minio`
3. Check Loki labels: `curl http://localhost/monitoring/loki/loki/api/v1/labels`

### Dashboard Not Showing

**Symptom**: Can't find dashboard in Grafana

**Solutions**:
1. Wait 30 seconds for auto-provisioning
2. Check provisioning config: `docker logs ai_infra_grafana | grep minio`
3. Manually import: Dashboard → Import → paste JSON from `docker/grafana/dashboards/minio-overview.json`

## Validation

Run the validation script to check everything:

```bash
make validate-minio-dashboard
```

This checks:
- ✓ Prometheus/Loki/Grafana accessibility
- ✓ MinIO metrics availability
- ✓ Loki log labels
- ✓ Dashboard variable data sources
- ✓ Dashboard exists in Grafana

## Related Commands

```bash
# View MinIO logs
make minio-logs

# Restart Grafana (if dashboard doesn't load)
make restart-grafana

# Check all service status
make all-ps

# View full stack logs
make all-logs

# Open Grafana directly
make grafana

# Validate MinIO setup
make validate-minio-dashboard
```

## Metrics Reference

### Key Prometheus Metrics

```promql
# Cluster Health
minio_cluster_nodes_online_total

# Storage Capacity
minio_cluster_capacity_usable_total_bytes
minio_cluster_capacity_usable_free_bytes

# Bucket Usage
minio_bucket_usage_total_bytes{bucket="mybucket"}
minio_bucket_usage_object_total{bucket="mybucket"}

# Requests
minio_s3_requests_total{api="GetObject"}
minio_s3_requests_errors_total{api="PutObject"}

# Latency
minio_s3_requests_ttfb_seconds_bucket

# Network
minio_s3_traffic_received_bytes
minio_s3_traffic_sent_bytes

# Node Metrics
minio_node_uptime_seconds{node="minio1"}
minio_node_process_resident_memory_bytes{node="minio1"}
```

### Key Loki Queries

```logql
# All MinIO logs
{source="minio"}

# Access denied events
{source="minio", security_event="access_denied"}

# DELETE operations
{source="minio", operation_type="delete"}

# Errors only
{source="minio", log_type="error"}

# Specific bucket
{source="minio", bucket="my-bucket"}

# Specific node
{source="minio", container=~".*minio1.*"}
```

## Dashboard JSON Location

The dashboard is auto-provisioned from:
```
/Users/nicolaslallier/Dev Nick/AI_Infra/docker/grafana/dashboards/minio-overview.json
```

To make changes:
1. Edit the JSON file
2. Wait 30 seconds (auto-reload), OR
3. Run `make restart-grafana` for immediate reload

## Best Practices

### Daily Checks
- [ ] Check **Error Rate** < 1%
- [ ] Verify all **4 nodes online**
- [ ] Review **Storage Usage** < 70%
- [ ] Check **Access Denied** = 0 or very low

### Weekly Reviews
- [ ] Analyze **Top Buckets by Request Volume**
- [ ] Review **Storage Growth Trends**
- [ ] Check **Request Latency** P99 trends
- [ ] Review any **Suspicious Activity** patterns

### Monthly Planning
- [ ] Capacity planning from **Storage Capacity** trends
- [ ] Performance baseline from **Request Latency** averages
- [ ] Security audit from **Access Denied** logs
- [ ] Cost analysis from **Storage by Bucket** table

## Support

For issues or questions:
1. Check `MINIO_DASHBOARD_IMPLEMENTATION.md` for detailed documentation
2. Run `make validate-minio-dashboard` for diagnostics
3. Review MinIO logs: `docker logs ai_infra_minio1`
4. Check Grafana logs: `docker logs ai_infra_grafana`

---

**Dashboard Version**: 2
**Last Updated**: December 6, 2025

