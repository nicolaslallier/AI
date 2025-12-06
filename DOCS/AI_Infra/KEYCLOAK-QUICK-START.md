# Keycloak Quick Start Guide

## 🎯 Quick Access

| Service | URL | Credentials |
|---------|-----|-------------|
| **Keycloak Admin Console** | http://localhost/auth/ | admin / admin |
| **Keycloak Realm** | http://localhost/auth/realms/infra-admin | - |
| **pgAdmin** | http://localhost/pgadmin | admin@example.com / admin |

## ✅ Verification Checklist

### 1. Check Service Status
```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "(keycloak|postgres)"
```
Expected output:
- `ai_infra_keycloak` → `Up X minutes (healthy)`
- `ai_infra_postgres` → `Up X minutes (healthy)`

### 2. Verify Database
```bash
# Check Keycloak database exists
docker exec ai_infra_postgres psql -U postgres -c "\l" | grep keycloak

# Check Keycloak user exists  
docker exec ai_infra_postgres psql -U postgres -c "SELECT rolname FROM pg_roles WHERE rolname = 'keycloak';"

# Check Keycloak can access database
docker exec ai_infra_postgres psql -U keycloak -d keycloak -c "\dt" | head -10
```

### 3. Test Web Access
```bash
# Test Keycloak is accessible
curl -I http://localhost/auth/

# Test realm is accessible
curl http://localhost/auth/realms/infra-admin | jq '.realm'
```

### 4. Run Full Validation
```bash
cd /path/to/AI_Infra
./scripts/validate-keycloak.sh
```
Expected: 25/27 tests passing (92.6% success rate)

## 🚀 First Time Setup

### If Starting Fresh

```bash
# Navigate to project directory
cd /path/to/AI_Infra

# Start all services
make up

# Wait for services to become healthy (~2 minutes)
watch docker ps

# Verify Keycloak is healthy
docker logs ai_infra_keycloak | tail -20

# Access admin console
open http://localhost/auth/
```

### If Keycloak Already Exists (Migration)

```bash
# Stop all services
make down

# Remove old PostgreSQL data (⚠️ this deletes all database data)
docker volume rm ai_infra_postgres_data

# Start services with fresh database
make up

# The init script will automatically:
# 1. Create keycloak database
# 2. Create keycloak user with password
# 3. Set up proper permissions
# 4. Keycloak will initialize schema on first start
```

## 🔧 Troubleshooting

### Issue: "password authentication failed for user keycloak"

**Solution 1: Reset Database Volume**
```bash
make down
docker volume rm ai_infra_postgres_data
make up
```

**Solution 2: Check Environment Variables**
```bash
# Verify .env file has matching passwords
grep KEYCLOAK_DB_PASSWORD .env
```

**Solution 3: Check Logs**
```bash
# Check PostgreSQL init logs
docker logs ai_infra_postgres | grep keycloak

# Check Keycloak connection logs  
docker logs ai_infra_keycloak | grep -i "database\|connection"
```

### Issue: Keycloak not starting

```bash
# Check if PostgreSQL is healthy first
docker ps | grep postgres

# Check Keycloak logs for errors
docker logs ai_infra_keycloak

# Restart Keycloak
docker restart ai_infra_keycloak
```

### Issue: Realm not found

```bash
# Check if realm import succeeded
docker logs ai_infra_keycloak | grep "realm-export"

# Verify realm file exists
ls -la docker/keycloak/realm-export.json

# Check realm is imported
curl http://localhost/auth/realms/infra-admin
```

## 🔐 Security Notes

### Default Credentials (Development)
- **Keycloak Admin**: admin / admin
- **Database**: keycloak / keycloak
- **pgAdmin**: admin@example.com / admin

⚠️ **Change these before production deployment!**

### Production Checklist
- [ ] Change all default passwords
- [ ] Enable HTTPS/TLS
- [ ] Use external secret management
- [ ] Disable development mode
- [ ] Configure proper CORS policies
- [ ] Set up backup strategy
- [ ] Enable audit logging
- [ ] Configure rate limiting

## 📊 Monitoring

### Check Keycloak Metrics
```bash
# Prometheus metrics endpoint
curl http://localhost/monitoring/prometheus/targets | grep keycloak
```

