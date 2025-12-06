# AI Infrastructure - Quick Access Guide

## 🚀 Service URLs

### Main Services
| Service | URL | Credentials |
|---------|-----|-------------|
| **Frontend Application** | http://localhost/ | - |
| **Keycloak Admin Console** | http://localhost/auth/ | admin / admin |
| **Grafana Dashboards** | http://localhost/monitoring/grafana/ | admin / admin |
| **pgAdmin Database UI** | http://localhost/pgadmin/ | admin@example.com / admin OR SSO |

### Monitoring Services (Internal)
| Service | URL | Notes |
|---------|-----|-------|
| **Prometheus** | http://localhost/monitoring/prometheus/ | Metrics & Alerting |
| **Loki** | http://localhost/monitoring/loki/ | Log Aggregation |
| **Tempo** | http://localhost/monitoring/tempo/ | Distributed Tracing |

## 📊 Grafana Dashboards

### Available Dashboards
1. **AI Infrastructure - System Overview**
   - System-wide metrics and health
   - URL: http://localhost/monitoring/grafana/d/ai-infra-overview/

2. **PostgreSQL Overview**
   - Database performance metrics
   - Connection pools, query performance
   - URL: http://localhost/monitoring/grafana/d/postgresql-overview/

3. **PostgreSQL Logs - Comprehensive Monitoring**
   - Database logs and query analysis
   - Slow queries, errors, connections
   - URL: http://localhost/monitoring/grafana/d/postgres-logs/

4. **pgAdmin Audit & Security Logs**
   - Admin access tracking
   - Security events and authentication
   - URL: http://localhost/monitoring/grafana/d/pgadmin-audit/

5. **Keycloak Authentication & Security**
   - SSO authentication events
   - Failed login attempts and brute force detection
   - User management audit trail
   - URL: http://localhost/monitoring/grafana/d/keycloak-dashboard/

## 🔧 Quick Commands

### Start/Stop Services
```bash
# Start all services
make up

# Stop all services
make down

# Restart specific service
make restart-grafana
make restart-prometheus
make restart-postgres
make restart-keycloak
```

### View Logs
```bash
# All services
make logs

# Specific service
make logs-service SERVICE=grafana
make logs-postgres
make logs-pgadmin
make keycloak-logs
```

### Access Services
```bash
# Open Grafana in browser
make dashboard

# Open pgAdmin in browser
make pgadmin

# Open Keycloak Admin Console
make keycloak-admin

# Open Prometheus
make metrics

# Open Loki
make loki
```

### Health Checks
```bash
# Check all services
make health

# Show service status
make ps

# Show resource usage
make stats
```

### Database Operations
```bash
# Open PostgreSQL shell
make psql

# Backup database
make db-backup

# Restore database
make db-restore FILE=backups/backup.sql
```

### Keycloak Operations
```bash
# Validate Keycloak integration
make keycloak-validate

# Open Keycloak shell
make keycloak-shell

# View Keycloak logs
make keycloak-logs

# Restart Keycloak
make restart-keycloak
```

## 📁 Important Directories

### Configuration
```
docker/
├── keycloak/
│   ├── realm-export.json  # Keycloak realm config
│   ├── keycloak.conf      # Keycloak settings
│   └── README.md          # Keycloak docs
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/    # Datasource configs
│   │   └── dashboards/     # Dashboard provisioning
│   └── dashboards/         # Dashboard JSON files
├── prometheus/
│   ├── prometheus.yml      # Prometheus config
│   └── alerts/             # Alert rules
├── loki/
│   └── loki.yml           # Loki config
├── tempo/
│   └── tempo.yml          # Tempo config
├── postgres/
│   ├── postgresql.conf    # PostgreSQL config
│   ├── pg_hba.conf        # Access control
│   └── init/              # Database init scripts
└── pgadmin/
    ├── servers.json       # Server definitions
    └── config_local.py    # pgAdmin config (incl. OAuth2)
```

### Data Volumes
```
volumes/
├── keycloak_data/        # Keycloak data & cache
├── grafana_data/         # Grafana data & plugins
├── prometheus_data/      # Metrics storage
├── loki_data/           # Log storage
├── tempo_data/          # Trace storage
├── postgres_data/       # Database data (incl. keycloak DB)
└── pgadmin_data/        # pgAdmin settings
```

## 🔍 Troubleshooting

### Grafana Not Loading
```bash
# Check Grafana logs
docker logs ai_infra_grafana --tail 50

# Restart Grafana
make restart-grafana

# Force recreate if config changed
docker-compose up -d --force-recreate grafana
```

### Database Connection Issues
```bash
# Check PostgreSQL logs
make logs-postgres

# Verify database is healthy
docker exec ai_infra_postgres pg_isready -U postgres

# Check connections
docker exec ai_infra_postgres psql -U postgres -c "SELECT count(*) FROM pg_stat_activity;"
```

