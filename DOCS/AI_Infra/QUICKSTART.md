# Quick Start Guide

Get your AI Infrastructure up and running in 5 minutes!

## Prerequisites Check

Ensure you have:
- ✅ Docker Desktop installed and running
- ✅ At least 8GB RAM available
- ✅ 20GB free disk space

## Step-by-Step Setup

### 1. Configure Environment (30 seconds)

```bash
# Copy environment template
cp .env.example .env

# Edit with your preferred editor (optional for quick start)
# For development, defaults are fine!
# nano .env
```

### 2. Start All Services (2-3 minutes first time)

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Start everything
./scripts/start.sh
```

**What's happening?**
- Docker pulls all required images
- Creates isolated networks
- Starts 12 services
- Runs health checks

### 3. Verify Services (30 seconds)

```bash
# Check all services are running
docker-compose ps

# Should show all services as "Up (healthy)"
```

### 4. Access Your Infrastructure

Open these URLs in your browser:

| Service | URL | Login |
|---------|-----|-------|
| **Frontend App** | http://localhost/ | - |
| **Grafana** (Monitoring) | http://localhost/monitoring/grafana/ | admin / admin |
| **Prometheus** (Metrics) | http://localhost/monitoring/prometheus/ | - |
| **Tempo** (Tracing) | http://localhost/monitoring/tempo/ | - |
| **Loki** (Logs) | http://localhost/monitoring/loki/ | - |
| **RabbitMQ** (Queues) | http://localhost:15672 | rabbitmq / rabbitmq |
| **Python API** | http://localhost:8000 | - |
| **Node.js API** | http://localhost:3001 | - |

### 5. Test the Setup (1 minute)

```bash
# Test PostgreSQL
docker-compose exec postgres psql -U postgres -c "SELECT version();"

# Test Redis
docker-compose exec redis redis-cli ping

# Test Python API health
curl http://localhost:8000/health || echo "Note: Add /health endpoint to your app"

# View logs
./scripts/logs.sh
```

## 🎉 Success! What's Next?

### Build Your First Service

1. **Python Service**:
```bash
# Create your app structure
mkdir -p services/python-service
cd services/python-service

# Create main.py
cat > main.py << 'EOF'
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="AI Infrastructure API")

@app.get("/")
async def root():
    return {"message": "Welcome to AI Infrastructure!"}

@app.get("/health")
async def health():
    return {"status": "healthy"}
EOF

# Restart service
cd ../..
docker-compose restart python-service
```

2. **Test Your API**:
```bash
curl http://localhost:8000
curl http://localhost:8000/docs  # OpenAPI docs
```

### Add Sample Data

```bash
./scripts/seed-data.sh
```

### View Metrics & Logs

```bash
# Real-time logs
./scripts/logs.sh -s python-service

# Check Grafana dashboards
open http://localhost/monitoring/grafana/  # Default: admin/admin

# View frontend application
open http://localhost/
```

## Common Commands

```bash
# Start services
./scripts/start.sh

# Stop services (keeps data)
./scripts/stop.sh

# View logs (all services)
./scripts/logs.sh

# View specific service logs
./scripts/logs.sh -s postgres

# Backup databases
./scripts/backup.sh

# Stop and clean everything
./scripts/stop.sh --clean
```

## Troubleshooting

### Services won't start?

```bash
# Check Docker is running
docker info

# Check for port conflicts
lsof -i :5432,6379,5672,9200,3000

# View service logs
docker-compose logs service-name
```

### Out of memory?

```bash
# Check Docker resources
docker stats

# Increase Docker Desktop memory:
# Docker Desktop → Settings → Resources → Memory
```

### Need to reset everything?

```bash
# WARNING: This deletes all data!
./scripts/stop.sh --clean
./scripts/start.sh --build
```

## Next Steps

1. **Read the Docs**:
   - [README.md](README.md) - Full documentation
   - [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture
   - [ENV_VARIABLES.md](ENV_VARIABLES.md) - Configuration guide
   - [docker/README.md](docker/README.md) - Docker details

2. **Build Your Application**:
   - Add your code to `services/python-service/` or `services/nodejs-service/`
   - Services auto-reload in development mode
   - Check `.cursorrules` for coding standards

3. **Customize**:
   - Modify `docker-compose.yml` for your needs
   - Add services or remove unused ones
   - Adjust resource limits
   - Configure monitoring alerts

4. **Deploy**:
   - Review security settings in `.env`
   - Change all default passwords
   - Set up SSL/TLS certificates
   - Configure backup schedules

## Getting Help

- **Logs**: Always start with `./scripts/logs.sh`
- **Status**: Check `docker-compose ps`
- **Health**: Visit Grafana dashboards
- **Docs**: See [README.md](README.md) for detailed help

## Pro Tips

💡 **Development**:
```bash
# Run in foreground to see all logs
./scripts/start.sh -f

# Start only what you need
./scripts/start.sh -s postgres redis python-service
```

💡 **Monitoring**:
```bash
# Import Grafana dashboards from grafana.com
# Dashboard ID 1860 (Node Exporter Full)
# Dashboard ID 9628 (PostgreSQL Database)
```

💡 **Performance**:
```bash
# Check what's using resources
docker stats

# See disk usage
docker system df
```

## Success Checklist

- ✅ All services show "Up (healthy)"
- ✅ Frontend loads at http://localhost/
- ✅ Can access Grafana at http://localhost/monitoring/grafana/
- ✅ Can access RabbitMQ management at http://localhost:15672
- ✅ Python API responds at http://localhost:8000
- ✅ Grafana shows metrics from all services
- ✅ No errors in `docker-compose logs`

---

**Welcome to your production-ready AI infrastructure! 🚀**

Questions? Check [README.md](README.md) or review the architecture in [ARCHITECTURE.md](ARCHITECTURE.md).

