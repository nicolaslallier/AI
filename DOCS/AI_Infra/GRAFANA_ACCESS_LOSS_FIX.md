# Grafana Access Loss After Infrastructure Recreation - SOLUTION

## Problem
Every time you recreate the infrastructure (`docker-compose down && docker-compose up`), you lose access to Grafana.

## Root Causes Identified

### 1. Grafana Volume Persistence Issues
- **First Login Creates Admin User**: When Grafana starts for the first time, it creates an admin user with the password from `GF_SECURITY_ADMIN_PASSWORD`
- **Subsequent Starts Ignore Env Var**: After the initial setup, Grafana stores the admin user in its database (SQLite in the `grafana_data` volume)
- **Password Doesn't Update**: Changing `GF_SECURITY_ADMIN_PASSWORD` in docker-compose.yml has NO effect on existing Grafana installations
- **Volume Recreated = Password Lost**: If you recreate volumes, you lose the admin credentials

### 2. Missing Keycloak Integration
- Grafana is NOT configured as an OAuth2/OIDC client in Keycloak
- No SSO integration exists between Grafana and Keycloak
- Users cannot authenticate via Keycloak (unlike pgAdmin and MinIO)

### 3. Session Cookie Issues
- Old browser cookies reference previous Grafana instance IDs
- Cookies persist even after container recreation
- Causes "Invalid session" or redirect loop errors

## Solutions

### Solution 1: Always Use Clean Volumes (Recommended for Development)

**Use this Makefile command to completely reset the infrastructure:**

```bash
make clean
make up
```

Or manually:
```bash
# Stop and remove everything including volumes
docker-compose down -v

# Rebuild and start fresh
docker-compose up -d --build
```

**After clean start, login credentials will be:**
- Username: `admin`
- Password: `admin` (or value from `GRAFANA_PASSWORD` env var)

### Solution 2: Reset Grafana Admin Password in Existing Volume

If you want to keep your data but reset the password:

```bash
# Access Grafana container
docker exec -it ai_infra_grafana grafana-cli admin reset-admin-password NEW_PASSWORD

# Example:
docker exec -it ai_infra_grafana grafana-cli admin reset-admin-password admin

# Restart Grafana
docker-compose restart grafana
```

### Solution 3: Configure Keycloak OAuth for Grafana (Production-Ready)

This solution integrates Grafana with Keycloak for centralized authentication.

#### Step 1: Add Grafana Client to Keycloak Realm

Update `/Users/nicolaslallier/Dev Nick/AI_Infra/docker/keycloak/realm-export.json`:

Add this client to the `"clients"` array:

```json
{
  "clientId": "grafana-client",
  "name": "Grafana Monitoring",
  "description": "OIDC client for Grafana monitoring dashboards",
  "enabled": true,
  "clientAuthenticatorType": "client-secret",
  "secret": "**GENERATED**",
  "redirectUris": [
    "http://localhost/monitoring/grafana/login/generic_oauth",
    "http://localhost:80/monitoring/grafana/login/generic_oauth",
    "http://*/monitoring/grafana/login/generic_oauth"
  ],
  "webOrigins": [
    "http://localhost",
    "http://localhost:80",
    "+"
  ],
  "protocol": "openid-connect",
  "publicClient": false,
  "bearerOnly": false,
  "standardFlowEnabled": true,
  "implicitFlowEnabled": false,
  "directAccessGrantsEnabled": false,
  "serviceAccountsEnabled": false,
  "consentRequired": false,
  "fullScopeAllowed": true,
  "attributes": {
    "saml.assertion.signature": "false",
    "saml.force.post.binding": "false",
    "saml.multivalued.roles": "false",
    "saml.encrypt": "false",
    "saml.server.signature": "false",
    "saml.server.signature.keyinfo.ext": "false",
    "exclude.session.state.from.auth.response": "false",
    "saml_force_name_id_format": "false",
    "saml.client.signature": "false",
    "tls.client.certificate.bound.access.tokens": "false",
    "saml.authnstatement": "false",
    "display.on.consent.screen": "false",
    "saml.onetimeuse.condition": "false",
    "access.token.lifespan": "3600",
    "pkce.code.challenge.method": "S256"
  },
  "protocolMappers": [
    {
      "name": "realm roles",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-usermodel-realm-role-mapper",
      "consentRequired": false,
      "config": {
        "multivalued": "true",
        "userinfo.token.claim": "true",
        "id.token.claim": "true",
        "access.token.claim": "true",
        "claim.name": "realm_access.roles",
        "jsonType.label": "String"
      }
    },
    {
      "name": "email",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-usermodel-property-mapper",
      "consentRequired": false,
      "config": {
        "userinfo.token.claim": "true",
        "user.attribute": "email",
        "id.token.claim": "true",
        "access.token.claim": "true",
        "claim.name": "email",
        "jsonType.label": "String"
      }
    },
    {
      "name": "username",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-usermodel-property-mapper",
      "consentRequired": false,
      "config": {
        "userinfo.token.claim": "true",
        "user.attribute": "username",
        "id.token.claim": "true",
        "access.token.claim": "true",
        "claim.name": "preferred_username",
        "jsonType.label": "String"
      }
    },
    {
      "name": "full_name",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-full-name-mapper",
      "consentRequired": false,
      "config": {
        "id.token.claim": "true",
        "access.token.claim": "true",
        "userinfo.token.claim": "true"
      }
    },
    {
      "name": "groups",
      "protocol": "openid-connect",
      "protocolMapper": "oidc-group-membership-mapper",
      "consentRequired": false,
      "config": {
        "full.path": "false",
        "id.token.claim": "true",
        "access.token.claim": "true",
        "claim.name": "groups",
        "userinfo.token.claim": "true"
      }
    }
  ]
}
```