### Prometheus Not Scraping
```bash
# Check Prometheus config
docker exec ai_infra_prometheus cat /etc/prometheus/prometheus.yml

# View targets status
# Open: http://localhost/monitoring/prometheus/targets

# Restart Prometheus
make restart-prometheus
```

### Loki/Promtail Issues
```bash
# Check Promtail logs
docker logs ai_infra_promtail --tail 50

# Verify Loki is receiving logs
curl http://localhost:3100/ready

# Restart logging stack
make restart-loki
docker-compose restart promtail
```

## 🔒 Security Notes

### Default Credentials (CHANGE IN PRODUCTION!)
- **Keycloak Admin**: admin / admin
- **Keycloak Test Users**:
  - admin-dba / ChangeMe123! (DBA role)
  - devops-user / ChangeMe123! (DevOps role)
- **Grafana**: admin / admin
- **pgAdmin Internal**: admin@example.com / admin
- **pgAdmin SSO**: Use Keycloak credentials
- **PostgreSQL**: postgres / postgres

### Reset Passwords
```bash
# Reset Grafana admin password
docker exec ai_infra_grafana grafana cli admin reset-admin-password <new-password>

# Reset PostgreSQL password
docker exec ai_infra_postgres psql -U postgres -c "ALTER USER postgres PASSWORD 'new-password';"
```

## 📊 Metrics & Monitoring

### Prometheus Targets
- **Prometheus**: http://prometheus:9090/metrics
- **Keycloak**: http://keycloak:8080/metrics
- **Loki**: http://loki:3100/metrics
- **Tempo**: http://tempo:3200/metrics
- **PostgreSQL Exporter**: http://postgres-exporter:9187/metrics
- **Promtail**: http://promtail:9080/metrics

### Log Labels (Loki)
```logql
{source="postgres"}                   # PostgreSQL logs
{source="pgadmin"}                    # pgAdmin logs
{source="keycloak"}                   # Keycloak logs
{source="promtail"}                   # Promtail logs
{tier="database"}                     # All database-related logs
{tier="admin_tool"}                   # Admin tool logs
{tier="identity_provider"}            # Authentication logs
{security_event="auth_failure"}       # Failed auth attempts
```

### Common Queries

#### Prometheus
```promql
# CPU usage by container
rate(container_cpu_usage_seconds_total[5m])

# Memory usage
container_memory_usage_bytes

# PostgreSQL connections
pg_stat_database_numbackends

# Slow queries
rate(pg_stat_database_tup_returned[5m]) / rate(pg_stat_database_xact_commit[5m])
```

#### LogQL (Loki)
```logql
# PostgreSQL errors
{source="postgres"} |= "ERROR"

# Slow queries
{source="postgres"} |= "slow query"

# pgAdmin authentication
{source="pgadmin"} |= "authentication"

# Keycloak failed authentications
{source="keycloak", security_event="auth_failure"}

# Keycloak admin actions
{source="keycloak", security_event="admin_action"}

# Connection events
{tier="database"} |= "connection"

# All security events
{security_event!=""}
```

## 🌐 Network Architecture

### Networks
- **frontend-net** (172.50.0.0/24): Frontend + Nginx + pgAdmin + Keycloak
- **monitoring-net** (172.31.0.0/24): All monitoring services + Keycloak
- **database-net** (172.23.0.0/24): PostgreSQL + pgAdmin + Keycloak + Exporter

### Service Discovery
All services use Docker's internal DNS (127.0.0.11) for service discovery. Services can reach each other using their container names (e.g., `http://grafana:3000`).

## 📚 Additional Documentation

- [README.md](./README.md) - Main project documentation
- [KEYCLOAK_INTEGRATION.md](./KEYCLOAK_INTEGRATION.md) - **Keycloak SSO setup & user management**
- [IMPLEMENTATION-SUMMARY.md](./IMPLEMENTATION-SUMMARY.md) - Implementation details
- [GRAFANA-FIX-SUMMARY.md](./GRAFANA-FIX-SUMMARY.md) - Grafana configuration
- [DATABASE_IMPLEMENTATION.md](./DATABASE_IMPLEMENTATION.md) - Database setup
- [docker/README-LOGGING.md](./docker/README-LOGGING.md) - Logging architecture
- [docker/README-NGINX-DNS.md](./docker/README-NGINX-DNS.md) - Nginx configuration
- [docker/keycloak/README.md](./docker/keycloak/README.md) - Keycloak configuration

## 🆘 Getting Help

### Check Service Health
```bash
make health
```

### View All URLs
```bash
make urls
```

### Validate Configuration
```bash
make validate
```

### Clean Restart
```bash
make down
make clean
make up
```

---

**Last Updated**: December 6, 2025
**Status**: All services operational ✅

