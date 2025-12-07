# Grafana Access Loss - Quick Fix Guide

## Problem
**Every time you recreate the infrastructure, you lose access to Grafana.**

## Root Cause
Grafana stores admin credentials in its persistent volume (`grafana_data`). The environment variable `GF_SECURITY_ADMIN_PASSWORD` only works on **first startup**. After that, Grafana ignores it and uses the password stored in its database.

## Quick Solutions

### 🚀 Option 1: Quick Restart (Fastest)
```bash
make reset-grafana
```
Or manually:
```bash
docker-compose restart grafana
# Wait 10 seconds
# Clear browser cookies for localhost
```

### 🔥 Option 2: Full Reset (Recommended)
```bash
make reset-grafana-full
```
Or manually:
```bash
docker-compose stop grafana
docker volume rm ai_infra_grafana_data
docker-compose up -d grafana
# Wait 30 seconds
```

**After full reset, login with:**
- Username: `admin`
- Password: `admin`

### 🔑 Option 3: Reset Password Only
```bash
make reset-grafana-password
```
Or manually:
```bash
docker exec -it ai_infra_grafana grafana-cli admin reset-admin-password admin
docker-compose restart grafana
```

### 🌐 Option 4: Clear Browser Cookies
If you get "Invalid session" or redirect errors:

1. Open DevTools (F12)
2. Go to Application/Storage tab
3. Clear all cookies for `localhost`
4. Clear localStorage for `localhost`
5. Refresh page and try again

## When Recreating Infrastructure

### Development: Always Clean Volumes
```bash
# ALWAYS use this for clean start:
docker-compose down -v
docker-compose up -d

# Or use make commands:
make clean
make all-up
```

### Production: Persistent Data
See `GRAFANA_ACCESS_LOSS_FIX.md` for Keycloak OAuth integration (Solution 3).

## Verification

Check if Grafana is working:
```bash
make grafana-health
# Or:
curl http://localhost/monitoring/grafana/api/health
```

Expected output:
```json
{
  "commit": "...",
  "database": "ok",
  "version": "..."
}
```

## Troubleshooting Commands

```bash
# Check Grafana logs
make grafana-logs

# Check container status
docker ps | grep grafana

# Verify health endpoint
curl -v http://localhost/monitoring/grafana/api/health

# Test login page
curl -v http://localhost/monitoring/grafana/login
```

## Why This Happens

1. **First Start**: Grafana reads `GF_SECURITY_ADMIN_PASSWORD` and creates admin user
2. **Subsequent Starts**: Grafana uses password from database, ignores env var
3. **Volume Recreation**: Password is lost because it's stored in volume
4. **Result**: You can't login because the password in the volume differs from what you expect

## Prevention

### For Development
Always use clean volumes:
```bash
# Add this to your workflow
docker-compose down -v && docker-compose up -d
```

### For Production
Implement Keycloak OAuth (see `GRAFANA_ACCESS_LOSS_FIX.md`) for:
- Centralized authentication
- SSO across all services
- No more password issues

## Quick Reference

| Command | What It Does | When to Use |
|---------|--------------|-------------|
| `make reset-grafana` | Restart container | Quick fix, least disruptive |
| `make reset-grafana-full` | Delete volume + recreate | Complete reset, loses all data |
| `make reset-grafana-password` | Reset password to 'admin' | Keep data, just reset password |
| `make grafana-logs` | View logs | Debug issues |
| `make grafana-health` | Check if responding | Verify it's working |

## Still Not Working?

1. **Clear browser cache completely**
2. **Check nginx logs**: `docker logs ai_infra_nginx`
3. **Verify nginx config**: `docker exec ai_infra_nginx cat /etc/nginx/nginx.conf`
4. **Check Grafana startup**: `docker logs ai_infra_grafana | grep -i error`
5. **Read full solution guide**: `GRAFANA_ACCESS_LOSS_FIX.md`

---

**TL;DR:**
```bash
# Lost access to Grafana? Run this:
make reset-grafana-full

# Then login with: admin/admin
```

