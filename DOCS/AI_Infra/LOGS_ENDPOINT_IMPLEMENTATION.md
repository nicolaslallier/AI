# Logs Endpoint Implementation

## Overview

The `/logs` endpoint has been added to provide quick access to the log aggregation interface. It redirects users to Grafana's Explore view with Loki as the data source, pre-configured to show all container logs from the last hour.

## Access URL

**Primary Endpoint**: http://localhost/logs

## What It Does

When you access http://localhost/logs, you will be automatically redirected to:
```
http://localhost/monitoring/grafana/explore?orgId=1&left={...Loki configuration...}
```

The redirect includes:
- **Data Source**: Loki (log aggregation system)
- **Query**: `{container=~".+"}` (all containers with logs)
- **Time Range**: Last 1 hour (`now-1h` to `now`)

## Implementation Details

### Nginx Configuration

The endpoint was added to `/docker/nginx/nginx.conf`:

```nginx
# Logs convenience endpoint - redirect to Grafana Explore with Loki
location = /logs {
    return 302 /monitoring/grafana/explore?orgId=1&left=%7B%22datasource%22:%22loki%22,%22queries%22:%5B%7B%22refId%22:%22A%22,%22expr%22:%22%7Bcontainer%3D~%5C%22.%2B%5C%22%7D%22%7D%5D,%22range%22:%7B%22from%22:%22now-1h%22,%22to%22:%22now%22%7D%7D;
}

location /logs/ {
    return 302 /monitoring/grafana/explore?orgId=1&left=%7B%22datasource%22:%22loki%22,%22queries%22:%5B%7B%22refId%22:%22A%22,%22expr%22:%22%7Bcontainer%3D~%5C%22.%2B%5C%22%7D%22%7D%5D,%22range%22:%7B%22from%22:%22now-1h%22,%22to%22:%22now%22%7D%7D;
}
```

### URL Parameters Decoded

The URL-encoded JSON parameters decode to:

```json
{
  "datasource": "loki",
  "queries": [
    {
      "refId": "A",
      "expr": "{container=~\".+\"}"
    }
  ],
  "range": {
    "from": "now-1h",
    "to": "now"
  }
}
```

## Usage

### Quick Access to Logs

Simply navigate to http://localhost/logs in your browser to view all container logs.

### Filtering Logs in Grafana

Once redirected to Grafana Explore, you can:

1. **Filter by container**:
   ```
   {container="ai_infra_postgres"}
   {container="ai_infra_keycloak"}
   {container="ai_infra_nginx"}
   ```

2. **Filter by log level**:
   ```
   {container=~".+"} |= "ERROR"
   {container=~".+"} |= "WARN"
   {container=~".+"} |~ "(?i)error|exception|fail"
   ```

3. **Filter by service type** (using labels):
   ```
   {logging_type="database"}
   {logging_type="identity_provider"}
   {logging_source="postgres"}
   ```

4. **Time-based filtering**:
   - Use the time picker in the top-right
   - Common ranges: Last 5m, 15m, 1h, 6h, 24h
   - Or set a custom range

### Advanced Log Queries

**Show only errors from the last 5 minutes**:
```
{container=~".+"} |= "ERROR" 
```

**Show Keycloak authentication logs**:
```
{container="ai_infra_keycloak"} |~ "(?i)login|auth"
```

**Show PostgreSQL slow queries**:
```
{logging_source="postgres"} |~ "duration:.*(ms|s)"
```

**Show Nginx access logs**:
```
{container="ai_infra_nginx"} != "health"
```

## Architecture

```
User Request (http://localhost/logs)
         ↓
    Nginx Reverse Proxy
         ↓ (302 Redirect)
    Grafana Explore View
         ↓ (Query)
    Loki (Log Aggregation)
         ↓ (Logs from)
    Promtail (Log Collection Agent)
         ↓ (Collects from)
    Docker Container Logs
```

## Log Collection Stack

1. **Docker Containers**: All services log to stdout/stderr
2. **Promtail**: Collects logs from Docker containers via `/var/lib/docker/containers`
3. **Loki**: Stores and indexes logs efficiently
4. **Grafana**: Provides the UI for querying and visualizing logs

## Related Services

- **Loki API**: http://localhost/monitoring/loki/ (for direct API access)
- **Grafana Dashboards**: http://localhost/monitoring/grafana/
- **Loki Overview Dashboard**: Available in Grafana under "Loki Overview"

## Log Labels

All logs are automatically labeled by Promtail with:
- `container`: Container name (e.g., `ai_infra_postgres`)
- `compose_service`: Docker Compose service name
- `logging_source`: Custom source label (e.g., `postgres`, `keycloak`)
- `logging_type`: Custom type label (e.g., `database`, `identity_provider`)

These labels can be used for filtering in LogQL queries.

## Troubleshooting

### Logs Not Appearing

1. **Check Promtail is running**:
   ```bash
   docker compose ps promtail
   ```

2. **Verify Promtail can access Docker logs**:
   ```bash
   docker compose logs promtail
   ```

3. **Check Loki is healthy**:
   ```bash
   docker compose ps loki
   ```

4. **Verify logs are being generated**:
   ```bash
   docker compose logs <service_name>
   ```

### Redirect Not Working

1. **Verify Nginx configuration was updated**:
   ```bash
   docker compose exec nginx cat /etc/nginx/nginx.conf | grep -A 2 "location = /logs"
   ```

2. **Restart Nginx**:
   ```bash
   docker compose restart nginx
   ```

3. **Check Nginx logs**:
   ```bash
   docker compose logs nginx
   ```

### Grafana Not Loading

1. **Verify Grafana is running**:
   ```bash
   docker compose ps grafana
   ```

2. **Check Grafana logs**:
   ```bash
   docker compose logs grafana
   ```

3. **Verify Grafana is accessible**:
   ```bash
   curl -I http://localhost/monitoring/grafana/
   ```

## Best Practices

### Log Volume Management

1. **Log Retention**: Loki is configured with 30-day retention (720h)
2. **Log Rotation**: Docker logs are rotated when they reach 10MB (3 files max)
3. **Disk Space**: Monitor Loki volume usage regularly

### Query Performance

1. **Use specific labels**: Filter by `container` or `logging_source` first
2. **Limit time range**: Shorter time ranges query faster
3. **Use line filters**: Use `|=` or `|~` to filter log lines early in the query

### Security

1. **Access Control**: Logs are only accessible via Grafana (which requires authentication)
2. **Sensitive Data**: Ensure sensitive data is not logged (passwords, tokens, etc.)
3. **Audit Logs**: Consider enabling audit logging for compliance requirements

## Future Enhancements

Potential improvements:
1. Add direct Loki UI access (if needed)
2. Create pre-built Grafana dashboards for common log patterns
3. Set up alerting rules for critical errors
4. Implement log-based metrics (e.g., error rate)
5. Add support for log aggregation from external services

## References

- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [LogQL Query Language](https://grafana.com/docs/loki/latest/logql/)
- [Grafana Explore](https://grafana.com/docs/grafana/latest/explore/)
- [Promtail Configuration](https://grafana.com/docs/loki/latest/clients/promtail/)

---

**Last Updated**: December 6, 2025
**Author**: AI Solution Architect
**Status**: ✅ Implemented and Tested

