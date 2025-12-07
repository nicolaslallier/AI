# Multi-Repository Setup Guide

## Overview

The AI infrastructure project is now organized as a multi-repository architecture with separate repositories for different concerns:

```
AI_Infra/          # Infrastructure & orchestration (this repo)
AI_Front/          # Frontend Vue.js application
AI_Middle/         # Middleware services (auth, gateway, aggregation)
AI_Backend/        # Backend workers (Celery, data processing)
```

## Repository Structure

### AI_Infra (Infrastructure)
**Purpose**: Core infrastructure services and orchestration

**Contains**:
- Nginx reverse proxy configuration
- Monitoring stack (Prometheus, Grafana, Loki, Tempo)
- PostgreSQL database
- Keycloak authentication
- pgAdmin database management
- RabbitMQ message broker
- Redis cache
- Docker Compose orchestration
- Integration tests
- Makefile for managing all services

**Port Bindings**:
- 80: Nginx (main entry point)
- 5432: PostgreSQL (internal)
- 15672: RabbitMQ Management UI
- 6379: Redis (internal)

### AI_Front (Frontend)
**Purpose**: User-facing web application

**Technology**: Vue 3 + TypeScript + Vite

**Contains**:
- SPA with authentication integration
- Keycloak-based authentication
- UI for monitoring tools
- Feature modules (counter, console hub, etc.)
- Playwright E2E tests
- Nginx for serving static assets

**Build**: Multi-stage Docker build with Nginx
**Development**: Hot-reload dev server on port 8080

### AI_Middle (Middleware)
**Purpose**: Business logic and API layer

**Technology**: Python + FastAPI + Clean Architecture

**Contains**:
- **Auth Service** (port 8001): User authentication, JWT tokens
- **Gateway Service** (port 8000): API gateway with circuit breaker
- **Aggregation Service** (port 8002): Data aggregation
- Shared domain models
- PostgreSQL for user data
- Alembic migrations

**Architecture**: Hexagonal/Clean Architecture with ports & adapters

### AI_Backend (Backend)
**Purpose**: Asynchronous processing and background tasks

**Technology**: Python + Celery + Redis

**Contains**:
- **Celery Workers**: Process background jobs
- **Celery Beat**: Task scheduler
- **Email Processor**: Email handling service
- **Payment Processor**: Payment processing
- **Data Sync Worker**: Data synchronization
- RabbitMQ as message broker
- Redis as result backend
- Prometheus metrics integration

## Directory Layout

Expected directory structure on your local machine:

```
~/Dev Nick/
├── AI/                    # Documentation and shared resources
│   ├── DOCS/
│   └── Analysis/
├── AI_Infra/             # This repository
├── AI_Front/             # Frontend repository
├── AI_Middle/            # Middleware repository
└── AI_Backend/           # Backend repository
```

## Initial Setup

### 1. Clone All Repositories

```bash
cd ~/Dev\ Nick/

# Infrastructure (if not already cloned)
git clone <AI_Infra_repo_url> AI_Infra

# Frontend
git clone <AI_Front_repo_url> AI_Front

# Middleware
git clone <AI_Middle_repo_url> AI_Middle

# Backend
git clone <AI_Backend_repo_url> AI_Backend
```

### 2. Setup Infrastructure

```bash
cd AI_Infra
make setup
```

This creates:
- `.env` file
- Required directories
- Executable permissions for scripts

### 3. Build All Services

```bash
# Build everything at once
make all-build

# Or build individually
make frontend-build
make middle-build
make backend-build
```

## Running Services

### Start Everything

```bash
# Start all services (infrastructure + applications)
make all-up

# Check status
make all-ps

# View logs
make all-logs
```

### Start Services Individually

```bash
# Infrastructure only (monitoring, databases, nginx)
make up

# Middleware services
make middle-up

# Backend workers
make backend-up

# Frontend development mode (with hot-reload)
make frontend-dev
```

### Stop Services

```bash
# Stop everything
make all-down

# Or individually
make down              # Infrastructure
make middle-down       # Middleware
make backend-down      # Backend
make frontend-dev-down # Frontend dev server
```

