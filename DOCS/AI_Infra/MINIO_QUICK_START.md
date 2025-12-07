# MinIO Quick Start Guide

Get started with MinIO object storage in 5 minutes.

## Prerequisites

- Docker and Docker Compose running
- MinIO cluster deployed (via `docker-compose up`)
- MinIO Client (mc) installed

## Install MinIO Client

### Linux/MacOS
```bash
wget https://dl.min.io/client/mc/release/linux-amd64/mc
chmod +x mc
sudo mv mc /usr/local/bin/
```

### Verify Installation
```bash
mc --version
```

## Step 1: Initialize Buckets

Run the initialization script to create the `backups-postgresql` bucket:

```bash
cd /path/to/AI_Infra
./scripts/minio/init-buckets.sh
```

This creates:
- `backups-postgresql` bucket with 30-day retention policy

## Step 2: Create Service Account

Create a service account for PostgreSQL backups:

```bash
./scripts/minio/create-service-account.sh backup-service
```

**Save the access key and secret key** displayed in the output!

## Step 3: Assign Policy

Assign the backup policy to your service account:

```bash
./scripts/minio/assign-policy.sh <YOUR_ACCESS_KEY> backup-service-policy
```

Replace `<YOUR_ACCESS_KEY>` with the access key from Step 2.

## Step 4: Configure Backup

Set environment variables:

```bash
export MINIO_ACCESS_KEY=<your-access-key>
export MINIO_SECRET_KEY=<your-secret-key>
export POSTGRES_PASSWORD=<your-postgres-password>
```

## Step 5: Run First Backup

Execute a backup:

```bash
./scripts/backup/postgres-to-minio-backup.sh app_db
```

Verify the backup:

```bash
mc ls ai-infra/backups-postgresql
```

## Step 6: Access MinIO Console

1. Open browser: http://localhost/minio-console/
2. Login with Keycloak (or root credentials)
3. Browse buckets and objects

## Common Tasks

### Upload a File (CLI)
```bash
mc alias set myalias http://localhost/storage <access-key> <secret-key>
mc cp myfile.txt myalias/backups-postgresql/
```

### Upload a File (Python)
```python
import boto3

s3 = boto3.client(
    's3',
    endpoint_url='http://localhost/storage',
    aws_access_key_id='YOUR_KEY',
    aws_secret_access_key='YOUR_SECRET'
)

s3.upload_file('local.txt', 'backups-postgresql', 'remote.txt')
```

### List Files
```bash
mc ls myalias/backups-postgresql
```

### Download a File
```bash
mc cp myalias/backups-postgresql/backup.sql.gz ./
```

### Delete a File
```bash
mc rm myalias/backups-postgresql/old-backup.sql.gz
```

## Monitoring

View MinIO metrics in Grafana:
1. Open: http://localhost/monitoring/grafana/
2. Navigate to "MinIO Overview" dashboard
3. Monitor cluster health, storage, and performance

Query logs in Grafana Explore:
```logql
{source="minio"}
```

## Troubleshooting

### Can't connect to MinIO
```bash
# Check MinIO is running
docker-compose ps | grep minio

# Check logs
docker-compose logs minio1
```

### Authentication failed
- Verify credentials are correct
- Check service account exists: `mc admin user list myalias`

### Bucket not found
```bash
# List buckets
mc ls myalias

# Create bucket
./scripts/minio/create-bucket.sh my-bucket
```

## Next Steps

- Read [MINIO_IMPLEMENTATION.md](MINIO_IMPLEMENTATION.md) for detailed architecture
- Read [MINIO_ADMIN_GUIDE.md](MINIO_ADMIN_GUIDE.md) for operations guide
- Configure automated backups with cron
- Set up additional buckets for your applications

## Quick Reference

| Task | Command |
|------|---------|
| List buckets | `mc ls myalias` |
| Create bucket | `./scripts/minio/create-bucket.sh <name>` |
| Upload file | `mc cp file.txt myalias/bucket/` |
| Download file | `mc cp myalias/bucket/file.txt ./` |
| Delete file | `mc rm myalias/bucket/file.txt` |
| Service account | `./scripts/minio/create-service-account.sh <name>` |
| Assign policy | `./scripts/minio/assign-policy.sh <key> <policy>` |
| Backup PostgreSQL | `./scripts/backup/postgres-to-minio-backup.sh` |
| Restore PostgreSQL | `./scripts/backup/restore-from-minio.sh <file>` |

## Support

- Documentation: [MINIO_IMPLEMENTATION.md](MINIO_IMPLEMENTATION.md)
- MinIO Docs: https://min.io/docs/minio/linux/
- Issues: Create an issue in the project repository