#### Step 2: Update Grafana Configuration

Add OAuth configuration to `/Users/nicolaslallier/Dev Nick/AI_Infra/docker/grafana/grafana.ini`:

```ini
[auth.generic_oauth]
enabled = true
name = Keycloak
icon = signin
allow_sign_up = true
auto_login = false
client_id = grafana-client
client_secret = YOUR_GENERATED_SECRET_FROM_KEYCLOAK
scopes = openid email profile
email_attribute_path = email
login_attribute_path = preferred_username
name_attribute_path = full_name
role_attribute_path = contains(realm_access.roles[*], 'ROLE_DEVOPS') && 'Admin' || 'Viewer'
role_attribute_strict = false
allow_assign_grafana_admin = false
auth_url = http://localhost/auth/realms/infra-admin/protocol/openid-connect/auth
token_url = http://keycloak:8080/auth/realms/infra-admin/protocol/openid-connect/token
api_url = http://keycloak:8080/auth/realms/infra-admin/protocol/openid-connect/userinfo
signout_redirect_url = http://localhost/auth/realms/infra-admin/protocol/openid-connect/logout?redirect_uri=http://localhost/monitoring/grafana

[auth]
# Allow both OAuth and local login
oauth_auto_login = false
disable_login_form = false
```

#### Step 3: Add Environment Variables to docker-compose.yml

Update the Grafana service in `/Users/nicolaslallier/Dev Nick/AI_Infra/docker-compose.yml`:

```yaml
grafana:
  image: grafana/grafana:latest
  container_name: ai_infra_grafana
  restart: unless-stopped
  environment:
    GF_SECURITY_ADMIN_USER: ${GRAFANA_USER:-admin}
    GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}
    GF_INSTALL_PLUGINS: ${GRAFANA_PLUGINS:-}
    GF_USERS_ALLOW_SIGN_UP: false
    # Subpath configuration
    GF_SERVER_ROOT_URL: http://localhost/monitoring/grafana
    GF_SERVER_SERVE_FROM_SUB_PATH: "true"
    GF_SERVER_DOMAIN: localhost
    GF_PATHS_CONFIG: /etc/grafana/grafana.ini
    # OAuth Configuration
    GF_AUTH_GENERIC_OAUTH_ENABLED: ${GRAFANA_OAUTH_ENABLED:-false}
    GF_AUTH_GENERIC_OAUTH_NAME: Keycloak
    GF_AUTH_GENERIC_OAUTH_CLIENT_ID: ${GRAFANA_OAUTH_CLIENT_ID:-grafana-client}
    GF_AUTH_GENERIC_OAUTH_CLIENT_SECRET: ${GRAFANA_OAUTH_CLIENT_SECRET}
    GF_AUTH_GENERIC_OAUTH_SCOPES: openid email profile
    GF_AUTH_GENERIC_OAUTH_AUTH_URL: http://localhost/auth/realms/infra-admin/protocol/openid-connect/auth
    GF_AUTH_GENERIC_OAUTH_TOKEN_URL: http://keycloak:8080/auth/realms/infra-admin/protocol/openid-connect/token
    GF_AUTH_GENERIC_OAUTH_API_URL: http://keycloak:8080/auth/realms/infra-admin/protocol/openid-connect/userinfo
    GF_AUTH_GENERIC_OAUTH_ALLOW_SIGN_UP: "true"
    GF_AUTH_OAUTH_AUTO_LOGIN: "false"
```

