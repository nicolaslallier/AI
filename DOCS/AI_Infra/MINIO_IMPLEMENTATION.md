# MinIO Object Storage Implementation

## Overview

This document describes the MinIO S3-compatible object storage implementation for the AI Infrastructure project. MinIO provides distributed, high-availability object storage for backups, logs, and application files.

## Architecture

### Distributed Cluster Configuration

The implementation uses a **4-node distributed MinIO cluster** with erasure coding for data redundancy:

- **Nodes**: 4 MinIO servers (minio1, minio2, minio3, minio4)
- **Storage**: Each node has dedicated persistent volume
- **Erasure Coding**: Automatic data protection across nodes
- **High Availability**: Tolerates loss of up to 2 nodes (N/2 for 4-node cluster)
- **Consistency**: Strong consistency for all operations

### Network Architecture

```
                          Internet/Users
                                |
                                v
                          NGINX (Port 80)
                                |
                    +-----------+------------+
                    |                        |
            /storage/ (S3 API)    /minio-console/ (Web UI)
                    |                        |
                    v                        v
        +------------------------+  +------------------+
        |   MinIO Cluster        |  | MinIO Console    |
        |  (4 nodes distributed) |  | (Admin UI)       |
        +------------------------+  +------------------+
                    |
        +-----------+----------+-----------+
        |           |          |           |
     minio1:9000 minio2    minio3      minio4
        |           |          |           |
        v           v          v           v
    [Volume1]   [Volume2]  [Volume3]  [Volume4]
```

### Network Segmentation

- **storage-net** (172.40.0.0/24): Inter-node communication
- **monitoring-net** (172.31.0.0/24): Metrics and logs
- **database-net** (172.23.0.0/24): PostgreSQL backup access

## Components

### 1. MinIO Services

**Location**: `docker-compose.yml`

Four identical MinIO services configured in distributed mode:
- Each exposes S3 API on port 9000
- Each runs admin console on port 9001
- Configured with Keycloak OIDC for SSO
- Prometheus metrics enabled

### 2. NGINX Reverse Proxy

**Location**: `docker/nginx/nginx.conf`

Two main endpoints:
- `/storage/` → MinIO S3 API (load balanced)
- `/minio-console/` → MinIO admin console (WebSocket support)

Features:
- Dynamic DNS resolution for container environments
- Large file support (5GB limit)
- Streaming uploads/downloads (buffering disabled)
- WebSocket support for real-time console updates

### 3. Keycloak Integration

**Location**: `docker/keycloak/realm-export.json`

OIDC client configuration:
- **Client ID**: `minio-console`
- **Type**: Confidential
- **Protocol**: OpenID Connect
- **Scopes**: openid, profile, email
- **Redirect URIs**: `/minio-console/*`

### 4. Monitoring Integration

#### Prometheus

**Location**: `docker/prometheus/prometheus.yml`

Two scrape jobs:
- `minio-cluster`: Cluster-wide metrics
- `minio-nodes`: Per-node metrics

Metrics exposed at `/minio/v2/metrics/cluster` and `/minio/v2/metrics/node`

#### Promtail

**Location**: `docker/promtail/promtail.yml`

Collects JSON logs from all MinIO containers with:
- Automatic log parsing and labeling
- PII redaction (access keys, signatures)
- Operation type tagging (read/write/delete)
- Security event tagging

#### Grafana

**Location**: `docker/grafana/dashboards/minio-overview.json`

Pre-configured dashboard with:
- Cluster health status
- Storage capacity and usage
- Request rate by API operation
- Network bandwidth (upload/download)
- Error rates
- Top buckets by size

## Security

### Authentication & Authorization

1. **Root Account**:
   - Used for initial setup and emergency access
   - Credentials: `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`
   - Should be rotated regularly

2. **Keycloak SSO**:
   - Admin console access via Keycloak
   - Uses OIDC authentication flow
   - Role-based access control

3. **Service Accounts**:
   - Generated for application access
   - IAM policies for least privilege
   - Managed via MinIO Client (mc)

### IAM Policies

**Location**: `docker/minio/policy-templates/`

Three predefined policies:

1. **backup-service-policy.json**:
   - Read/write access to `backups-postgresql` bucket
   - List buckets capability

2. **readonly-policy.json**:
   - Read-only access to specific buckets
   - Used for monitoring and reporting

3. **admin-policy.json**:
   - Full administrative access
   - Assigned to admin users only

