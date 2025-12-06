# Environment Variables Documentation

This document provides detailed information about all environment variables used in the AI Infrastructure project.

## Table of Contents

- [Environment](#environment)
- [PostgreSQL Database](#postgresql-database)
- [pgAdmin](#pgadmin)
- [Monitoring Stack](#monitoring-stack)
- [Application Services](#application-services)
- [Security Configuration](#security-configuration)
- [CORS Configuration](#cors-configuration)
- [Rate Limiting](#rate-limiting)
- [Backup Configuration](#backup-configuration)

---

## Environment

### ENVIRONMENT
- **Description**: Specifies the current environment
- **Values**: `development`, `staging`, `production`
- **Default**: `development`
- **Required**: Yes

### NODE_ENV
- **Description**: Node.js environment setting
- **Values**: `development`, `production`
- **Default**: `development`
- **Required**: Yes (for Node.js services)

---

## PostgreSQL Database

### POSTGRES_DB
- **Description**: Name of the PostgreSQL database
- **Default**: `app_db`
- **Required**: Yes
- **Format**: Alphanumeric with underscores
- **Security**: This is the main database for the AI Infrastructure project

### POSTGRES_USER
- **Description**: PostgreSQL username
- **Default**: `postgres`
- **Required**: Yes
- **Security**: Change in production, use a dedicated non-superuser account for applications

### POSTGRES_PASSWORD
- **Description**: PostgreSQL password
- **Default**: `postgres`
- **Required**: Yes
- **Security**: Must be strong in production, minimum 16 characters with mixed case, numbers, and special characters

### POSTGRES_PORT
- **Description**: PostgreSQL port number (internal only, not exposed externally)
- **Default**: `5432`
- **Required**: Yes
- **Note**: Only accessible on database-net (172.23.0.0/24)

### DATABASE_URL
- **Description**: Full PostgreSQL connection string
- **Format**: `postgresql://user:password@host:port/database`
- **Example**: `postgresql://postgres:postgres@postgres:5432/app_db`
- **Required**: Yes
- **Note**: Used by application services to connect to PostgreSQL

---

## Keycloak Identity & Access Management

### KEYCLOAK_ADMIN
- **Description**: Keycloak admin console username
- **Default**: `admin`
- **Required**: Yes
- **Security**: Change in production, this is the superadmin account

### KEYCLOAK_ADMIN_PASSWORD
- **Description**: Keycloak admin console password
- **Default**: `admin`
- **Required**: Yes
- **Security**: Must be strong in production, minimum 12 characters with mixed case, numbers, and special characters

### KEYCLOAK_DB_PASSWORD
- **Description**: Password for the keycloak database user in PostgreSQL
- **Default**: `keycloak`
- **Required**: Yes
- **Security**: Should be different from POSTGRES_PASSWORD, minimum 16 characters

### KEYCLOAK_URL
- **Description**: Internal URL for Keycloak service
- **Default**: `http://keycloak:8080`
- **Required**: Yes
- **Note**: Used by other services to connect to Keycloak

### KEYCLOAK_REALM
- **Description**: Keycloak realm name for infrastructure authentication
- **Default**: `infra-admin`
- **Required**: Yes
- **Note**: The realm contains users, roles, and client configurations

### KEYCLOAK_LOG_LEVEL
- **Description**: Logging level for Keycloak
- **Values**: `DEBUG`, `INFO`, `WARNING`, `ERROR`
- **Default**: `INFO`
- **Required**: No

### Access Information
- **Admin Console URL**: `http://localhost/auth/`
- **Authentication**: Keycloak admin credentials (KEYCLOAK_ADMIN/KEYCLOAK_ADMIN_PASSWORD)
- **Realm Management**: Access via Admin Console → Select Realm → infra-admin
- **Network**: Accessible via NGINX reverse proxy, connects to PostgreSQL on database-net

---

## pgAdmin

### PGADMIN_DEFAULT_EMAIL
- **Description**: Default admin email for pgAdmin login
- **Default**: `admin@example.com`
- **Required**: Yes
- **Format**: Valid email address
- **Security**: Change in production to a real administrator email

### PGADMIN_DEFAULT_PASSWORD
- **Description**: Default admin password for pgAdmin login
- **Default**: `admin`
- **Required**: Yes
- **Security**: Must be strong in production, minimum 12 characters

### PGADMIN_CONFIG_SERVER_MODE
- **Description**: Enable server mode for pgAdmin (multi-user support)
- **Default**: `True`
- **Values**: `True`, `False`
- **Required**: Yes

### PGADMIN_CONFIG_MASTER_PASSWORD_REQUIRED
- **Description**: Require master password for saved server passwords
- **Default**: `False`
- **Values**: `True`, `False`
- **Required**: No
- **Note**: Set to `True` in production for additional security

### PGADMIN_AUTHENTICATION_SOURCES
- **Description**: Comma-separated list of authentication sources
- **Values**: `internal`, `oauth2`, `ldap`, `kerberos`
- **Default**: `internal,oauth2`
- **Required**: Yes
- **Note**: Allows both internal pgAdmin auth and Keycloak SSO

### PGADMIN_OAUTH2_NAME
- **Description**: Internal identifier for OAuth2 provider
- **Default**: `Keycloak`
- **Required**: If using OAuth2

### PGADMIN_OAUTH2_DISPLAY_NAME
- **Description**: Display name shown on login button
- **Default**: `Login with Keycloak`
- **Required**: If using OAuth2

### PGADMIN_OAUTH2_CLIENT_ID
- **Description**: OAuth2 client ID registered in Keycloak
- **Default**: `pgadmin-client`
- **Required**: If using OAuth2
- **Note**: Must match client ID in Keycloak realm configuration

### PGADMIN_OAUTH2_CLIENT_SECRET
- **Description**: OAuth2 client secret from Keycloak
- **Default**: (empty - generated by Keycloak)
- **Required**: If using OAuth2
- **Security**: Obtain from Keycloak Admin Console → Clients → pgadmin-client → Credentials

### PGADMIN_OAUTH2_SCOPE
- **Description**: OAuth2 scopes to request
- **Default**: `openid email profile`
- **Required**: If using OAuth2

### PGADMIN_OAUTH2_AUTO_CREATE_USER
- **Description**: Automatically create pgAdmin user on first OAuth2 login
- **Values**: `True`, `False`
- **Default**: `True`
- **Required**: If using OAuth2

### Access Information
- **URL**: `http://localhost/pgadmin/`
- **Authentication**: 
  - **Internal**: pgAdmin email/password (PGADMIN_DEFAULT_EMAIL/PASSWORD)
  - **Keycloak SSO**: Click "Login with Keycloak" button
- **Pre-configured Server**: PostgreSQL server automatically configured in pgAdmin
- **Network**: Only accessible via NGINX reverse proxy on frontend-net
- **Role Mapping**: Keycloak users with ROLE_DBA or ROLE_DEVOPS get admin access

---

## Monitoring Stack

**Note**: All monitoring services are now accessible via nginx reverse proxy at `/monitoring/*` paths:
- Grafana: `http://localhost/monitoring/grafana/`
- Prometheus: `http://localhost/monitoring/prometheus/`
- Tempo: `http://localhost/monitoring/tempo/`
- Loki: `http://localhost/monitoring/loki/`
- pgAdmin: `http://localhost/pgadmin/`

### PROMETHEUS_PORT
- **Description**: Prometheus web UI and API port (internal)
- **Default**: `9090`
- **Required**: Yes
- **Access**: Via nginx at `/monitoring/prometheus/`

### GRAFANA_USER
- **Description**: Grafana admin username
- **Default**: `admin`
- **Required**: Yes

### GRAFANA_PASSWORD
- **Description**: Grafana admin password
- **Default**: `admin`
- **Required**: Yes
- **Security**: Change immediately in production

### GRAFANA_PLUGINS
- **Description**: Comma-separated list of Grafana plugins to install
- **Example**: `grafana-clock-panel,grafana-simple-json-datasource`
- **Required**: No

### TEMPO_HTTP_PORT
- **Description**: Tempo HTTP port (internal)
- **Default**: `3200`
- **Required**: Yes
- **Access**: Via nginx at `/monitoring/tempo/`

### TEMPO_OTLP_GRPC_PORT
- **Description**: Tempo OTLP gRPC receiver port
- **Default**: `4317`
- **Required**: Yes

### TEMPO_OTLP_HTTP_PORT
- **Description**: Tempo OTLP HTTP receiver port
- **Default**: `4318`
- **Required**: Yes

### LOKI_PORT
- **Description**: Loki HTTP API port (internal)
- **Default**: `3100`
- **Required**: Yes
- **Access**: Via nginx at `/monitoring/loki/`

---

## Application Services

### NGINX_PORT
- **Description**: Nginx reverse proxy external port
- **Default**: `80`
- **Required**: Yes
- **Note**: Main entry point for all web traffic

### PYTHON_SERVICE_PORT
- **Description**: Python service HTTP port
- **Default**: `8000`
- **Required**: Yes

### NODEJS_SERVICE_PORT
- **Description**: Node.js service HTTP port
- **Default**: `3001`
- **Required**: Yes

### DEBUG
- **Description**: Enable debug mode for Python service
- **Values**: `true`, `false`
- **Default**: `false`
- **Required**: No

### LOG_LEVEL
- **Description**: Logging level
- **Values**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (Python), `debug`, `info`, `warn`, `error` (Node.js)
- **Default**: `INFO` / `info`
- **Required**: Yes

---

## Security Configuration

### JWT_SECRET
- **Description**: Secret key for JWT token signing
- **Security**: Must be cryptographically random, minimum 32 characters
- **Required**: Yes
- **Generate**: `openssl rand -hex 32`

### JWT_ALGORITHM
- **Description**: Algorithm for JWT signing
- **Default**: `HS256`
- **Values**: `HS256`, `HS384`, `HS512`, `RS256`
- **Required**: Yes

### JWT_EXPIRATION
- **Description**: JWT token expiration time in seconds
- **Default**: `3600` (1 hour)
- **Required**: Yes

---

## CORS Configuration

### CORS_ORIGINS
- **Description**: Comma-separated list of allowed CORS origins
- **Example**: `http://localhost:3000,https://app.example.com`
- **Default**: `http://localhost:3000,http://localhost:8000`
- **Required**: Yes

### CORS_ALLOW_CREDENTIALS
- **Description**: Allow credentials in CORS requests
- **Values**: `true`, `false`
- **Default**: `true`
- **Required**: Yes

---

## Rate Limiting

### RATE_LIMIT_ENABLED
- **Description**: Enable rate limiting
- **Values**: `true`, `false`
- **Default**: `true`
- **Required**: No

### RATE_LIMIT_MAX_REQUESTS
- **Description**: Maximum number of requests per window
- **Default**: `100`
- **Required**: If rate limiting enabled

### RATE_LIMIT_WINDOW_MS
- **Description**: Time window for rate limiting in milliseconds
- **Default**: `60000` (1 minute)
- **Required**: If rate limiting enabled

---

## Backup Configuration

### BACKUP_ENABLED
- **Description**: Enable automatic backups
- **Values**: `true`, `false`
- **Default**: `true`
- **Required**: No

### BACKUP_SCHEDULE
- **Description**: Cron expression for backup schedule
- **Default**: `0 2 * * *` (2 AM daily)
- **Format**: Cron expression
- **Required**: If backups enabled

### BACKUP_RETENTION_DAYS
- **Description**: Number of days to retain backups
- **Default**: `7`
- **Required**: If backups enabled

---

## Best Practices

1. **Never commit `.env` file**: Always use `.env.example` as a template
2. **Use strong passwords**: Minimum 16 characters for production databases, 12 for admin interfaces
3. **Rotate secrets regularly**: Change passwords and keys periodically
4. **Use environment-specific values**: Different secrets for dev/staging/prod
5. **Validate on startup**: Services should validate required environment variables
6. **Document changes**: Update this file when adding new variables
7. **Use secret management**: Consider using HashiCorp Vault, AWS Secrets Manager, etc. for production

---

## Security Warnings

### Production Deployment Checklist

Before deploying to production, ensure you have:

- [ ] Changed all default passwords (PostgreSQL, pgAdmin, Grafana, Keycloak)
- [ ] Generated strong JWT_SECRET (use `openssl rand -hex 32`)
- [ ] Updated PGADMIN_DEFAULT_EMAIL to a real administrator email
- [ ] Set PGADMIN_CONFIG_MASTER_PASSWORD_REQUIRED to `True`
- [ ] Changed KEYCLOAK_ADMIN and KEYCLOAK_ADMIN_PASSWORD
- [ ] Generated and configured PGADMIN_OAUTH2_CLIENT_SECRET from Keycloak
- [ ] Reviewed and configured Keycloak realm users and roles
- [ ] Enabled Keycloak HTTPS/TLS (set KC_HTTPS_ENABLED=true)
- [ ] Configured Keycloak password policies and brute force protection
- [ ] Configured proper CORS_ORIGINS (not wildcard)
- [ ] Enabled HTTPS/TLS with valid certificates for NGINX
- [ ] Reviewed and restricted network access rules
- [ ] Set up proper backup schedule and tested restore
- [ ] Configured log retention policies
- [ ] Tested Keycloak SSO authentication flow end-to-end
- [ ] Set up monitoring alerts for authentication failures

---

## Troubleshooting

### Missing Environment Variables
If a service fails to start due to missing environment variables:
1. Check `.env` file exists in project root
2. Verify all required variables are set
3. Ensure no typos in variable names
4. Check docker-compose reads the `.env` file

### Connection Issues
If services can't connect to PostgreSQL or other services:
1. Verify service names in connection strings match docker-compose service names
2. Check network configuration in docker-compose
3. Ensure ports are not conflicting
4. Verify credentials are correct
5. Check that services are on the correct networks (database-net for DB access)

### Permission Issues
If you encounter permission errors:
1. Ensure volume permissions are correct
2. Check user/group IDs in Dockerfiles
3. Verify file ownership in mounted volumes

### pgAdmin Connection Issues
If pgAdmin can't connect to PostgreSQL:
1. Verify PostgreSQL is healthy: `docker-compose ps postgres`
2. Check PostgreSQL logs: `docker-compose logs postgres`
3. Verify pgAdmin is on database-net network
4. Ensure POSTGRES_PASSWORD matches in both services
5. Check pg_hba.conf allows connections from database-net (172.23.0.0/24)

---

## Quick Reference

### Service URLs

**Via NGINX Reverse Proxy:**
- Frontend: `http://localhost/`
- Keycloak Admin: `http://localhost/auth/` (admin/admin)
- Grafana: `http://localhost/monitoring/grafana/` (admin/admin)
- Prometheus: `http://localhost/monitoring/prometheus/`
- Tempo: `http://localhost/monitoring/tempo/`
- Loki: `http://localhost/monitoring/loki/`
- pgAdmin: `http://localhost/pgadmin/` (admin@example.com/admin OR Keycloak SSO)

### Database Connection

**From application services:**
```
Host: postgres
Port: 5432
Database: app_db
User: postgres
Password: <from POSTGRES_PASSWORD>
Connection String: postgresql://postgres:password@postgres:5432/app_db
```

**From pgAdmin:**
- Pre-configured server available after login
- Server name: "AI Infrastructure PostgreSQL"

### Network Topology

- **frontend-net** (172.50.0.0/24): NGINX, Frontend, pgAdmin
- **monitoring-net** (172.31.0.0/24): All monitoring services, exporters
- **database-net** (172.23.0.0/24): PostgreSQL, pgAdmin, postgres-exporter

