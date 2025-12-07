# Keycloak Login Loop Fix

## Issue Summary

**Date**: December 6, 2025  
**Reporter**: User experiencing issues on home page  
**Root Cause**: Authentication callback race condition causing login loops

---

## Problem Description

### Symptoms
1. **Repeated LOGIN events** in Keycloak logs (21:41:50 and 21:42:52)
2. **White page or loading loop** on the frontend
3. **Application never fully loading** after authentication
4. **Constant redirects** between app and Keycloak

### Root Cause
The authentication callback handler (`auth-callback-view.vue`) had a **race condition**:

```typescript
// OLD CODE - PROBLEMATIC
await new Promise((resolve) => setTimeout(resolve, 1000));

if (auth.isAuthenticated.value) {
  // Redirect to home
}
```

**Problems:**
1. **Hard-coded 1-second wait** - insufficient for slow Keycloak responses
2. **Single check** - no retry mechanism if Keycloak takes longer
3. **Race condition** - might check before Keycloak finishes token exchange
4. **False negatives** - redirects to `/home` even if not authenticated
5. **Loop trigger** - `/home` requires auth, triggers another login

### Flow of the Bug

```
1. User logs in → Keycloak redirect
2. Callback component loads
3. Waits 1 second (hard-coded)
4. Checks auth status → NOT YET READY
5. Redirects to /home
6. /home requires auth → triggers login
7. REPEAT (infinite loop)
```

---

## Solution Implemented

### 1. Improved Auth Callback with Polling

**File**: `AI_Front/src/features/auth/views/auth-callback-view.vue`

**Changes:**
- Replaced hard-coded 1-second wait with **intelligent polling**
- Added **retry mechanism** (20 attempts × 500ms = 10 seconds max)
- Added **progress logging** for debugging
- Added **session cleanup** on failure to prevent loops

**NEW CODE:**
```typescript
// Wait for authentication to complete with polling (max 10 seconds)
const maxAttempts = 20; // 20 attempts * 500ms = 10 seconds max
let attempts = 0;

while (attempts < maxAttempts) {
  // Check if user is authenticated
  if (auth.isAuthenticated.value) {
    Logger.info('Authentication successful, redirecting to intended route');
    
    // Get intended route or default to home
    const intendedRoute = getAndClearIntendedRoute() || '/home';
    
    // Redirect to intended destination
    await router.push(intendedRoute);
    return;
  }

  // Wait 500ms before next check
  await new Promise((resolve) => setTimeout(resolve, 500));
  attempts++;
  
  if (attempts % 4 === 0) {
    Logger.info(`Still waiting for authentication... (${attempts}/20)`);
  }
}
```

### 2. Added Session Cleanup on Failure

```typescript
// Clear any stored session to prevent loops
try {
  sessionStorage.removeItem('kc_session');
} catch {
  // Ignore storage errors
}
```

This ensures that if authentication fails, we don't keep trying with stale tokens.

---

## Testing Performed

### Before Fix
- ✗ Repeated LOGIN events in Keycloak logs
- ✗ White page after login
- ✗ Infinite redirect loop

### After Fix
- ✅ Single LOGIN event
- ✅ Successful authentication
- ✅ Proper redirect to intended route
- ✅ No loops detected

---

## Additional Fixes (Bonus)

### Health Check Fix for Docker Containers

**Issue**: `nginx` and `frontend` containers showing as "unhealthy"  
**Cause**: Health checks using `localhost` which doesn't resolve in Alpine containers  
**Fix**: Changed to `127.0.0.1`

**File**: `AI_Infra/docker-compose.yml`

**Changes:**
```yaml
# BEFORE
test: ["CMD", "wget", "--spider", "-q", "http://localhost:80/health"]

# AFTER
test: ["CMD", "wget", "--spider", "-q", "http://127.0.0.1:80/health"]
```

**Result**: Both containers now show as **(healthy)**

---

## Architecture Insights

### Why This Happened

1. **Asynchronous OAuth2/OIDC Flow**: 
   - Token exchange happens asynchronously
   - JavaScript callback must wait for completion

2. **Keycloak JavaScript Adapter**:
   - Processes authorization code automatically
   - Timing varies based on network and server load

3. **SPA Architecture**:
   - Single-page app must handle all auth states
   - Race conditions common between init and callback

### Best Practices Implemented

✅ **Polling with timeout** - More reliable than hard-coded waits  
✅ **Progress logging** - Helps debugging authentication issues  
✅ **Session cleanup** - Prevents stale state from causing loops  
✅ **Graceful degradation** - Shows error messages instead of silently failing  
✅ **Defensive programming** - Handles edge cases and failures

---

## Verification Steps

To verify the fix is working:

1. **Clear browser cache** and cookies for `localhost`
2. **Open browser console** (F12) to see logs
3. **Navigate to** `http://localhost/home`
4. **Observe**: Should redirect to Keycloak login
5. **Login** with `testuser` credentials
6. **Observe**: Should redirect back and load home page (no loop)
7. **Check Keycloak logs**: Should show only ONE LOGIN event

### Expected Console Logs

```
[INFO] Initializing authentication system...
[INFO] Processing authentication callback...
[INFO] Still waiting for authentication... (4/20)
[INFO] Authentication successful, redirecting to intended route
[INFO] Navigation from: auth-callback to: home
```

### Expected Keycloak Logs

```
type="LOGIN", ... username="testuser" ... ✅
type="CODE_TO_TOKEN", ... ✅
(NO repeated LOGIN events)
```

---

## Files Changed

### Frontend (AI_Front)
- `src/features/auth/views/auth-callback-view.vue` - **Improved callback handling**

### Infrastructure (AI_Infra)  
- `docker-compose.yml` - **Fixed health checks**

---

## Related Documentation

- [KEYCLOAK_IMPLEMENTATION_SUMMARY.md](../AI_Front/KEYCLOAK_IMPLEMENTATION_SUMMARY.md)
- [AUTHENTICATION.md](../AI_Front/docs/AUTHENTICATION.md)
- [FR-FE-KC-003](../AI_Front/docs/AUTHENTICATION.md#login-flow) - Login flow specification

---

## Prevention

To prevent similar issues in the future:

### Code Review Checklist
- [ ] No hard-coded timeouts for async operations
- [ ] Proper retry/polling mechanisms for external services
- [ ] Comprehensive error handling with cleanup
- [ ] Progress logging for long-running operations
- [ ] Testing with slow network conditions

### Testing Recommendations
- Test with network throttling (slow 3G)
- Test with Keycloak under load
- Test session expiration scenarios
- Test with browser cache disabled
- Monitor Keycloak logs during testing

---

## Status

**RESOLVED** ✅

**Deployed**: December 6, 2025  
**Verified**: Authentication working correctly  
**No further action required**

---

## Contact

For questions about this fix, refer to:
- Authentication implementation: `AI_Front/src/core/auth/`
- Keycloak configuration: `AI_Infra/docker/keycloak/`
- OAuth2/OIDC spec: [RFC 6749](https://tools.ietf.org/html/rfc6749)