#### Step 4: Create .env File with Secrets

Create or update `/Users/nicolaslallier/Dev Nick/AI_Infra/.env`:

```bash
# Grafana Configuration
GRAFANA_USER=admin
GRAFANA_PASSWORD=admin

# Grafana OAuth (set to true to enable)
GRAFANA_OAUTH_ENABLED=true
GRAFANA_OAUTH_CLIENT_ID=grafana-client
GRAFANA_OAUTH_CLIENT_SECRET=YOUR_SECRET_HERE

# Keycloak Configuration
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=admin
```

#### Step 5: Apply the Configuration

```bash
# Stop services
docker-compose down

# Start Keycloak first to generate the client secret
docker-compose up -d keycloak postgres

# Wait for Keycloak to be ready (about 60 seconds)
sleep 60

# Get the client secret from Keycloak
docker exec -it ai_infra_keycloak /opt/keycloak/bin/kcadm.sh config credentials \
  --server http://localhost:8080/auth \
  --realm master \
  --user admin \
  --password admin

docker exec -it ai_infra_keycloak /opt/keycloak/bin/kcadm.sh get clients \
  -r infra-admin \
  --fields id,clientId,secret \
  | grep -A 2 "grafana-client"

# Copy the secret and update your .env file
# Then restart everything
docker-compose up -d
```

### Solution 4: Clear Browser Cookies (Quick Fix)

If you get "Invalid session" errors:

1. Open browser DevTools (F12)
2. Go to Application/Storage tab
3. Clear all cookies for `localhost`
4. Clear localStorage for `localhost`
5. Refresh the page
6. Try logging in again

## Prevention Strategy

### For Development (Fastest Iteration)

```bash
# Always use clean volumes
make clean && make up

# Or add this to your Makefile
reset-grafana:
	docker-compose stop grafana
	docker volume rm ai_infra_grafana_data || true
	docker-compose up -d grafana
	@echo "Grafana reset complete. Use admin/admin to login."
```

### For Production (Data Persistence)

1. **Use Keycloak OAuth** (Solution 3) - Provides centralized authentication
2. **External Grafana Database** - Use PostgreSQL instead of SQLite
3. **Configuration as Code** - Use Grafana's provisioning API to set up dashboards/datasources
4. **Backup Strategy** - Regular backups of `grafana_data` volume

```yaml
# Add to docker-compose.yml for external database
environment:
  GF_DATABASE_TYPE: postgres
  GF_DATABASE_HOST: postgres:5432
  GF_DATABASE_NAME: grafana
  GF_DATABASE_USER: grafana
  GF_DATABASE_PASSWORD: ${GRAFANA_DB_PASSWORD}
```

## Testing Checklist

After applying any solution:

- [ ] Stop all services: `docker-compose down`
- [ ] Remove Grafana volume: `docker volume rm ai_infra_grafana_data`
- [ ] Start services: `docker-compose up -d`
- [ ] Wait 30 seconds for Grafana to initialize
- [ ] Navigate to `http://localhost/monitoring/grafana/`
- [ ] Login with `admin`/`admin` (or OAuth via Keycloak)
- [ ] Verify dashboards load correctly
- [ ] Test recreation: `docker-compose restart grafana`
- [ ] Verify you can still login

## Quick Reference Commands

```bash
# Reset Grafana completely
docker-compose stop grafana
docker volume rm ai_infra_grafana_data
docker-compose up -d grafana

# Reset admin password in running container
docker exec -it ai_infra_grafana grafana-cli admin reset-admin-password admin

# Check Grafana logs
docker logs ai_infra_grafana -f

# Verify Grafana health
curl http://localhost/monitoring/grafana/api/health

# Test OAuth endpoints (if configured)
curl http://localhost/auth/realms/infra-admin/.well-known/openid-configuration
```

## Recommended Immediate Action

**For now, use Solution 1 (Clean volumes) combined with Solution 4 (Clear cookies):**

```bash
# Complete infrastructure reset
docker-compose down -v
docker-compose up -d
# Wait 2 minutes for all services to start
# Clear browser cookies
# Login to Grafana with admin/admin
```

**Long-term, implement Solution 3 (Keycloak OAuth) for production-ready authentication.**

---

**Status:** Solutions provided, awaiting user preference for implementation
**Date:** December 6, 2025
**Priority:** High - Impacts development workflow

