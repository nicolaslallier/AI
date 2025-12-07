# Quick Fix: Grafana "Too Many Redirects" Error

## The Problem
`http://localhost/monitoring/grafana/` shows "too many redirects" error

## The Solution (30 seconds)

### Option 1: Use the Fix Script (Easiest)

```bash
./scripts/fix-grafana-redirects.sh
```

This script will:
- Stop Grafana and Nginx
- Restart them with the fixed configuration
- Verify everything is working

### Option 2: Manual Restart

```bash
# Stop the services
docker-compose stop grafana nginx

# Start them again
docker-compose up -d grafana nginx

# Wait 10-15 seconds, then test
```

### Option 3: Quick Restart

```bash
docker-compose restart grafana nginx
```

## Test It

1. Wait 10-15 seconds for Grafana to start
2. Open: **http://localhost/monitoring/grafana/**
3. You should see the login page (no redirect error!)
4. Login with: **admin** / **admin**

## What Was Fixed?

Changed Grafana configuration from:
- ❌ `serve_from_sub_path = false` (caused redirect loops)
- ✅ `serve_from_sub_path = true` (works perfectly)

Files changed:
- `docker/grafana/grafana.ini`
- `docker-compose.yml`
- `docker/nginx/nginx.conf`

## Still Having Issues?

### Clear Browser Cache
- **Chrome**: Ctrl+Shift+Delete → Clear cached images and files
- **Firefox**: Ctrl+Shift+Delete → Cached Web Content
- **Or use incognito/private mode**

### Check Logs
```bash
docker logs ai_infra_grafana --tail 50
docker logs ai_infra_nginx --tail 50
```

### Full Restart
```bash
docker-compose down
docker-compose up -d
```

## More Details

See **GRAFANA_REDIRECT_LOOP_FIX.md** for complete technical explanation.