### Network Security

- MinIO nodes **not** exposed on public ports
- All access through NGINX reverse proxy
- Internal communication on isolated network
- TLS termination at NGINX layer

### Data Protection

- **Erasure Coding**: Automatic data redundancy
- **Server-Side Encryption**: Available for sensitive buckets
- **Audit Logging**: All operations logged to Loki
- **Retention Policies**: Automated cleanup of old objects

## Usage

### Initial Setup

1. **Start MinIO cluster**:
   ```bash
   docker-compose up -d minio1 minio2 minio3 minio4
   ```

2. **Initialize buckets**:
   ```bash
   ./scripts/minio/init-buckets.sh
   ```

3. **Create service accounts**:
   ```bash
   ./scripts/minio/create-service-account.sh backup-service
   ```

4. **Assign policies**:
   ```bash
   ./scripts/minio/assign-policy.sh <access-key> backup-service-policy
   ```

### Access Points

- **S3 API**: `http://localhost/storage`
- **Admin Console**: `http://localhost/minio-console`
- **Dashboard**: `http://localhost/monitoring/grafana` → "MinIO Overview"

### Bucket Management

**List buckets**:
```bash
./scripts/minio/list-buckets.sh
```

**Create bucket**:
```bash
./scripts/minio/create-bucket.sh <bucket-name> [retention-days]
```

### PostgreSQL Backup Integration

**Manual backup**:
```bash
export MINIO_ACCESS_KEY=<your-key>
export MINIO_SECRET_KEY=<your-secret>
./scripts/backup/postgres-to-minio-backup.sh [database-name]
```

**Restore from backup**:
```bash
export MINIO_ACCESS_KEY=<your-key>
export MINIO_SECRET_KEY=<your-secret>
./scripts/backup/restore-from-minio.sh <backup-filename> [database-name]
```

**Schedule automated backups** (cron example):
```bash
# Daily backup at 2 AM
0 2 * * * /path/to/postgres-to-minio-backup.sh app_db >> /var/log/minio-backup.log 2>&1
```

## Application Integration

### Python (boto3)

```python
import boto3
from botocore.client import Config

s3_client = boto3.client(
    's3',
    endpoint_url='http://localhost/storage',
    aws_access_key_id='YOUR_ACCESS_KEY',
    aws_secret_access_key='YOUR_SECRET_KEY',
    config=Config(signature_version='s3v4'),
    region_name='us-east-1'
)

# Upload file
s3_client.upload_file('local_file.txt', 'bucket-name', 'object-key')

# Download file
s3_client.download_file('bucket-name', 'object-key', 'local_file.txt')
```

### Node.js (aws-sdk)

```javascript
const AWS = require('aws-sdk');

const s3 = new AWS.S3({
    endpoint: 'http://localhost/storage',
    accessKeyId: 'YOUR_ACCESS_KEY',
    secretAccessKey: 'YOUR_SECRET_KEY',
    s3ForcePathStyle: true,
    signatureVersion: 'v4'
});

// Upload file
await s3.putObject({
    Bucket: 'bucket-name',
    Key: 'object-key',
    Body: fileContent
}).promise();

// Download file
const data = await s3.getObject({
    Bucket: 'bucket-name',
    Key: 'object-key'
}).promise();
```

### MinIO Client (mc)

```bash
# Configure alias
mc alias set myalias http://localhost/storage ACCESS_KEY SECRET_KEY

# List buckets
mc ls myalias

# Upload file
mc cp local-file.txt myalias/bucket-name/

# Download file
mc cp myalias/bucket-name/object-key ./local-file.txt

# Mirror directory
mc mirror local-dir/ myalias/bucket-name/prefix/
```

## Monitoring & Observability

### Key Metrics

Available in Grafana "MinIO Overview" dashboard:

- **Cluster Health**:
  - Nodes online/offline
  - Disk status
  - Network connectivity

- **Storage**:
  - Total capacity
  - Used capacity
  - Free capacity
  - Growth rate

- **Performance**:
  - Request rate (GET/PUT/DELETE ops/sec)
  - Bandwidth (upload/download MB/s)
  - Latency percentiles

- **Errors**:
  - 4xx errors (client errors)
  - 5xx errors (server errors)
  - Failed operations

### Log Analysis

Query MinIO logs in Grafana Explore (Loki datasource):

