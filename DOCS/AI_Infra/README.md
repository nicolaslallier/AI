# Docker Configuration Guide

This directory contains all Docker-related configurations for the AI Infrastructure project.

## Directory Structure

```
docker/
├── postgres/              # PostgreSQL database
│   ├── init/             # Initialization scripts (run once)
│   └── conf/             # PostgreSQL configuration
├── redis/                # Redis cache
│   └── redis.conf        # Redis configuration
├── rabbitmq/             # RabbitMQ message broker
│   ├── rabbitmq.conf     # RabbitMQ configuration
│   └── definitions.json  # Queue/exchange definitions
├── elasticsearch/        # Elasticsearch search engine
│   └── config/          # Elasticsearch configuration
├── prometheus/           # Prometheus monitoring
│   ├── prometheus.yml    # Main configuration
│   └── alerts/          # Alert rules
├── grafana/              # Grafana dashboards
│   ├── provisioning/     # Auto-provisioning configs
│   └── dashboards/       # Dashboard definitions
├── python-service/       # Python microservice
│   ├── Dockerfile        # Multi-stage build
│   └── pyproject.toml    # Python dependencies
└── nodejs-service/       # Node.js microservice
    ├── Dockerfile        # Multi-stage build
    ├── package.json      # npm dependencies
    └── tsconfig.json     # TypeScript configuration
```

## Service Configurations

### PostgreSQL

**Location**: `docker/postgres/`

**Initialization Scripts** (`init/`):
- Scripts run automatically on first database creation
- Executed in alphabetical order
- `01-init-db.sql`: Creates extensions, schemas, and base tables

**Configuration** (`conf/postgresql.conf`):
- Performance tuning for development
- Connection and memory settings
- Logging configuration
- Autovacuum settings

**Key Settings**:
- Max connections: 200
- Shared buffers: 256MB
- Effective cache size: 1GB
- Log slow queries: >1000ms

**Customization**:
```sql
# Add new initialization scripts in docker/postgres/init/
# Name format: NN-description.sql (e.g., 02-add-indexes.sql)
```

### Redis

**Location**: `docker/redis/`

**Configuration** (`redis.conf`):
- Persistence (RDB + AOF)
- Memory management
- Security settings
- Networking configuration

**Key Settings**:
- Max memory: 512MB
- Eviction policy: allkeys-lru
- Persistence: Both RDB and AOF
- Password authentication required

**Security Notes**:
- Dangerous commands disabled (FLUSHDB, FLUSHALL)
- CONFIG command renamed
- Password required for access

### RabbitMQ

**Location**: `docker/rabbitmq/`

**Configuration** (`rabbitmq.conf`):
- Memory and disk limits
- Management plugin settings
- Network configuration
- Performance tuning

**Definitions** (`definitions.json`):
- Pre-configured users
- Virtual hosts (/, /app, /tasks)
- Exchanges and queues
- Bindings and policies

**Pre-configured Resources**:
- **Virtual Hosts**: /, /app, /tasks
- **Exchanges**: task.exchange (topic), events.exchange (fanout)
- **Queues**: task.default, task.priority, notifications
- **Policies**: HA for all queues, TTL for task queues

**Access Management UI**:
```bash
# Default credentials (change in production!)
URL: http://localhost:15672
User: rabbitmq
Pass: rabbitmq
```

### Elasticsearch

**Location**: `docker/elasticsearch/config/`

**Configuration** (`elasticsearch.yml`):
- Cluster settings
- Network configuration
- Security settings
- Index management

**Logging** (`log4j2.properties`):
- Log levels and formats
- Rolling file policies
- Slow log configuration

**Key Settings**:
- Single-node mode (development)
- JVM heap: 512MB
- Security: X-Pack with basic auth
- Auto-create index: enabled

**JVM Tuning**:
Set in docker-compose.yml:
```yaml
environment:
  - "ES_JAVA_OPTS=-Xms512m -Xmx512m"
```

### Prometheus

**Location**: `docker/prometheus/`

**Configuration** (`prometheus.yml`):
- Scrape configurations
- Alert manager setup
- Global settings
- Service discovery

**Alert Rules** (`alerts/`):
- Instance health alerts
- Resource usage alerts
- Service-specific alerts
- Custom business metrics

**Scrape Targets**:
- System: node-exporter (every 15s)
- PostgreSQL: postgres-exporter (every 15s)
- Redis: redis-exporter (every 15s)
- RabbitMQ: management plugin (every 15s)
- Elasticsearch: metrics endpoint (every 15s)
- Applications: /metrics endpoints (every 30s)

**Adding New Alerts**:
Create YAML file in `docker/prometheus/alerts/`:
```yaml
groups:
  - name: my_alerts
    rules:
      - alert: MyAlert
        expr: my_metric > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "My alert fired"
```

### Grafana

**Location**: `docker/grafana/`

**Provisioning** (`provisioning/`):
- `datasources/`: Auto-configured data sources
- `dashboards/`: Dashboard providers

**Dashboards** (`dashboards/`):
- Pre-built monitoring dashboards
- JSON format for version control
- Auto-loaded on startup

**Pre-configured Data Sources**:
- Prometheus (default)
- PostgreSQL (direct queries)
- Elasticsearch (logs)

**Adding New Dashboard**:
1. Create in Grafana UI
2. Export as JSON
3. Save to `docker/grafana/dashboards/`
4. Restart Grafana

### Python Service

**Location**: `docker/python-service/`

**Dockerfile**: Multi-stage build
- **Base**: Python 3.11 + Poetry setup
- **Dependencies**: Install production packages
- **Development**: Include dev tools, hot-reload
- **Production**: Optimized runtime

