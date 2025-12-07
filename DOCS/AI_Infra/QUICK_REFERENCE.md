# Quick Reference - AI Infrastructure

## 🚀 Quick Start

```bash
# 1. Setup (first time)
make setup

# 2. Build all services
make all-build

# 3. Start everything
make all-up

# 4. Check status
make all-ps

# 5. View all service URLs
make urls
```

## 📦 All Services Commands

| Command | Description |
|---------|-------------|
| `make all-build` | Build all Docker images (frontend, middleware, backend) |
| `make all-up` | Start all services |
| `make all-down` | Stop all services |
| `make all-ps` | Show status of all services |
| `make all-logs` | View logs from all services |
| `make all-test` | Run all test suites |

## 🎨 Frontend Commands (AI_Front)

| Command | Description |
|---------|-------------|
| `make frontend-build` | Build frontend Docker image |
| `make frontend-dev` | Start dev server (hot-reload on :8080) |
| `make frontend-dev-down` | Stop dev server |
| `make frontend-install` | Install npm dependencies |
| `make frontend-test` | Run frontend tests |
| `make frontend-validate` | Lint, format, type-check |
| `make frontend-logs` | View frontend logs |
| `make frontend-shell` | Open shell in container |

## ⚙️ Middleware Commands (AI_Middle)

| Command | Description |
|---------|-------------|
| `make middle-build` | Build middleware services |
| `make middle-up` | Start middleware services |
| `make middle-down` | Stop middleware services |
| `make middle-ps` | Show middleware status |
| `make middle-logs` | View all middleware logs |
| `make middle-auth-logs` | View auth service logs |
| `make middle-gateway-logs` | View gateway logs |
| `make middle-aggregation-logs` | View aggregation logs |
| `make middle-auth-shell` | Open shell in auth service |
| `make middle-test` | Run middleware tests |
| `make middle-migrate` | Run database migrations |

## 🔧 Backend Commands (AI_Backend)

| Command | Description |
|---------|-------------|
| `make backend-build` | Build backend services |
| `make backend-up` | Start Celery workers & beat |
| `make backend-down` | Stop backend services |
| `make backend-ps` | Show backend status |
| `make backend-logs` | View all backend logs |
| `make backend-worker-logs` | View Celery worker logs |
| `make backend-beat-logs` | View Celery beat logs |
| `make backend-shell` | Open shell in worker |
| `make backend-test` | Run backend tests |
| `make backend-migrate` | Run database migrations |

## 🏗️ Infrastructure Commands

| Command | Description |
|---------|-------------|
| `make up` | Start infrastructure only |
| `make down` | Stop infrastructure |
| `make ps` | Show infrastructure status |
| `make logs` | View infrastructure logs |
| `make restart` | Restart all infrastructure |
| `make health` | Check service health |
| `make test` | Run infrastructure tests |

## 📊 Monitoring

| Command | Description |
|---------|-------------|
| `make dashboard` | Open Grafana |
| `make metrics` | Open Prometheus |
| `make tempo` | Open Tempo (tracing) |
| `make loki` | Open Loki (logs) |
| `make urls` | Show all service URLs |

## 🗄️ Database

| Command | Description |
|---------|-------------|
| `make pgadmin` | Open pgAdmin |
| `make psql` | Open PostgreSQL shell |
| `make db-backup` | Backup database |
| `make db-restore FILE=backup.sql` | Restore database |
| `make middle-migrate` | Run middleware migrations |
| `make backend-migrate` | Run backend migrations |

## 🔐 Authentication

| Command | Description |
|---------|-------------|
| `make keycloak-admin` | Open Keycloak admin |
| `make keycloak-logs` | View Keycloak logs |
| `make restart-keycloak` | Restart Keycloak |

## 📝 Repository Management

| Command | Description |
|---------|-------------|
| `make repos-status` | Show git status of all repos |
| `make repos-pull` | Pull latest from all repos |
| `make repos-branch` | Show current branch of all repos |

## 🧹 Cleanup

