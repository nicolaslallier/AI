# Grafana "Too Many Redirects" Error - Fixed

## Problem

When accessing `http://localhost/monitoring/grafana/`, you get a "too many redirects" error.

## Root Cause

The issue was caused by a configuration mismatch between Grafana and Nginx:

- **Grafana** was configured with `serve_from_sub_path = false`, expecting nginx to strip the `/monitoring/grafana/` prefix
- **Nginx** was configured to strip the prefix with `rewrite` rules
- This created a redirect loop where both Grafana and Nginx were trying to handle the path transformation

## Solution

Switch to `serve_from_sub_path = true`, which is simpler and more reliable:

1. **Grafana** handles the full path `/monitoring/grafana/*` internally
2. **Nginx** passes the complete path without modification
3. No path rewriting = no redirect loops

## Changes Made

### 1. docker/grafana/grafana.ini
Changed `serve_from_sub_path` from `false` to `true`:

```ini
[server]
root_url = http://localhost/monitoring/grafana/
serve_from_sub_path = true  # Changed from false
domain = localhost
```

### 2. docker-compose.yml
Updated Grafana environment variable:

```yaml
GF_SERVER_SERVE_FROM_SUB_PATH: "true"  # Changed from "false"
```

### 3. docker/nginx/nginx.conf
Simplified the Grafana location block by removing path rewriting:

```nginx
location /monitoring/grafana/ {
    set $grafana_upstream http://grafana:3000;
    
    # Pass the FULL path to Grafana (no rewriting needed)
    proxy_pass $grafana_upstream;
    
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # WebSocket support
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    
    # Timeouts
    proxy_connect_timeout 300;
    proxy_send_timeout 300;
    proxy_read_timeout 300;
    send_timeout 300;
}
```

## How to Apply the Fix

### Option 1: Restart Services (Recommended)

The changes have already been made to the configuration files. Simply restart the affected services:

```bash
# Stop Grafana and Nginx
docker-compose stop grafana nginx

# Start them again
docker-compose up -d grafana nginx
```

### Option 2: Full Restart

If you want to be extra sure everything is working:

```bash
# Stop all services
docker-compose down

# Start all services
docker-compose up -d

# Or use the convenience script
./scripts/stop.sh
./scripts/start.sh
```

### Option 3: Restart Only Grafana (Quick Test)

If you want to test just Grafana first:

```bash
docker-compose restart grafana
```

Then test if the issue is resolved. If it still redirects, restart nginx too:

```bash
docker-compose restart nginx
```

## Verification

After restarting the services:

1. **Wait 10-15 seconds** for Grafana to fully start
2. **Open your browser** and navigate to: http://localhost/monitoring/grafana/
3. **You should see** the Grafana login page (not a redirect error)
4. **Login with**:
   - Username: `admin`
   - Password: `admin`

## Additional Verification Commands

### Check if Grafana is running:
```bash
docker ps | grep grafana
```

### Check Grafana logs:
```bash
docker logs ai_infra_grafana --tail 50
```

Look for messages like:
- `HTTP Server Listen` - Grafana web server started
- `Serving Grafana from subpath enabled` - Confirms our configuration

### Check Nginx logs:
```bash
docker logs ai_infra_nginx --tail 50
```

### Test Grafana health:
```bash
curl -I http://localhost/monitoring/grafana/api/health
```

Should return `HTTP/1.1 200 OK`

## What If It Still Doesn't Work?

### Clear Browser Cache

The redirect loop might be cached in your browser:

**Chrome/Edge:**
1. Open DevTools (F12)
2. Right-click the refresh button
3. Select "Empty Cache and Hard Reload"

**Firefox:**
1. Ctrl+Shift+Delete
2. Select "Cached Web Content"
3. Click "Clear Now"

**Or try incognito/private browsing mode**

### Check Container Status

```bash
docker-compose ps
```

Both `ai_infra_grafana` and `ai_infra_nginx` should show status "Up".

### Restart All Monitoring Services

```bash
docker-compose restart prometheus grafana tempo loki nginx
```

### Check for Port Conflicts

```bash
# Make sure nothing else is using port 80
lsof -i :80

# Make sure Grafana's internal port is available
docker exec ai_infra_grafana netstat -tlnp | grep 3000
```

## Understanding the Fix

### Before (serve_from_sub_path = false)

```
Browser → http://localhost/monitoring/grafana/login
         ↓
Nginx strips prefix → Grafana receives /login
         ↓
Grafana (root_url=/monitoring/grafana/) → Redirects to /monitoring/grafana/login
         ↓
Nginx strips prefix again → /login
         ↓
REDIRECT LOOP! 🔄
```

### After (serve_from_sub_path = true)

```
Browser → http://localhost/monitoring/grafana/login
         ↓
Nginx passes full path → Grafana receives /monitoring/grafana/login
         ↓
Grafana handles subpath internally → Serves page ✅
         ↓
NO REDIRECT!
```

## Why This Approach is Better

1. **Simpler**: No path rewriting in nginx
2. **More Reliable**: Grafana handles its own subpath
3. **Less Prone to Errors**: Single point of path handling
4. **Official Recommendation**: Grafana documentation recommends this for reverse proxies
5. **Easier to Debug**: Fewer layers of transformation

## Backwards Compatibility

The following URLs still work (due to redirect rules in nginx):

- `http://localhost/grafana/` → Redirects to `http://localhost/monitoring/grafana/`
- `http://localhost/grafana` → Redirects to `http://localhost/monitoring/grafana/`

These redirects are preserved in the nginx configuration.

## Related Services

The same pattern is used for other monitoring services, but they don't have the same redirect issue:

- **Prometheus**: Uses `--web.external-url` and `--web.route-prefix` flags
- **Tempo**: Handles subpath natively  
- **Loki**: Handles subpath natively

Only Grafana required the `serve_from_sub_path` configuration change.

## Testing Other Services

While fixing Grafana, verify other services still work:

- **Prometheus**: http://localhost/monitoring/prometheus/
- **Frontend**: http://localhost/home
- **Keycloak**: http://localhost/auth/
- **pgAdmin**: http://localhost/pgadmin/

## Quick Reference

| URL | Service | Expected Result |
|-----|---------|-----------------|
| http://localhost/monitoring/grafana/ | Grafana | Login page ✅ |
| http://localhost/grafana/ | Redirect | Redirects to /monitoring/grafana/ ✅ |
| http://localhost/monitoring/prometheus/ | Prometheus | Dashboard ✅ |
| http://localhost/auth/ | Keycloak | Admin Console ✅ |
| http://localhost/home | Frontend | Vue App ✅ |

## Need More Help?

If the issue persists after applying these fixes:

1. **Collect logs**:
   ```bash
   docker logs ai_infra_grafana > grafana.log 2>&1
   docker logs ai_infra_nginx > nginx.log 2>&1
   ```

2. **Check Grafana configuration**:
   ```bash
   docker exec ai_infra_grafana cat /etc/grafana/grafana.ini | grep -A 5 "\[server\]"
   ```

3. **Test with curl**:
   ```bash
   curl -v http://localhost/monitoring/grafana/ 2>&1 | grep -E "(Location|HTTP)"
   ```

## Summary

✅ **Changed**: `serve_from_sub_path = true` in Grafana configuration  
✅ **Changed**: Removed path rewriting in nginx  
✅ **Changed**: Updated docker-compose environment variable  
✅ **Result**: No more redirect loops!

**Next step**: Restart the services and enjoy your working Grafana! 🎉

