# Keycloak HTTPS Requirement Fix

## Issue
Keycloak shows "HTTPS required" error when accessed through NGINX reverse proxy at `http://localhost/auth/`

## Root Cause
Keycloak in production mode (or when not in dev mode) enforces HTTPS by default. The `proxy=edge` setting requires proper configuration to recognize HTTP is being terminated at the reverse proxy level.

## Solution Applied

### 1. Updated Keycloak Configuration
**File:** `docker/keycloak/keycloak.conf`

Added additional proxy forwarding settings:
```conf
hostname-strict-backchannel=false
proxy-address-forwarding=true
```

### 2. Updated Docker Compose Environment Variables
**File:** `docker-compose.yml`

Added environment variables to Keycloak service:
```yaml
KC_HOSTNAME_STRICT_BACKCHANNEL: false
KC_PROXY_ADDRESS_FORWARDING: true
```

### 3. Verification Steps

After applying these changes:

1. **Restart Keycloak service:**
   ```bash
   cd /Users/nicolaslallier/Dev\ Nick/AI_Infra
   docker-compose restart keycloak
   ```

2. **Check Keycloak logs for startup confirmation:**
   ```bash
   docker logs -f ai_infra_keycloak
   ```
   
   Look for:
   - "Listening on: http://0.0.0.0:8080"
   - No errors about HTTPS requirements
   - "Keycloak 23.x.x started in Xms"

3. **Test access through NGINX:**
   ```bash
   # Health check (should return HTTP 200)
   curl -I http://localhost/auth/health/ready
   
   # Admin console (should return HTTP 200 and HTML)
   curl -I http://localhost/auth/
   ```

4. **Access in browser:**
   - Navigate to: http://localhost/auth/
   - Should see Keycloak welcome page or admin console
   - No "HTTPS required" error

### 4. Alternative: Force Development Mode

If issues persist, you can explicitly force development mode (NOT recommended for production):

**In docker-compose.yml**, change the Keycloak command:
```yaml
# Current (recommended):
command: start-dev --import-realm

# Alternative if needed:
command: start-dev --import-realm --hostname-strict=false
```

### 5. Environment Variable Override

Create/update `.env` file in project root with:
```bash
# Keycloak Configuration
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=admin
KEYCLOAK_LOG_LEVEL=INFO

# Database
KEYCLOAK_DB_PASSWORD=keycloak

# Force development settings (remove in production)
KC_HOSTNAME_STRICT=false
KC_HOSTNAME_STRICT_HTTPS=false
KC_HTTP_ENABLED=true
```

## Testing the Fix

### Quick Test Script

```bash
#!/bin/bash
echo "Testing Keycloak access..."

# Test 1: Health check
echo -n "1. Health check: "
if curl -sf http://localhost/auth/health/ready > /dev/null; then
    echo "✓ PASSED"
else
    echo "✗ FAILED"
fi

# Test 2: Admin console
echo -n "2. Admin console access: "
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/auth/)
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "303" ]; then
    echo "✓ PASSED (HTTP $HTTP_CODE)"
else
    echo "✗ FAILED (HTTP $HTTP_CODE)"
fi

# Test 3: Realm discovery
echo -n "3. Realm discovery: "
if curl -sf http://localhost/auth/realms/infra-admin/.well-known/openid-configuration > /dev/null; then
    echo "✓ PASSED"
else
    echo "✗ FAILED"
fi

echo ""
echo "If all tests passed, Keycloak is working correctly!"
```

Save as `scripts/test-keycloak.sh` and run:
```bash
chmod +x scripts/test-keycloak.sh
./scripts/test-keycloak.sh
```

## Troubleshooting

### If "HTTPS required" error persists:

1. **Check Keycloak realm settings:**
   - Access admin console (if possible through direct container access)
   - Go to: Realm Settings → Login
   - Set "Require SSL" to "none" or "external requests"
   
   Via docker exec:
   ```bash
   docker exec -it ai_infra_keycloak /bin/bash
   # Inside container
   /opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080 --realm master --user admin --password admin
   /opt/keycloak/bin/kcadm.sh update realms/infra-admin -s sslRequired=EXTERNAL
   ```

2. **Verify NGINX proxy headers:**
   ```bash
   docker exec ai_infra_nginx cat /etc/nginx/nginx.conf | grep -A 10 "location /auth/"
   ```

3. **Check Keycloak environment variables:**
   ```bash
   docker exec ai_infra_keycloak env | grep KC_
   ```

4. **Review Keycloak startup logs:**
   ```bash
   docker logs ai_infra_keycloak 2>&1 | grep -i "hostname\|proxy\|https\|ssl"
   ```

### Direct Container Access (Bypass NGINX)

For debugging, you can temporarily expose Keycloak port directly:

**In docker-compose.yml** (under keycloak service):
```yaml
ports:
  - "8080:8080"
```

Then restart and access directly:
```bash
docker-compose restart keycloak
# Access at: http://localhost:8080/
```

If direct access works but proxy access doesn't, the issue is with NGINX configuration.

## Production Considerations

For production deployments:

1. **Enable HTTPS at NGINX level:**
   - Obtain SSL/TLS certificates
   - Configure NGINX for SSL termination
   - Update `proxy_set_header X-Forwarded-Proto https`

2. **Update realm SSL requirement:**
   - Set "Require SSL" to "all requests" in production
   - Ensure all services communicate via HTTPS

3. **Remove development mode:**
   - Change command from `start-dev` to `start`
   - Configure production-grade settings in keycloak.conf

## References

- [Keycloak Reverse Proxy Guide](https://www.keycloak.org/server/reverseproxy)
- [Keycloak Configuration Options](https://www.keycloak.org/server/all-config)
- [NGINX Proxy Headers](http://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_set_header)

---

**Applied:** December 6, 2025  
**Status:** Ready for testing

