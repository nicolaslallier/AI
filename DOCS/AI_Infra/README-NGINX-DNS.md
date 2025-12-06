# Nginx DNS Resolution Fix

## Problem Description

Nginx was failing to start with the error:
```
nginx: [emerg] host not found in upstream "loki:3100" in /etc/nginx/nginx.conf:47
```

This is a common issue in Docker environments where Nginx attempts to resolve upstream host names at startup time, but some services haven't started yet or DNS resolution fails temporarily.

## Root Cause

By default, when Nginx encounters an `upstream` block or a static `proxy_pass` directive with a hostname, it resolves the DNS entry **at startup time only**. This creates a tight coupling where:

1. All upstream services must be running and resolvable before Nginx starts
2. If any service is temporarily unavailable, Nginx fails to start
3. DNS changes during runtime are not picked up without reloading Nginx

This violates the principles of:
- **Graceful Degradation**: Services should start independently
- **Service Resilience**: One service's unavailability shouldn't prevent others from starting
- **Loose Coupling**: Services should not have hard runtime dependencies on each other's availability

## Solution Implemented

We implemented a two-part solution following Nginx best practices for Docker environments:

### 1. Added Docker DNS Resolver

```nginx
# DNS resolver for Docker - enables runtime DNS resolution
# Using Docker's internal DNS server (127.0.0.11)
# valid=10s - cache DNS results for 10 seconds
# ipv6=off - disable IPv6 resolution to avoid potential issues
resolver 127.0.0.11 valid=10s ipv6=off;
```

**Explanation:**
- `127.0.0.11` - Docker's internal DNS server that resolves container names
- `valid=10s` - Cache DNS results for 10 seconds to balance performance vs. freshness
- `ipv6=off` - Disable IPv6 to avoid potential resolution issues in IPv4-only Docker networks

### 2. Converted Static Upstreams to Dynamic Variables

**Before (Static Resolution - WRONG):**
```nginx
upstream loki {
    server loki:3100;
}

location /monitoring/loki/ {
    proxy_pass http://loki;
}
```

**After (Dynamic Resolution - CORRECT):**
```nginx
location /monitoring/loki/ {
    # Use variable to force runtime DNS resolution
    set $loki_upstream http://loki:3100;
    proxy_pass $loki_upstream;
}
```

**Why this works:**
- When `proxy_pass` uses a variable instead of a static upstream name, Nginx performs DNS resolution **at request time** rather than at startup
- This allows Nginx to start successfully even if upstream services aren't ready yet
- DNS changes are picked up automatically on each request (subject to the resolver cache)

### 3. Relaxed Docker Compose Dependencies

**Before:**
```yaml
depends_on:
  - frontend
  - grafana
  - prometheus
  - tempo
  - loki
  - pgadmin
```

**After:**
```yaml
# Removed hard dependencies to allow Nginx to start even if services are not ready
# Runtime DNS resolution in nginx.conf handles service discovery dynamically
depends_on:
  - frontend
```

**Rationale:**
- Only keeping the dependency on `frontend` as it's the core application
- Monitoring services (Grafana, Prometheus, Tempo, Loki) are optional for application functionality
- Nginx can now start and serve the frontend even if monitoring stack is not ready
- When monitoring services come online, they become accessible automatically

## Architectural Benefits

### 1. **Improved Service Independence**
- Services can start in any order
- Partial system startup is possible
- No cascading startup failures

### 2. **Better Resilience**
- Transient DNS issues don't prevent Nginx from starting
- Services can restart independently without affecting Nginx
- Graceful handling of temporary service unavailability

### 3. **Dynamic Service Discovery**
- New service instances are discovered automatically
- DNS changes propagate within the cache timeout (10s)
- Supports dynamic scaling scenarios