| Command | Description |
|---------|-------------|
| `make clean` | Stop and remove containers |
| `make clean-volumes` | Remove volumes (⚠️ deletes data) |
| `make clean-all` | Complete cleanup |
| `make prune` | Clean Docker system |

## 🌐 Service URLs

### Infrastructure (via Nginx - :80)
- **Frontend**: http://localhost/
- **Grafana**: http://localhost/monitoring/grafana/ (admin/admin)
- **Prometheus**: http://localhost/monitoring/prometheus/
- **Tempo**: http://localhost/monitoring/tempo/
- **Loki**: http://localhost/monitoring/loki/
- **Keycloak**: http://localhost/auth/ (admin/admin)
- **pgAdmin**: http://localhost/pgadmin/ (admin@example.com/admin)

### Middleware (Direct Access)
- **Gateway API**: http://localhost:8000
- **Auth Service**: http://localhost:8001
- **Aggregation**: http://localhost:8002
- **PostgreSQL**: localhost:5433

### Backend
- **RabbitMQ UI**: http://localhost:15672 (guest/guest)
- **Redis**: localhost:6379

## 🔄 Common Workflows

### Daily Development
```bash
make repos-pull      # Update all repos
make all-build       # Rebuild if needed
make all-up          # Start services
make frontend-dev    # Start frontend hot-reload
# ... do your work ...
make all-down        # Stop when done
```

### Working on Frontend Only
```bash
make up              # Start infrastructure
make frontend-dev    # Start with hot-reload
# Edit code, see changes instantly
make frontend-test   # Run tests
make frontend-dev-down
```

### Working on Middleware
```bash
make up              # Start infrastructure
make middle-up       # Start middleware
make middle-logs     # Watch logs
make middle-test     # Run tests
make middle-down
```

### Working on Backend
```bash
make up              # Start infrastructure
make backend-up      # Start workers
make backend-worker-logs  # Watch worker logs
make backend-test    # Run tests
make backend-down
```

### Full Stack Testing
```bash
make all-up          # Start everything
make all-test        # Run all tests
make all-logs        # Check for errors
make all-down
```

### Update Everything
```bash
make all-down        # Stop services
make repos-pull      # Update all repos
make all-build       # Rebuild images
make all-up          # Start services
make all-test        # Verify everything works
```

### Database Work
```bash
make psql            # Infrastructure DB
make middle-migrate  # Run middleware migrations
make backend-migrate # Run backend migrations
make db-backup       # Backup database
```

## 🐛 Troubleshooting

### Check Status
```bash
make all-ps          # All services
make health          # Health checks
```

### View Logs
```bash
make all-logs        # All logs
make logs            # Infrastructure
make middle-logs     # Middleware
make backend-logs    # Backend
```

### Restart Services
```bash
make all-down
make all-up
```

### Clean Start
```bash
make clean           # Remove containers
make all-build       # Rebuild
make all-up          # Start fresh
```

### Check Repositories
```bash
make repos-status    # Git status
make repos-branch    # Current branches
make repos-pull      # Update all
```

## 💡 Tips

1. **Use `make help`** to see all available commands
2. **Use `make urls`** to see all service URLs
3. **Start infrastructure first**: `make up` before other services
4. **Check logs often**: Use `*-logs` commands to debug
5. **Run tests**: Always run `make all-test` before committing
6. **Update regularly**: Use `make repos-pull` to stay current
7. **Monitor health**: Keep `make dashboard` (Grafana) open
8. **Database migrations**: Run after pulling updates

## 📚 Documentation

- **MULTI_REPO_SETUP.md** - Complete setup guide
- **MAKEFILE_UPDATE_SUMMARY.md** - Detailed changes
- **README.md** - Project overview
- Individual repo READMEs for service-specific docs

## 🆘 Need Help?

```bash
make help            # Show all commands
make urls            # Show all URLs
make all-ps          # Check what's running
make all-logs        # See what's happening
```

## 📞 Support

Check logs, monitor dashboards, and refer to documentation in each repository.

