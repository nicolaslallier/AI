# Nginx DNS Resolution Fix - Quick Reference

## Problem
Nginx was failing to start with error:
```
nginx: [emerg] host not found in upstream "loki:3100" in /etc/nginx/nginx.conf:47
```

## Root Cause
Nginx resolved DNS at startup time instead of request time, causing failures when upstream services weren't ready.

## Solution Applied

### 1. Added DNS Resolver (nginx.conf)
```nginx
# DNS resolver for Docker - enables runtime DNS resolution
resolver 127.0.0.11 valid=10s ipv6=off;
```

### 2. Changed All proxy_pass to Use Variables
**Before:**
```nginx
upstream loki {
    server loki:3100;
}

location /monitoring/loki/ {
    proxy_pass http://loki;
}
```

**After:**
```nginx
location /monitoring/loki/ {
    set $loki_upstream http://loki:3100;
    proxy_pass $loki_upstream;
}
```

### 3. Relaxed Docker Compose Dependencies
**Before:** Nginx depended on all services (frontend, grafana, prometheus, tempo, loki, pgadmin)
**After:** Nginx only depends on frontend (core application)

## Benefits
✅ Services can start in any order
✅ Nginx starts even if monitoring services are unavailable
✅ Automatic service discovery when services come online
✅ No manual Nginx reloads needed when services restart
✅ Better resilience and fault isolation

## How It Works
1. **Nginx starts** → Resolver configured for Docker DNS (127.0.0.11)
2. **Request comes in** → Nginx performs DNS lookup for upstream service
3. **DNS result cached** → Cached for 10 seconds (configurable)
4. **Service unavailable** → Returns 502, but Nginx keeps running
5. **Service comes online** → Automatically available within DNS cache timeout

## Testing

### Verify Fix Works
```bash
# Start with only core services
docker-compose up -d nginx frontend postgres

# Nginx should be healthy
docker ps | grep nginx

# Start monitoring services
docker-compose up -d grafana prometheus tempo loki

# Services become accessible automatically
curl http://localhost/monitoring/grafana/
```

### Expected Behavior
- ✅ Nginx starts successfully without all services
- ✅ Frontend accessible immediately
- ✅ Monitoring endpoints return 502 until services start
- ✅ Monitoring endpoints become accessible within ~10 seconds after service starts
- ✅ No Nginx restart needed when services restart

## Files Changed
1. `/docker/nginx/nginx.conf` - Added resolver, converted upstreams to variables
2. `/docker-compose.yml` - Relaxed Nginx dependencies
3. `/docker/README-NGINX-DNS.md` - Comprehensive documentation (NEW)
4. `/README.md` - Updated troubleshooting section

## Quick Commands

**Check service health:**
```bash
docker-compose ps
```

**View Nginx logs:**
```bash
docker logs ai_infra_nginx
```

**Restart Nginx (if needed):**
```bash
docker-compose restart nginx
```

**Test all endpoints:**
```bash
curl http://localhost/
curl http://localhost/monitoring/grafana/
curl http://localhost/monitoring/prometheus/
curl http://localhost/monitoring/tempo/
curl http://localhost/monitoring/loki/
curl http://localhost/pgadmin/
```

## Troubleshooting

**502 Bad Gateway for a service:**
→ Check if service is running: `docker-compose ps [service-name]`
→ Check service logs: `docker-compose logs [service-name]`

**All services return 502:**
→ Check DNS resolution: `docker exec ai_infra_nginx nslookup loki`

**Changes not taking effect:**
→ Reload Nginx: `docker-compose restart nginx`

## Performance Impact
- **DNS Query Overhead**: Negligible (cached for 10s)
- **First Request**: ~1-2ms additional latency for DNS lookup
- **Subsequent Requests**: No overhead (uses cached result)
- **Memory**: No significant impact

## Architecture Alignment
This fix aligns with our Solution Architect principles:

✅ **Scalability**: Services scale independently
✅ **Security**: No changes to security posture
✅ **Maintainability**: Simpler startup logic, fewer dependencies
✅ **DevOps**: Better observability, graceful degradation
✅ **Microservices**: Loose coupling, independent lifecycles

## Related Documentation
- Full documentation: [docker/README-NGINX-DNS.md](docker/README-NGINX-DNS.md)
- Architecture overview: [ARCHITECTURE.md](ARCHITECTURE.md)
- Environment variables: [ENV_VARIABLES.md](ENV_VARIABLES.md)

---
**Last Updated**: 2024-12-06
**Tested**: ✅ Docker 20.10+ / Docker Compose 2.0+