**Dependencies** (`pyproject.toml`):
- FastAPI + Uvicorn
- SQLAlchemy + Asyncpg
- Redis, aio-pika (RabbitMQ), Elasticsearch clients
- Pydantic for validation
- Structured logging

**Build Targets**:
```bash
# Development
docker build --target development -t python-service:dev .

# Production
docker build --target production -t python-service:prod .
```

**Application Structure**:
Place your code in `services/python-service/`:
```
services/python-service/
├── main.py              # FastAPI app entry
├── api/                 # API routes
├── models/              # Database models
├── services/            # Business logic
├── schemas/             # Pydantic schemas
└── tests/               # Test suite
```

### Node.js Service

**Location**: `docker/nodejs-service/`

**Dockerfile**: Multi-stage build
- **Base**: Node.js 20 + dumb-init
- **Dependencies**: Production packages
- **Dev Dependencies**: Including dev tools
- **Development**: Hot-reload with nodemon
- **Build**: TypeScript compilation
- **Production**: Optimized runtime

**Dependencies** (`package.json`):
- Express web framework
- PostgreSQL, Redis, AMQP clients
- Elasticsearch client
- Winston for logging
- TypeScript and dev tools

**TypeScript Configuration** (`tsconfig.json`):
- Strict mode enabled
- ES2022 target
- CommonJS modules
- Source maps enabled

**Build Targets**:
```bash
# Development
docker build --target development -t nodejs-service:dev .

# Production
docker build --target production -t nodejs-service:prod .
```

**Application Structure**:
Place your code in `services/nodejs-service/src/`:
```
services/nodejs-service/
├── src/
│   ├── main.ts          # Application entry
│   ├── routes/          # Express routes
│   ├── models/          # Data models
│   ├── services/        # Business logic
│   └── middleware/      # Express middleware
├── tests/               # Test suite
└── dist/                # Compiled output (gitignored)
```

## Building Images

### Build All Services
```bash
docker-compose build
```

### Build Specific Service
```bash
docker-compose build python-service
```

### Build Without Cache
```bash
docker-compose build --no-cache
```

### Build with BuildKit
```bash
DOCKER_BUILDKIT=1 docker-compose build
```

## Image Optimization

### Multi-Stage Builds
All application Dockerfiles use multi-stage builds:
- Reduces final image size
- Separates build and runtime dependencies
- Enables development and production from same Dockerfile

### Layer Caching
Optimize layer caching by ordering Dockerfile commands:
1. Base image and system packages (changes rarely)
2. Dependency files (package.json, pyproject.toml)
3. Install dependencies
4. Application code (changes frequently)

### .dockerignore
Each service directory should have `.dockerignore`:
```
node_modules/
__pycache__/
*.pyc
.git/
.env
*.log
```

## Health Checks

All services include health checks:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 5s
```

### Health Check Endpoints

Application services should expose:
```
GET /health
Response: {"status": "healthy", "checks": {...}}
```

## Resource Limits

Set in docker-compose.yml:

```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 2G
    reservations:
      cpus: '0.5'
      memory: 512M
```

**Guidelines**:
- PostgreSQL: 2 CPU, 2GB RAM
- Redis: 1 CPU, 1GB RAM
- Elasticsearch: 2 CPU, 2GB RAM
- RabbitMQ: 1 CPU, 1GB RAM
- Application services: 2 CPU, 1GB RAM
- Monitoring: 1 CPU, 512MB RAM

## Best Practices

### 1. Security
- ✅ Run as non-root user
- ✅ Minimal base images (Alpine)
- ✅ No secrets in images
- ✅ Regular image updates
- ✅ Scan images for vulnerabilities

### 2. Performance
- ✅ Multi-stage builds
- ✅ Layer caching optimization
- ✅ Health checks for readiness
- ✅ Resource limits set
- ✅ Graceful shutdown handling

### 3. Maintainability
- ✅ One service per container
- ✅ Logs to stdout/stderr
- ✅ Configuration via environment
- ✅ Version pinning for dependencies
- ✅ Documentation for each service

### 4. Development
- ✅ Hot-reload in development
- ✅ Development overrides file
- ✅ Volume mounts for code
- ✅ Debug ports exposed
- ✅ Easy local testing

## Troubleshooting

### Build Issues

**Problem**: Build fails with "no space left on device"
```bash
# Clean up Docker system
docker system prune -a --volumes
```

**Problem**: Dependency installation fails
```bash
# Clear build cache and rebuild
docker-compose build --no-cache service-name
```

### Runtime Issues

**Problem**: Service fails health check
```bash
# Check service logs
docker-compose logs service-name

# Inspect health check
docker inspect --format='{{json .State.Health}}' container-name
```

**Problem**: Out of memory
```bash
# Increase memory limit in docker-compose.yml
deploy:
  resources:
    limits:
      memory: 4G  # Increased from 2G
```

### Performance Issues

**Problem**: Slow builds
- Use BuildKit: `DOCKER_BUILDKIT=1`
- Check layer caching
- Use lighter base images
- Multi-stage builds

**Problem**: Large images
- Use Alpine variants
- Multi-stage builds
- Remove unnecessary files
- Combine RUN commands

## Additional Resources

- [Docker Best Practices](https://docs.docker.com/develop/dev-best-practices/)
- [Docker Compose Reference](https://docs.docker.com/compose/compose-file/)
- [Multi-Stage Builds](https://docs.docker.com/develop/develop-images/multistage-build/)
- [Health Check Best Practices](https://docs.docker.com/engine/reference/builder/#healthcheck)

---

For questions or issues, refer to the main [README.md](../README.md) or [ARCHITECTURE.md](../ARCHITECTURE.md).

