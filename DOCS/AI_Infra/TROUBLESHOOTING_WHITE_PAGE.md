# Troubleshooting: White Page After Login

## Issue
After successful Keycloak login, the page shows white/blank and gets stuck in a redirect loop.

## Symptoms
- Frontend logs show continuous requests: `/home` → `/auth/...` → `/token` → `/home` (repeat)
- Browser shows blank white page
- Network tab shows 200 OK responses but infinite redirects

## Root Cause Analysis

The issue is an **authentication redirect loop** in the Vue application. Possible causes:

### 1. Token Exchange Failure
The frontend successfully gets the authorization code but fails to exchange it for tokens, causing it to retry authentication.

### 2. Token Storage Issue
Tokens are obtained but not properly stored, making the app think the user is still unauthenticated.

### 3. Router Guard Loop
Vue Router navigation guard keeps redirecting to login because it doesn't recognize the user as authenticated.

### 4. JavaScript Error
A runtime error prevents the application from rendering after authentication.

## Debugging Steps

### Step 1: Check Browser Console

Open browser DevTools (F12) and look for:

```
Console Tab:
  ❌ JavaScript errors (red text)
  ⚠️  Warnings about CORS, tokens, or authentication
  📋 Look for Keycloak-related messages
```

Common errors to look for:
- `TypeError: Cannot read property 'token' of undefined`
- `CORS policy: No 'Access-Control-Allow-Origin' header`
- `Failed to parse token`
- `Uncaught ReferenceError`

### Step 2: Check Network Tab

In DevTools → Network tab:

1. **Filter by XHR** to see API calls
2. Look for the `/token` request
3. Check if it returns **200 OK** with `access_token` in response
4. Look for any **401**, **403**, or **5xx** errors

Example of successful token response:
```json
{
  "access_token": "eyJhbGc...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "eyJhbGc...",
  "id_token": "eyJhbGc..."
}
```

### Step 3: Check Local Storage

In DevTools → Application → Local Storage → `http://localhost`:

Look for:
- `keycloak_token`
- `keycloak_refreshToken`
- `keycloak_idToken`
- Or similar keys where tokens should be stored

If these are **missing or empty**, the application isn't storing tokens correctly.

### Step 4: Enable Keycloak Debug Mode

The frontend should have Keycloak debug enabled during development.

Check if `VITE_KEYCLOAK_DEBUG` is set to `true` in the build:

```bash
docker exec ai_infra_frontend sh -c "cd /usr/share/nginx/html && grep -o 'KEYCLOAK_DEBUG.*true' assets/*.js"
```

If debug is enabled, you'll see detailed Keycloak logs in the console.

## Quick Fixes

### Fix 1: Check Token Storage

The application might not be saving tokens. Check the frontend authentication service:

```bash
# Look for token storage code in the frontend
docker exec ai_infra_frontend sh -c "cd /usr/share/nginx/html && grep -o 'localStorage.setItem.*token' assets/*.js"
```

### Fix 2: Verify Redirect URI

Ensure the redirect URI matches exactly:

```bash
# The redirect_uri in the auth request should be:
http://localhost/home

# NOT:
http://localhost:8080/home  # ❌ Wrong port
http://localhost/  # ❌ Missing path
https://localhost/home  # ❌ Wrong protocol
```

### Fix 3: Clear Browser Storage

Sometimes old/corrupt data causes issues:

1. Open DevTools (F12)
2. Go to **Application** tab
3. Click **Clear storage**
4. Check all boxes
5. Click **Clear site data**
6. Hard refresh: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)

### Fix 4: Check for CORS Issues

If you see CORS errors, check Keycloak client configuration:

```bash
# Get admin token
TOKEN=$(curl -s -X POST "http://localhost/auth/realms/master/protocol/openid-connect/token" \
  -d "username=admin" \
  -d "password=admin" \
  -d "grant_type=password" \
  -d "client_id=admin-cli" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

# Check client web origins
curl -s -X GET "http://localhost/auth/admin/realms/infra-admin/clients?clientId=ai-front-spa" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -m json.tool | grep -A 3 "webOrigins"
```