### View Keycloak Logs in Grafana
1. Open http://localhost/monitoring/grafana
2. Navigate to "Explore"
3. Select "Loki" as data source
4. Query: `{container_name="ai_infra_keycloak"}`

### View Keycloak Dashboard
1. Open http://localhost/monitoring/grafana  
2. Navigate to "Dashboards"
3. Select "Keycloak Dashboard"

## 🧪 Testing SSO Integration

### Test OIDC Discovery
```bash
curl http://localhost/auth/realms/infra-admin/.well-known/openid-configuration | jq
```

### Get Realm Public Key
```bash
curl http://localhost/auth/realms/infra-admin | jq '.public_key'
```

### Test Token Endpoint
```bash
curl -X POST http://localhost/auth/realms/infra-admin/protocol/openid-connect/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin" \
  -d "password=admin" \
  -d "grant_type=password" \
  -d "client_id=admin-cli"
```

## 🔄 Common Operations

### Restart Keycloak
```bash
docker restart ai_infra_keycloak
```

### View Real-time Logs
```bash
docker logs -f ai_infra_keycloak
```

### Access PostgreSQL Shell
```bash
# As postgres superuser
docker exec -it ai_infra_postgres psql -U postgres

# As keycloak user
docker exec -it ai_infra_postgres psql -U keycloak -d keycloak
```

### Export Realm Configuration
```bash
# From running container
docker exec ai_infra_keycloak /opt/keycloak/bin/kc.sh export \
  --dir /tmp/export \
  --realm infra-admin

# Copy to host
docker cp ai_infra_keycloak:/tmp/export/infra-admin-realm.json ./backup/
```

### Import Realm Configuration
```bash
# Place realm file in docker/keycloak/
cp my-realm.json docker/keycloak/realm-export.json

# Restart Keycloak with import
docker restart ai_infra_keycloak

# Check logs for import success
docker logs ai_infra_keycloak | grep import
```

## 📚 Useful SQL Queries

```sql
-- Connect to keycloak database
docker exec -it ai_infra_postgres psql -U keycloak -d keycloak

-- List all realms
SELECT id, name, enabled FROM realm;

-- List all users
SELECT username, email, enabled FROM user_entity;

-- List all clients  
SELECT client_id, name, enabled FROM client;

-- List all roles
SELECT name, description FROM keycloak_role;

-- Check user count
SELECT COUNT(*) FROM user_entity;

-- Check active sessions
SELECT COUNT(*) FROM user_session;
```

## 🎓 Learning Resources

### Keycloak Documentation
- **Official Docs**: https://www.keycloak.org/documentation
- **Admin Guide**: https://www.keycloak.org/docs/latest/server_admin/
- **Developer Guide**: https://www.keycloak.org/docs/latest/server_development/

### Architecture
- See `KEYCLOAK_INTEGRATION.md` for detailed integration documentation
- See `KEYCLOAK-FIX-SUMMARY.md` for implementation details
- See `docker/keycloak/README.md` for Keycloak-specific configuration

## 💡 Tips

1. **Wait for Health Check**: Keycloak takes ~90 seconds to become healthy after starting
2. **Check Logs First**: Most issues can be diagnosed from container logs
3. **Database First**: Always ensure PostgreSQL is healthy before troubleshooting Keycloak
4. **Realm Import**: Realm configuration is only imported on first startup or with `--import-realm` flag
5. **Development Mode**: Current setup uses `start-dev` which is NOT for production use

## 🆘 Support

If you encounter issues not covered here:

1. **Check Logs**:
   ```bash
   docker logs ai_infra_keycloak
   docker logs ai_infra_postgres
   ```

2. **Run Validation**:
   ```bash
   ./scripts/validate-keycloak.sh
   ```

3. **Check Service Health**:
   ```bash
   docker ps
   docker inspect ai_infra_keycloak | jq '.[0].State.Health'
   ```

4. **Review Documentation**:
   - `KEYCLOAK-FIX-SUMMARY.md` - Detailed fix documentation
   - `KEYCLOAK_INTEGRATION.md` - Integration guide
   - `docker/keycloak/README.md` - Configuration details

---

**Last Updated**: December 6, 2025  
**Keycloak Version**: 26.4.7  
**Status**: ✅ Working (25/27 validation tests passing)