## Development Workflow

### Working on Frontend

```bash
# Install dependencies
make frontend-install

# Start dev server with hot-reload
make frontend-dev

# Run tests
make frontend-test

# Validate code (lint, format, type-check)
make frontend-validate

# Build production image
make frontend-build
```

Frontend dev server: http://localhost:8080

### Working on Middleware

```bash
# Start middleware services
make middle-up

# View logs
make middle-logs

# Run database migrations
make middle-migrate

# Run tests
make middle-test

# Open shell in auth service
make middle-auth-shell
```

API endpoints:
- Gateway: http://localhost:8000
- Auth: http://localhost:8001
- Aggregation: http://localhost:8002

### Working on Backend

```bash
# Start backend workers
make backend-up

# View worker logs
make backend-worker-logs

# View scheduler logs
make backend-beat-logs

# Run migrations
make backend-migrate

# Run tests
make backend-test

# Open shell
make backend-shell
```

## Testing

### Run All Tests

```bash
# Run everything (infra, frontend, middleware, backend)
make all-test
```

### Run Specific Test Suites

```bash
# Infrastructure tests
make test              # All infra tests
make test-unit         # Unit tests
make test-integration  # Integration tests
make test-e2e          # E2E tests

# Frontend tests
make frontend-test

# Middleware tests
make middle-test

# Backend tests
make backend-test
```

## Database Management

### Infrastructure Database (PostgreSQL)

```bash
# Open pgAdmin
make pgadmin

# Access PostgreSQL shell
make psql

# Backup database
make db-backup

# Restore database
make db-restore FILE=backups/backup_20231201.sql
```

### Middleware Database

```bash
# Run migrations
make middle-migrate

# Access database shell
cd ../AI_Middle
docker-compose exec postgres psql -U auth_user -d auth_db
```

### Backend Database

```bash
# Run migrations
make backend-migrate

# Access database shell
cd ../AI_Backend
docker-compose exec postgres psql -U celery_user -d celery_db
```

## Monitoring

### Access Monitoring Tools

```bash
# Show all URLs
make urls

# Open specific tools
make dashboard    # Grafana
make metrics      # Prometheus
make tempo        # Tempo (tracing)
make loki         # Loki (logs)
```

### Monitoring Stack URLs

- **Grafana**: http://localhost/monitoring/grafana/ (admin/admin)
- **Prometheus**: http://localhost/monitoring/prometheus/
- **Tempo**: http://localhost/monitoring/tempo/
- **Loki**: http://localhost/monitoring/loki/
- **Keycloak**: http://localhost/auth/ (admin/admin)

## Repository Management

### Check Status of All Repos

```bash
# Show git status
make repos-status

# Show current branches
make repos-branch
```

### Update All Repositories

```bash
# Pull latest changes from all repos
make repos-pull
```

### Manual Updates

```bash
# Update specific repo
cd ~/Dev\ Nick/AI_Front
git pull origin main

# Or use the Makefile from AI_Infra
cd ~/Dev\ Nick/AI_Infra
make frontend-build  # Rebuild after update
```

## Service URLs Reference

### Infrastructure Services (via Nginx)
- **Frontend**: http://localhost/
- **Grafana**: http://localhost/monitoring/grafana/
- **Prometheus**: http://localhost/monitoring/prometheus/
- **Tempo**: http://localhost/monitoring/tempo/
- **Loki**: http://localhost/monitoring/loki/
- **Keycloak**: http://localhost/auth/
- **pgAdmin**: http://localhost/pgadmin/

### Middleware Services (Direct)
- **Gateway API**: http://localhost:8000
- **Auth Service**: http://localhost:8001
- **Aggregation Service**: http://localhost:8002
- **PostgreSQL**: localhost:5433

### Backend Services
- **RabbitMQ Management**: http://localhost:15672 (guest/guest)
- **Redis**: localhost:6379
- **Flower (Celery monitoring)**: http://localhost:5555 (if configured)

## Troubleshooting

### Services Not Starting

```bash
# Check status
make all-ps

# View logs for errors
make all-logs

# Restart services
make all-down
make all-up
```

### Repository Not Found

