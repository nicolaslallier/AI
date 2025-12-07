# Backend Services - Quick Reference

## ✅ Current Status: ALL SERVICES OPERATIONAL

### Active Services
- ✅ **Celery Beat** - Scheduler for periodic tasks
- ✅ **Email Worker** - Handles email processing queue (port 9091)
- ✅ **Payment Worker** - Handles payment processing queue (port 9092)
- ✅ **Data Sync Worker** - Handles data synchronization queue (port 9093)
- 🔴 **Flower** - Monitoring UI (temporarily disabled)

## Quick Commands

### Check Status
```bash
# View all backend service status
docker ps | grep backend

# Check specific worker logs
docker logs ai_backend_email_worker --tail 50
docker logs ai_backend_payment_worker --tail 50
docker logs ai_backend_data_sync_worker --tail 50
docker logs ai_backend_celery_beat --tail 50

# Check worker connectivity
docker exec ai_backend_email_worker celery -A shared.infrastructure.celery_app inspect ping
```

### Control Services
```bash
# Start all backend services
make backend-up

# Stop all backend services
make backend-down

# Restart all backend services
docker-compose restart celery_beat email_worker payment_worker data_sync_worker

# Restart individual worker
docker-compose restart email_worker
```

### Monitor Workers
```bash
# View active tasks
docker exec ai_backend_email_worker celery -A shared.infrastructure.celery_app inspect active

# View worker statistics
docker exec ai_backend_email_worker celery -A shared.infrastructure.celery_app inspect stats

# Check Prometheus metrics
curl http://localhost:9091/metrics  # Email worker
curl http://localhost:9092/metrics  # Payment worker
curl http://localhost:9093/metrics  # Data sync worker
```

### Database Operations
```bash
# Access PostgreSQL
docker exec -it ai_infra_postgres psql -U postgres

# List databases
docker exec ai_infra_postgres psql -U postgres -l

# Connect to ai_backend database
docker exec -it ai_infra_postgres psql -U postgres -d ai_backend
```

## Service Configuration

### Queue Configuration
- **email_processing**: Email worker (concurrency: 4)
- **payment_processing**: Payment worker (concurrency: 4)
- **data_sync**: Data sync worker (concurrency: 2)

### Network Topology
```
Backend Workers
    ↓
Redis (Broker) ← redis://redis:6379/0
    ↓
PostgreSQL (Results) ← postgresql+psycopg://postgres@postgres:5432/ai_backend
```

### Resource Allocation
- Each worker: 0.5 CPU, 512MB RAM
- Celery beat: 0.5 CPU, 256MB RAM
- All services have health checks with 30s start period

## Troubleshooting

### Workers Keep Restarting
✅ **FIXED** - Was caused by incorrect `--queues` syntax

If you encounter this again:
1. Check logs: `docker logs ai_backend_email_worker --tail 100`
2. Verify command syntax in docker-compose.yml
3. Ensure ai_backend database exists
4. Verify Redis and PostgreSQL are healthy

### Database Connection Issues
```bash
# Check if database exists
docker exec ai_infra_postgres psql -U postgres -c "\l" | grep ai_backend

# Create database if missing
docker exec ai_infra_postgres psql -U postgres -c "CREATE DATABASE ai_backend;"
```

### Redis Connection Issues
```bash
# Check Redis status
docker exec ai_infra_redis redis-cli ping

# View Redis info
docker exec ai_infra_redis redis-cli info
```

### Health Check Failures
```bash
# Manual health check
docker exec ai_backend_email_worker celery -A shared.infrastructure.celery_app inspect ping

# Check process running
docker exec ai_backend_email_worker ps aux | grep celery
```

## Environment Variables

All workers share these environment variables:
```yaml
DB_HOST: postgres
DB_PORT: 5432
DB_NAME: ai_backend
DB_USER: postgres
DB_PASSWORD: postgres
REDIS_HOST: redis
REDIS_PORT: 6379
CELERY_BROKER_URL: redis://redis:6379/0
CELERY_RESULT_BACKEND: db+postgresql+psycopg://postgres:postgres@postgres:5432/ai_backend
LOG_LEVEL: INFO
LOG_FORMAT: json
ENVIRONMENT: development
PROMETHEUS_ENABLED: "true"
```

## Next Steps

### Short-term
1. Monitor worker performance for 24 hours
2. Set up Grafana dashboards for Celery metrics
3. Re-enable Flower monitoring UI

### Medium-term
1. Implement database migrations with Alembic
2. Add more task types for different queues
3. Configure alerting for worker failures

### Long-term
1. Implement auto-scaling based on queue depth
2. Add dead letter queue for failed tasks
3. Set up distributed tracing for tasks
4. Implement task result caching

## Support

For issues or questions:
1. Check logs first: `make backend-logs`
2. Review BACKEND_REBOOT_FIX.md for common issues
3. Verify services are healthy: `docker ps | grep backend`
4. Check connectivity: `docker exec ai_backend_email_worker celery -A shared.infrastructure.celery_app inspect ping`

---

**Last Updated**: December 6, 2025  
**System Status**: ✅ Operational  
**Services**: 4/5 running (Flower temporarily disabled)

