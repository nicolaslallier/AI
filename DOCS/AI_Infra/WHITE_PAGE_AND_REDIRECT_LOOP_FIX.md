# White Page & Redirect Loop Fix

## Issue Summary

**Date**: December 6, 2025  
**Symptoms**: 
1. White/blank page on frontend
2. Infinite redirect loop
3. Rapid-fire Keycloak authentication requests
4. Browser console may show errors or just white screen

---

## Root Causes (Multiple Issues)

### Issue #1: Wrong Keycloak URL Default ✅ FIXED

**File**: `AI_Front/src/core/config/index.ts`

**Problem**:
```typescript
// ❌ WRONG - Falls back to direct Keycloak port
url: import.meta.env.VITE_KEYCLOAK_URL || 'http://localhost:8080',
```

**Why it failed**:
- Browser tries to connect to `localhost:8080` (Keycloak's internal port)
- Port 8080 is **not exposed** to the browser (only accessible internally)
- Connection fails silently
- No authentication → white page
- No Keycloak logs because it never reaches Keycloak

**Fix**:
```typescript
// ✅ CORRECT - Uses nginx reverse proxy
url: import.meta.env.VITE_KEYCLOAK_URL || 'http://localhost/auth',
```

---

### Issue #2: SSO Redirect Loop ✅ FIXED

**File**: `AI_Front/src/core/auth/keycloak-service.ts`

**Problem**:
```typescript
// ❌ WRONG - No redirect URI for SSO checks
const initOptions: KeycloakInitOptions = {
  pkceMethod: 'S256',
  onLoad: 'check-sso', // ← Problem: redirects to current page
  checkLoginIframe: false,
};
```

**Why it caused infinite loop**:
1. App loads `/home`
2. Keycloak init with `check-sso` finds existing session
3. **Redirects back to `/home`** (current page) instead of `/auth/callback`
4. App reloads and reinitializes
5. Keycloak finds session again
6. **INFINITE LOOP**

**Symptoms**:
- Dozens/hundreds of requests per second
- Browser freezes or shows white page
- Nginx logs show rapid-fire requests:
  ```
  POST /auth/.../token HTTP/1.1" 200
  GET /auth/.../auth?client_id=... HTTP/1.1" 302
  GET /home HTTP/1.1" 200
  (REPEAT INFINITELY)
  ```

**Fix**:
```typescript
// ✅ CORRECT - Explicit redirect URI for SSO
const initOptions: KeycloakInitOptions = {
  pkceMethod: 'S256',
  onLoad: 'check-sso',
  silentCheckSsoRedirectUri: window.location.origin + '/auth/callback', // ← Fix
  checkLoginIframe: false,
};
```

This ensures that when Keycloak performs a silent SSO check, it redirects to `/auth/callback` instead of the current page, breaking the loop.

---

### Issue #3: Auth Callback Race Condition ✅ FIXED (Earlier)

**File**: `AI_Front/src/features/auth/views/auth-callback-view.vue`

**Problem**: Hard-coded 1-second wait insufficient for Keycloak token exchange

**Fix**: Polling mechanism with 10-second timeout

---

### Issue #4: Docker Health Checks Failing ✅ FIXED (Earlier)

**File**: `AI_Infra/docker-compose.yml`

**Problem**: Health checks using `localhost` instead of `127.0.0.1`

**Fix**: Changed to `127.0.0.1` for Alpine container compatibility

---

## How to Reproduce (For Testing)

### Reproduce Issue #1 (Wrong URL)
1. Set Keycloak URL default to `http://localhost:8080`
2. Build frontend without `VITE_KEYCLOAK_URL` env var
3. Open browser → White page, no Keycloak logs

### Reproduce Issue #2 (Redirect Loop)
1. Login successfully once (creates Keycloak session)
2. Use `check-sso` without `silentCheckSsoRedirectUri`
3. Navigate to `/home` → Infinite loop

---

## Solution Summary

### Files Changed

1. **`AI_Front/src/core/config/index.ts`**
   - Changed Keycloak URL default from `:8080` to `/auth`

2. **`AI_Front/src/core/auth/keycloak-service.ts`**
   - Added `silentCheckSsoRedirectUri` to prevent SSO redirect loops

3. **`AI_Front/src/features/auth/views/auth-callback-view.vue`** (Earlier)
   - Improved callback polling mechanism

4. **`AI_Infra/docker-compose.yml`** (Earlier)
   - Fixed health checks for Alpine containers

---

## How to Fix for Users

If you're experiencing the white page or redirect loop:

### Step 1: Clear Browser Storage

Open browser console (F12) and run:

```javascript
sessionStorage.clear();
localStorage.clear();
```

### Step 2: Hard Refresh

- **Windows/Linux**: `Ctrl + Shift + R`
- **Mac**: `Cmd + Shift + R`

### Step 3: Verify Fix

1. Navigate to `http://localhost/home`
2. Should redirect to Keycloak login (if not logged in)
3. Login with credentials
4. Should redirect to `/auth/callback` briefly
5. Then redirect to `/home` and show the app
6. **NO loop**

---

## Verification Steps

### Check if redirect loop is fixed:

```bash
# Watch nginx logs for rapid requests
docker logs ai_infra_nginx --tail 50 --follow

# Should see NORMAL pattern:
# GET /home → 200
# (Maybe redirect to Keycloak login)
# POST /auth/.../token → 200
# GET /auth/callback → 200
# GET /home → 200
# (STOPS - no loop)
```

### Check if Keycloak is accessible:

```bash
curl http://localhost/auth/realms/infra-admin/.well-known/openid-configuration
# Should return JSON with Keycloak config
```

### Check if frontend has correct URL:

```bash
docker exec ai_infra_frontend cat /usr/share/nginx/html/assets/index-*.js | grep -o "http://localhost/auth"
# Should find "http://localhost/auth"
```

---

## Prevention

### For Developers

✅ **Always set explicit defaults** for critical config:
```typescript
// GOOD
url: import.meta.env.VITE_KEYCLOAK_URL || 'http://localhost/auth',

// BAD
url: import.meta.env.VITE_KEYCLOAK_URL || 'http://localhost:8080',
```

✅ **Always specify redirect URIs** for SSO:
```typescript
// GOOD
{
  onLoad: 'check-sso',
  silentCheckSsoRedirectUri: window.location.origin + '/auth/callback',
}

// BAD
{
  onLoad: 'check-sso',
  // Missing silentCheckSsoRedirectUri
}
```

✅ **Test with existing sessions**:
- Don't just test fresh logins
- Test with browser already authenticated
- Test page refreshes
- Test direct URL navigation

### Code Review Checklist

- [ ] All auth-related URLs use nginx proxy (`/auth`), not direct ports
- [ ] SSO initialization includes `silentCheckSsoRedirectUri`
- [ ] Callback handler has polling/retry mechanism
- [ ] No hard-coded timeouts for async operations
- [ ] Browser storage cleared in error cases

---

## Architecture Notes

### Why These Issues Happened

1. **Nginx Reverse Proxy Complexity**:
   - Keycloak runs on `keycloak:8080` internally
   - Browser accesses via `localhost/auth` (nginx proxy)
   - Easy to accidentally use wrong URL

2. **OAuth2/OIDC Flow Complexity**:
   - Multiple redirect steps
   - Session state across page loads
   - Silent token refresh
   - Easy to create redirect loops

3. **SPA Architecture**:
   - Client-side routing
   - Page reloads trigger full auth check
   - Browser session storage
   - Race conditions possible

### Best Practices

✅ **Always use nginx proxy URLs** in browser-facing code  
✅ **Explicit redirect URIs** for all OAuth flows  
✅ **Polling mechanisms** for async operations  
✅ **Session cleanup** on errors  
✅ **Defensive programming** - assume network delays  

---

## Related Documentation

- [KEYCLOAK_LOGIN_LOOP_FIX.md](./KEYCLOAK_LOGIN_LOOP_FIX.md) - Previous auth callback fix
- [KEYCLOAK_URL_FIX.md](./KEYCLOAK_URL_FIX.md) - Nginx proxy configuration
- [AUTHENTICATION.md](../AI_Front/docs/AUTHENTICATION.md) - Full auth spec
- [OAuth 2.0 RFC 6749](https://tools.ietf.org/html/rfc6749)
- [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html)

---

## Status

**RESOLVED** ✅

**Deployed**: December 6, 2025  
**Verified**: Authentication working without loops  
**Action Required**: Users must clear browser storage

---

## Quick Fix Commands

```bash
# Rebuild and restart frontend
cd AI_Front && npm run build
cd ../AI_Infra
docker-compose build frontend
docker-compose up -d --force-recreate frontend

# Wait 10 seconds for health check
sleep 10

# Verify deployment
docker ps | grep frontend  # Should show (healthy)
curl -I http://localhost/home  # Should return 200 OK

# Check Keycloak accessibility
curl http://localhost/auth/realms/infra-admin/.well-known/openid-configuration | jq .issuer
# Should show: "http://localhost/auth/realms/infra-admin"
```

Then in **browser**:
1. Open console (F12)
2. Run: `sessionStorage.clear(); localStorage.clear();`
3. Hard refresh: Ctrl+Shift+R (or Cmd+Shift+R on Mac)
4. Navigate to `http://localhost/home`

---

## Contact

For questions about this fix:
- OAuth2/OIDC flows: See RFC 6749
- Keycloak configuration: See `docker/keycloak/realm-export.json`
- Frontend auth: See `AI_Front/src/core/auth/`

