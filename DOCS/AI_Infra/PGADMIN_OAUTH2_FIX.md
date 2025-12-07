# pgAdmin OAuth2 Error Fix

## Issue
pgAdmin was throwing a 404 error when trying to authenticate with Keycloak:
```
404 Client Error: Not Found for url: http://keycloak:8080/realms/infra-admin/.well-known/openid-configuration
```

## Root Cause
pgAdmin was configured to access Keycloak directly at `http://keycloak:8080` instead of through the nginx reverse proxy. 

Keycloak is configured with `KC_PROXY=edge` mode, which means it expects all requests to come through a reverse proxy. When accessed directly at `http://keycloak:8080`, it returns 404 errors for realm endpoints because the proxy headers are missing.

## Solution
Modified pgAdmin's OAuth2 configuration in `/docker/pgadmin/config_local.py` to route all Keycloak requests through nginx at `http://nginx/auth` instead of directly to `http://keycloak:8080`.

### Changes Made

**File: `/docker/pgadmin/config_local.py`**

Changed from:
```python
_keycloak_base_url = os.environ.get('KEYCLOAK_URL', 'http://keycloak:8080')
```

To:
```python
# pgAdmin must access Keycloak through nginx reverse proxy
_keycloak_base_url = 'http://nginx/auth'
```

This ensures all OAuth2 endpoints use the proxy path:
- Token URL: `http://nginx/auth/realms/infra-admin/protocol/openid-connect/token`
- Authorization URL: `http://nginx/auth/realms/infra-admin/protocol/openid-connect/auth`
- Userinfo Endpoint: `http://nginx/auth/realms/infra-admin/protocol/openid-connect/userinfo`
- Metadata URL: `http://nginx/auth/realms/infra-admin/.well-known/openid-configuration`

## Network Architecture

```
┌─────────────┐
│  pgAdmin    │
│  Container  │
└──────┬──────┘
       │ frontend-net
       │
       ▼
┌─────────────┐      ┌──────────────┐
│    nginx    │────▶ │  Keycloak    │
│   /auth/*   │      │  Container   │
└─────────────┘      └──────────────┘
```

- pgAdmin and nginx are on the same `frontend-net` network
- nginx forwards `/auth/*` requests to Keycloak on port 8080
- Keycloak receives proper proxy headers from nginx

## Verification

### 1. Test endpoint accessibility from pgAdmin container:
```bash
docker-compose exec pgadmin wget -O- --spider http://nginx/auth/realms/infra-admin/.well-known/openid-configuration
```
Expected: `remote file exists`

### 2. Test from host through nginx:
```bash
curl http://localhost/auth/realms/infra-admin/.well-known/openid-configuration | jq '.issuer'
```
Expected: `"http://localhost/auth/realms/infra-admin"`

### 3. Check pgAdmin logs for errors:
```bash
docker-compose logs --tail=50 pgadmin | grep -i error
```
Expected: No 404 errors for `.well-known/openid-configuration`

## Testing OAuth2 Login

1. **Access pgAdmin**: http://localhost/pgadmin/
2. **Login page should display**:
   - Email/Password form (internal authentication)
   - "Login with Keycloak" button (OAuth2)
3. **Click "Login with Keycloak"**
4. **Redirect to Keycloak**: Should redirect to Keycloak login page
5. **Login with Keycloak credentials**:
   - DBA Admin: `dba-admin@example.com` / `ChangeMe123!`
   - DevOps User: `devops@example.com` / `ChangeMe123!`
6. **Redirect back to pgAdmin**: Should be authenticated and see dashboard

## Environment Variables

The OAuth2 configuration respects these environment variables:

```yaml
# docker-compose.yml pgadmin service environment
PGADMIN_OAUTH2_NAME: ${PGADMIN_OAUTH2_NAME:-Keycloak}
PGADMIN_OAUTH2_DISPLAY_NAME: ${PGADMIN_OAUTH2_DISPLAY_NAME:-Login with Keycloak}
PGADMIN_OAUTH2_CLIENT_ID: ${PGADMIN_OAUTH2_CLIENT_ID:-pgadmin-client}
PGADMIN_OAUTH2_CLIENT_SECRET: ${PGADMIN_OAUTH2_CLIENT_SECRET:-}
PGADMIN_OAUTH2_SCOPE: ${PGADMIN_OAUTH2_SCOPE:-openid email profile}
KEYCLOAK_REALM: ${KEYCLOAK_REALM:-infra-admin}
```

## Keycloak Client Configuration

The `pgadmin-client` is configured in Keycloak with:
- **Client ID**: `pgadmin-client`
- **Access Type**: `confidential`
- **Valid Redirect URIs**: 
  - `http://localhost/pgadmin/*`
  - `http://localhost:80/pgadmin/*`
  - `http://*/pgadmin/*`
- **Web Origins**: 
  - `http://localhost`
  - `http://localhost:80`
  - `+` (all origins from redirect URIs)

## Role-Based Access

pgAdmin users are granted admin access based on Keycloak roles:
- **ROLE_DBA**: Full admin access to pgAdmin
- **ROLE_DEVOPS**: Full admin access to pgAdmin
- **ROLE_READONLY_MONITORING**: Read-only access (default)

See `/docker/pgadmin/config_local.py` function `OAUTH2_CLAIM_ADMIN_ROLE()` for role mapping logic.

## Troubleshooting

### Still getting 404 errors?
1. Verify nginx is running: `docker-compose ps nginx`
2. Check nginx configuration: `docker-compose exec nginx cat /etc/nginx/nginx.conf | grep -A10 "location /auth"`
3. Verify Keycloak is healthy: `docker-compose ps keycloak`
4. Restart pgAdmin: `docker-compose restart pgadmin`

### OAuth2 button not appearing?
1. Check pgAdmin config is loaded: `docker-compose exec pgadmin cat /pgadmin4/config_local.py | grep OAUTH2_CONFIG`
2. Verify authentication sources: `docker-compose exec pgadmin cat /pgadmin4/config_local.py | grep AUTHENTICATION_SOURCES`
3. Check browser console for JavaScript errors

### Login fails after Keycloak redirect?
1. Verify redirect URIs in Keycloak client configuration
2. Check client secret is set (if using confidential client)
3. Review pgAdmin logs: `docker-compose logs --tail=100 pgadmin`

## Related Files

- `/docker/pgadmin/config_local.py` - OAuth2 configuration
- `/docker/pgadmin/config_distro.py` - Authentication sources
- `/docker/keycloak/realm-export.json` - Keycloak realm with pgadmin-client
- `/docker/nginx/nginx.conf` - Reverse proxy configuration

## Commands

```bash
# Restart pgAdmin after config changes
make restart-pgadmin

# View pgAdmin logs
make logs-pgadmin

# Open pgAdmin in browser
make pgadmin

# Test Keycloak endpoint
curl http://localhost/auth/realms/infra-admin/.well-known/openid-configuration
```

## Status

✅ **FIXED** - pgAdmin can now successfully fetch Keycloak's OpenID configuration through nginx reverse proxy.

The OAuth2 login flow should work correctly. Users can now authenticate with Keycloak SSO in addition to internal pgAdmin credentials.

