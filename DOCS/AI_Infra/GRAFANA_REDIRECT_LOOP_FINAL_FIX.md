# Grafana Redirect Loop - Final Fix

## Problem

Grafana was stuck in an infinite redirect loop, continuously appending `/monitoring/grafana` to the URL:

```
http://localhost/grafana/monitoring/grafana/monitoring/grafana/monitoring/grafana/...
```

## Root Cause

The issue was a **double configuration conflict**:

1. Mismatch between nginx reverse proxy configuration and Grafana's `serve_from_sub_path` setting
2. Environment variable `GF_SERVER_SERVE_FROM_SUB_PATH` was overriding the config file setting

### Previous Configuration (BROKEN)

**Grafana (`grafana.ini`):**
```ini
root_url = http://localhost/monitoring/grafana/
serve_from_sub_path = true
```

**Nginx:**
```nginx
location /monitoring/grafana/ {
    proxy_pass http://grafana:3000;  # Passes FULL path including /monitoring/grafana/
}
```

**What Happened:**
1. Browser requests: `GET /monitoring/grafana/`
2. Nginx passes to Grafana: `GET /monitoring/grafana/`
3. Grafana (with `serve_from_sub_path=true`) expects the full path and processes it
4. BUT Grafana's routing then tries to redirect based on `root_url`, adding `/monitoring/grafana/` again
5. Result: Infinite loop

## Solution

Change Grafana to serve from root internally while maintaining the public URL awareness:

### Fixed Configuration

**Grafana Config File (`grafana.ini`):**
```ini
root_url = http://localhost/monitoring/grafana/
serve_from_sub_path = false  # ← CHANGED: Grafana serves from root internally
```

**Grafana Environment Variables (`docker-compose.yml`):**
```yaml
environment:
  GF_SERVER_ROOT_URL: http://localhost/monitoring/grafana/
  GF_SERVER_SERVE_FROM_SUB_PATH: "false"  # ← CRITICAL: Must match config file
```

**Nginx:**
```nginx
location /monitoring/grafana/ {
    rewrite ^/monitoring/grafana/(.*)$ /$1 break;  # ← STRIP prefix
    proxy_pass http://grafana:3000;
}
```

**How It Works Now:**
1. Browser requests: `GET /monitoring/grafana/dashboard/home`
2. Nginx rewrites and proxies: `GET /dashboard/home` → `http://grafana:3000/dashboard/home`
3. Grafana receives: `GET /dashboard/home`
4. Grafana serves content from root but generates links with `/monitoring/grafana/` prefix (via `root_url`)
5. Result: Clean URLs, no redirect loop

## Key Concepts

### `serve_from_sub_path` Setting

- **`true`**: Grafana expects to receive the full path including the subpath
  - Example: Grafana receives `GET /monitoring/grafana/dashboard`
  - Use when: Proxy passes the full path without stripping

- **`false`**: Grafana serves from root internally but knows its public URL
  - Example: Grafana receives `GET /dashboard`
  - Use when: Proxy strips the subpath before forwarding
  - Grafana uses `root_url` to generate correct public URLs

### Nginx Rewrite Rules

```nginx
rewrite ^/monitoring/grafana/(.*)$ /$1 break;
```

- `^/monitoring/grafana/(.*)$` - Captures everything after `/monitoring/grafana/`
- `/$1` - Replaces with just the captured part
- `break` - Stops processing further rewrite rules

**Examples:**
- `/monitoring/grafana/` → `/`
- `/monitoring/grafana/dashboard/home` → `/dashboard/home`
- `/monitoring/grafana/api/datasources` → `/api/datasources`

## Testing

After applying the fix and restarting containers:

```bash
docker-compose up -d grafana nginx
```

### Test Results ✅

1. ✅ `http://localhost/monitoring/grafana/` → **302 to /monitoring/grafana/login** (correct)
2. ✅ `http://localhost/monitoring/grafana/login` → **200 OK** (loads login page)
3. ✅ `http://localhost/monitoring/grafana/api/health` → **200 OK** (health check works)
4. ✅ No redirect loop - URLs remain clean

### Expected Behavior

- Root `/monitoring/grafana/` redirects to `/monitoring/grafana/login`
- Login page loads without redirect loops
- All API endpoints work correctly
- Links within Grafana maintain `/monitoring/grafana/` prefix

## Files Changed

1. **`docker/grafana/grafana.ini`**
   - Changed `serve_from_sub_path = true` → `serve_from_sub_path = false`

2. **`docker-compose.yml`**
   - Changed `GF_SERVER_SERVE_FROM_SUB_PATH: "true"` → `GF_SERVER_SERVE_FROM_SUB_PATH: "false"`
   - **IMPORTANT**: Environment variables override config file settings!

3. **`docker/nginx/nginx.conf`**
   - Added rewrite rule to strip `/monitoring/grafana` prefix before proxying

## Related Documentation

- [Grafana Behind Reverse Proxy](https://grafana.com/tutorials/run-grafana-behind-a-proxy/)
- [Grafana Configuration - Server](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/#server)
- [Nginx Rewrite Module](http://nginx.org/en/docs/http/ngx_http_rewrite_module.html)

## Prevention

To avoid this issue in the future:

1. **Consistency is key**: Match nginx proxy behavior with Grafana's `serve_from_sub_path` setting
2. **Environment variables override config files**: Always check BOTH `docker-compose.yml` AND `grafana.ini`
3. **Choose one approach**:
   - **Option A** (Recommended): Strip subpath in nginx, set `serve_from_sub_path = false`
   - **Option B**: Pass full path in nginx, set `serve_from_sub_path = true`
4. **Never mix approaches**: Don't pass full path AND set `serve_from_sub_path = false`
5. **Test thoroughly**: Always test both direct URLs and in-app navigation after changes
6. **Document configuration**: Keep comments in sync with actual settings

### Configuration Priority in Grafana

Grafana reads configuration in this order (highest priority first):
1. **Environment variables** (`GF_*`) - HIGHEST PRIORITY
2. Command-line flags
3. Configuration file (`grafana.ini`)
4. Default values

**Key Takeaway**: Environment variables in `docker-compose.yml` will ALWAYS override `grafana.ini` settings!

## Architecture Pattern

This fix follows the **Path Normalization Pattern** for reverse proxies:

```
┌─────────┐  /monitoring/grafana/dashboard  ┌───────┐  /dashboard  ┌─────────┐
│ Browser │ ──────────────────────────────> │ Nginx │ ───────────> │ Grafana │
└─────────┘                                  └───────┘              └─────────┘
                                                 ↑                       │
                                                 │  root_url config      │
                                                 │  tells Grafana its    │
                                                 │  public path          │
                                                 └───────────────────────┘
```

**Benefits:**
- Clean separation of concerns
- Grafana doesn't need to know about reverse proxy details
- Easy to change proxy path without modifying Grafana
- Consistent with how other services (Prometheus, Tempo) are configured

## Status

✅ **FIXED** - Grafana is now accessible at `http://localhost/monitoring/grafana/` without redirect loops.

---

**Date Fixed:** December 6, 2025  
**Tested By:** Solution Architect  
**Severity:** High (Service Unavailable)  
**Resolution Time:** Immediate