Should show:
```json
"webOrigins": [
  "http://localhost",
  "+"
]
```

## Potential Solutions

### Solution 1: Frontend Code Issue

The frontend Vue application might have a bug in the authentication flow. Check:

```typescript
// Common issue: Not handling authentication callback correctly
router.beforeEach(async (to, from, next) => {
  if (to.path !== '/login') {
    // BUG: This might cause infinite redirect if auth state isn't properly checked
    if (!keycloak.authenticated) {
      await keycloak.login();  // ← This redirects, but might loop
      return;
    }
  }
  next();
});
```

**Fix**: Add proper state management:
```typescript
router.beforeEach(async (to, from, next) => {
  // Don't redirect if we're in the middle of authentication callback
  if (to.query.code || to.query.state) {
    next();  // Let the auth callback complete
    return;
  }
  
  if (to.path !== '/login' && !keycloak.authenticated) {
    await keycloak.login({ redirectUri: window.location.origin + to.path });
    return;
  }
  next();
});
```

### Solution 2: Keycloak Configuration

Check if the Keycloak adapter is properly initialized:

```typescript
// Ensure init is completed before mounting app
keycloak.init({
  onLoad: 'login-required',
  checkLoginIframe: false,  // Disable iframe checking
  pkceMethod: 'S256',
  flow: 'standard'
}).then((authenticated) => {
  if (authenticated) {
    // Mount Vue app only after authentication succeeds
    app.mount('#app');
  }
});
```

### Solution 3: Disable Silent Check SSO

Silent check SSO can cause redirect loops:

```typescript
keycloak.init({
  onLoad: 'check-sso',
  silentCheckSsoRedirectUri: window.location.origin + '/silent-check-sso.html',
  checkLoginIframe: false  // ← Disable this to prevent loops
});
```

## Testing

After applying fixes:

1. **Clear all browser data** (DevTools → Application → Clear storage)
2. **Hard refresh** the page (`Ctrl+Shift+R` or `Cmd+Shift+R`)
3. **Try logging in again**
4. **Check Console for errors**
5. **Verify Local Storage has tokens**

## Need Frontend Source Code?

If the issue persists, we need to examine the frontend source code:

```bash
# Check if frontend source is available
ls -la /Users/nicolaslallier/Dev\ Nick/AI_Infra/frontend/ai-front/src/
```

Specifically, look at:
- `src/main.ts` - App initialization and Keycloak setup
- `src/router/index.ts` - Router guards
- `src/core/keycloak/` - Keycloak integration code
- `src/stores/auth.ts` - Authentication state management

## Emergency Bypass (Development Only)

For testing purposes, you can temporarily disable authentication:

### Option 1: Access root path
Try accessing `http://localhost/` instead of `http://localhost/home`

### Option 2: Add unauthenticated route
If there's a public route like `/login` or `/about`, try that first.

## Expected vs Actual Flow

### Expected Flow ✅
```
1. User → http://localhost/home
2. App detects: Not authenticated
3. Redirect to Keycloak
4. User logs in
5. Keycloak redirects back with code
6. App exchanges code for tokens
7. App stores tokens
8. App renders /home page
9. User sees content ✅
```

### Actual Flow (Problem) ❌
```
1. User → http://localhost/home
2. App detects: Not authenticated
3. Redirect to Keycloak
4. User logs in
5. Keycloak redirects back with code
6. App exchanges code for tokens ✅
7. App stores tokens (maybe ❓)
8. App checks auth status → Not authenticated ❌
9. Redirect to Keycloak again
10. Loop continues infinitely 🔄
```

The break is somewhere between steps 7-8.

## Next Steps

Please provide:
1. **Browser console errors** (if any)
2. **Network tab** screenshot showing the /token request/response
3. **Local Storage** contents for `http://localhost`
4. Any **JavaScript errors** in the console

This will help pinpoint the exact issue.

---

**Status**: 🔍 **INVESTIGATING**
**Priority**: **High** - Blocking user access
**Date**: December 6, 2025