```logql
# All MinIO logs
{source="minio"}

# Failed authentication attempts
{source="minio", security_event="access_denied"}

# Object deletions
{source="minio", operation_type="delete"}

# Errors only
{source="minio", level="error"}

# Slow requests (if duration tracked)
{source="minio"} |~ "duration"
```

### Alerting

Recommended alert rules (add to Prometheus):

```yaml
- alert: MinIONodeDown
  expr: minio_cluster_nodes_online_total < 4
  for: 5m
  annotations:
    summary: "MinIO node is down"

- alert: MinIOHighStorageUsage
  expr: (minio_cluster_capacity_usable_total_bytes - minio_cluster_capacity_usable_free_bytes) / minio_cluster_capacity_usable_total_bytes > 0.85
  for: 10m
  annotations:
    summary: "MinIO storage usage above 85%"

- alert: MinIOHighErrorRate
  expr: rate(minio_s3_requests_errors_total[5m]) > 10
  for: 5m
  annotations:
    summary: "MinIO error rate is high"
```

## Maintenance

### Backup & Disaster Recovery

1. **Bucket Backups**:
   - Use `mc mirror` to replicate buckets
   - Automate with cron jobs
   - Store offsite for disaster recovery

2. **Configuration Backup**:
   - Export IAM policies
   - Document service accounts
   - Save bucket configurations

3. **Testing Recovery**:
   - Regularly test restore procedures
   - Verify backup integrity
   - Document recovery time objectives (RTO)

### Scaling

**Add more nodes** (scale to 8 nodes):
1. Add new services in docker-compose.yml
2. Update command: `http://minio{1...8}/data`
3. Add volumes for new nodes
4. Restart cluster (requires downtime)

**Increase storage**:
- Add more volumes to existing nodes
- Ensure all nodes have equal storage
- MinIO automatically uses new space

### Upgrades

1. **Backup configuration**:
   ```bash
   mc admin config export myalias > minio-config-backup.json
   ```

2. **Update image** in docker-compose.yml:
   ```yaml
   image: minio/minio:RELEASE.2024-XX-XX
   ```

3. **Rolling restart**:
   ```bash
   docker-compose restart minio1
   # Wait for health
   docker-compose restart minio2
   # Continue for remaining nodes
   ```

4. **Verify cluster health**:
   ```bash
   mc admin info myalias
   ```

## Troubleshooting

### Node Won't Start

Check logs:
```bash
docker-compose logs minio1
```

Common issues:
- Insufficient disk space
- Port conflicts
- Network connectivity
- Wrong credentials

### Slow Performance

1. Check disk I/O:
   ```bash
   docker stats
   ```

2. Check network latency:
   ```bash
   mc admin trace myalias
   ```

3. Review metrics in Grafana

### Cannot Access Console

1. Verify Keycloak is running:
   ```bash
   docker-compose ps keycloak
   ```

2. Check client secret is configured:
   ```bash
   # In Keycloak admin console
   ```

3. Verify NGINX routing:
   ```bash
   curl -I http://localhost/minio-console/
   ```

### Backup Failures

1. Check service account permissions:
   ```bash
   mc admin policy info myalias backup-service-policy
   ```

2. Verify bucket exists:
   ```bash
   mc ls myalias/backups-postgresql
   ```

3. Check MinIO logs for errors

## Resources

- **MinIO Documentation**: https://min.io/docs/minio/linux/
- **MinIO Client**: https://min.io/docs/minio/linux/reference/minio-mc.html
- **S3 API Reference**: https://docs.aws.amazon.com/AmazonS3/latest/API/
- **Prometheus Metrics**: https://min.io/docs/minio/linux/operations/monitoring/metrics-and-alerts.html

## Compliance

### Loi 25 (Quebec Privacy Law)

MinIO implementation addresses Loi 25 requirements:

1. **Data Minimization**:
   - Lifecycle policies delete old data automatically
   - PII redaction in logs

2. **Right to Deletion**:
   - Objects can be deleted on request
   - No versioning by default (immediate deletion)

3. **Security Measures**:
   - Encryption available for sensitive data
   - Access controls via IAM policies
   - Audit trail in Loki

4. **Data Retention**:
   - Configurable retention policies per bucket
   - Default 30 days for backups
   - Documented in bucket initialization

## Support

For issues or questions:
1. Check logs: `docker-compose logs minio1-4`
2. Review Grafana dashboard for metrics
3. Search Loki for error events
4. Consult MinIO documentation
5. Create an issue in the project repository