### 4. **Aligned with Microservices Principles**
- Loose coupling between services
- Each service has independent lifecycle
- Failure isolation (one service down doesn't prevent others from starting)

## Performance Considerations

### DNS Caching
- **Cache Duration**: 10 seconds (`valid=10s`)
- **Trade-off**: Balance between DNS query overhead and service discovery freshness
- **Impact**: Minimal - DNS queries are only made when cache expires

### Request Overhead
- **First Request**: Performs DNS lookup (cached for 10s)
- **Subsequent Requests**: Uses cached DNS result
- **Overhead**: Negligible - modern DNS resolution is extremely fast

### Memory Usage
- **Resolver**: Minimal memory footprint
- **Variables**: No significant memory overhead
- **Overall**: Impact is negligible compared to static upstream approach

## Testing & Validation

### Test 1: Start with Missing Services
```bash
# Start only Nginx and Frontend
docker-compose up -d nginx frontend

# Verify Nginx started successfully
docker ps | grep nginx

# Expected: Nginx is running and healthy
```

### Test 2: Start Remaining Services
```bash
# Start monitoring stack
docker-compose up -d grafana prometheus tempo loki

# Access monitoring endpoints
curl http://localhost/monitoring/grafana/
curl http://localhost/monitoring/prometheus/
curl http://localhost/monitoring/tempo/
curl http://localhost/monitoring/loki/

# Expected: All endpoints become accessible
```

### Test 3: Restart Individual Services
```bash
# Restart Loki
docker-compose restart loki

# Nginx should continue serving other services
curl http://localhost/monitoring/grafana/

# Loki becomes available again after restart
sleep 15  # Allow 10s DNS cache + 5s startup
curl http://localhost/monitoring/loki/

# Expected: No Nginx restart needed, Loki automatically available
```

### Test 4: DNS Cache Validation
```bash
# Monitor Nginx error logs
docker logs -f ai_infra_nginx

# Restart a backend service
docker-compose restart prometheus

# Make requests within 10 seconds
for i in {1..5}; do 
  curl -s http://localhost/monitoring/prometheus/ > /dev/null
  echo "Request $i completed"
  sleep 2
done

# Expected: Some requests may fail during restart, but no Nginx errors
```

## Troubleshooting

### Issue: 502 Bad Gateway for a specific service
**Cause**: Backend service is not running or not healthy
**Solution**: 
```bash
# Check service status
docker-compose ps

# Check service logs
docker-compose logs [service-name]

# Restart the specific service
docker-compose restart [service-name]
```

### Issue: All services return 502
**Cause**: DNS resolution not working or wrong resolver configured
**Solution**:
```bash
# Verify Docker DNS server
docker exec ai_infra_nginx nslookup loki

# Should resolve to internal Docker IP (172.x.x.x)
```

### Issue: Intermittent 502 errors
**Cause**: Service is restarting or DNS cache timeout during restart
**Solution**: This is expected behavior during service restarts. Errors clear within DNS cache timeout (10s).

### Issue: Changes to nginx.conf not taking effect
**Cause**: Configuration not reloaded
**Solution**:
```bash
# Reload Nginx configuration
docker-compose restart nginx

# Or, for zero-downtime reload (if nginx is running)
docker exec ai_infra_nginx nginx -s reload
```

## Monitoring & Observability

### DNS Resolution Metrics
Monitor these in Nginx access logs:
- Response times to different upstream services
- 502 error rates per service
- Pattern of errors during service restarts

### Health Checks
Each service has its own health check:
```bash
# Check all service health
docker-compose ps

# Look for "healthy" status
```

### Grafana Dashboard Recommendations
Create dashboards to monitor:
1. **Nginx Response Codes by Upstream**: Track 502 errors per service
2. **Upstream Response Times**: Detect slow or unavailable services
3. **Service Availability**: Aggregate health check status
4. **DNS Resolution Failures**: Monitor DNS-related errors in logs

## References

### Nginx Documentation
- [Nginx Resolver Directive](http://nginx.org/en/docs/http/ngx_http_core_module.html#resolver)
- [Nginx proxy_pass Variables](http://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_pass)
- [Dynamic DNS Resolution in Nginx](https://www.nginx.com/blog/dns-service-discovery-nginx-plus/)

### Docker Networking
- [Docker DNS Resolution](https://docs.docker.com/config/containers/container-networking/#dns-services)
- [Docker Internal DNS Server](https://docs.docker.com/network/drivers/bridge/#use-the-default-bridge-network)

### Best Practices
- [Microservices Communication Patterns](https://microservices.io/patterns/communication-style/messaging.html)
- [Service Mesh Patterns](https://www.nginx.com/blog/microservices-reference-architecture-nginx-service-mesh/)
- [Graceful Degradation in Distributed Systems](https://martinfowler.com/articles/microservices.html)

## Related Configuration Files

- `/docker/nginx/nginx.conf` - Main Nginx configuration with DNS resolver
- `/docker-compose.yml` - Service orchestration with relaxed dependencies
- `/docker/prometheus/prometheus.yml` - Prometheus monitoring configuration
- `/docker/grafana/provisioning/datasources/datasources.yml` - Grafana data sources

## Change Log

### 2024-12-06 - Initial DNS Resolution Fix
- Added Docker DNS resolver (127.0.0.11) to nginx.conf
- Converted all static upstream blocks to dynamic variable-based proxy_pass
- Relaxed docker-compose depends_on to allow independent service startup
- Added start_period to Nginx health check to allow graceful startup
- Documented solution and architectural benefits

## Future Improvements

### Short Term
1. **Implement Circuit Breakers**: Add Nginx error handling to fast-fail on unavailable services
2. **Enhanced Logging**: Add upstream response time logging for better diagnostics
3. **Custom Error Pages**: Create friendly 502/503 pages for unavailable services

### Medium Term
1. **Service Mesh**: Consider implementing a service mesh (Istio, Linkerd) for advanced traffic management
2. **Health Check Proxying**: Proxy upstream health checks through Nginx for unified monitoring
3. **Load Balancing**: Add multiple instances of services with Nginx load balancing

### Long Term
1. **External Service Discovery**: Integrate with Consul or etcd for distributed service discovery
2. **API Gateway**: Evolve Nginx into a full API gateway with rate limiting, auth, etc.
3. **Observability Integration**: Full OpenTelemetry integration for distributed tracing