Make sure all repositories are cloned in the correct location:

```bash
ls -la ~/Dev\ Nick/
# Should show: AI_Infra, AI_Front, AI_Middle, AI_Backend
```

If a repository is missing, update the paths in the Makefile:

```makefile
FRONTEND_DIR := ../AI_Front
MIDDLE_DIR := ../AI_Middle
BACKEND_DIR := ../AI_Backend
```

### Port Conflicts

Check if ports are already in use:

```bash
# Check common ports
lsof -i :80        # Nginx
lsof -i :5432      # PostgreSQL (infra)
lsof -i :5433      # PostgreSQL (middleware)
lsof -i :8000      # Gateway
lsof -i :8001      # Auth service
```

### Docker Issues

```bash
# Clean up everything
make clean-all

# Remove dangling images and volumes
make prune

# Check Docker disk usage
make disk-usage
```

### Database Connection Issues

```bash
# Check if databases are healthy
make health

# View PostgreSQL logs
make logs-postgres

# For middleware database
make middle-logs
```

## Best Practices

### 1. Regular Updates

```bash
# Daily workflow
make repos-pull       # Pull latest code
make all-build        # Rebuild images
make all-up           # Start services
make all-test         # Run tests
```

### 2. Clean Development

```bash
# Before starting work
make clean
make all-build
make all-up

# After work
make all-down
```

### 3. Testing

```bash
# Always run tests before committing
make all-test

# Run specific tests during development
make frontend-test    # While working on frontend
make middle-test      # While working on middleware
make backend-test     # While working on backend
```

### 4. Monitoring

- Keep Grafana open to monitor service health
- Check Prometheus for metrics
- Use Loki/Grafana to view logs
- Monitor RabbitMQ queues for backend tasks

### 5. Database Migrations

```bash
# Always run migrations after pulling updates
make middle-migrate   # Middleware database
make backend-migrate  # Backend database
```

## CI/CD Integration

### Jenkins Pipeline

The infrastructure includes a Jenkinsfile that can orchestrate:

1. Pull latest code from all repositories
2. Build all Docker images
3. Run all test suites
4. Deploy to staging/production

### GitHub Actions

Each repository can have its own GitHub Actions:

- **AI_Front**: Run frontend tests, build Docker image
- **AI_Middle**: Run middleware tests, database migrations
- **AI_Backend**: Run worker tests, validate Celery tasks
- **AI_Infra**: Integration tests, deploy stack

## Migration from Submodules

This setup replaces the previous Git submodule architecture. Benefits:

✅ **Simpler Git workflow** - No submodule commands needed
✅ **Independent development** - Each repo can be worked on separately
✅ **Cleaner history** - No nested commit references
✅ **Better IDE support** - IDEs work better with separate repos
✅ **Flexible deployment** - Services can be deployed independently

## Next Steps

1. **Configure Environment Variables**
   - Edit `.env` files in each repository
   - Set up secrets for production

2. **Set Up CI/CD**
   - Configure Jenkins or GitHub Actions
   - Set up automated deployments

3. **Add Monitoring Alerts**
   - Configure Prometheus alerts
   - Set up notification channels in Grafana

4. **Documentation**
   - Document API endpoints in each service
   - Add architecture decision records (ADRs)

5. **Security**
   - Review and update credentials
   - Configure TLS/SSL certificates
   - Set up proper firewall rules

## Support

For issues or questions:

1. Check service logs: `make all-logs`
2. Review documentation in each repository
3. Check the monitoring dashboards
4. Create an issue in the respective repository

## Useful Commands Reference

```bash
# Setup & Build
make setup                    # Initial setup
make all-build               # Build all services
make all-up                  # Start everything

# Development
make frontend-dev            # Start frontend dev server
make middle-up               # Start middleware
make backend-up              # Start backend workers

# Monitoring
make urls                    # Show all URLs
make dashboard               # Open Grafana
make all-ps                  # Check status

# Testing
make all-test               # Run all tests
make test-e2e               # Run E2E tests

# Maintenance
make repos-pull             # Update all repos
make all-down               # Stop everything
make clean                  # Clean up
```

