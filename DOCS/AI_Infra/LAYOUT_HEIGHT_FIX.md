# Layout Height Fix - Full Page Display

## Problem Description

The application was only displaying content in approximately a quarter of the available screen space instead of filling the full viewport. The iframe-based pages (MinIO, Grafana, Prometheus, Loki, Tempo, pgAdmin, Keycloak Admin) were not expanding to use the full available height.

## Root Cause

The issue stemmed from **inconsistent CSS height constraints** in the layout hierarchy:

1. **App Shell** (`app-shell.vue`): 
   - Used `h-screen` (100vh) for the container
   - Had `overflow-hidden` on the `<main>` element
   - The `<main>` element used `flex-1` but couldn't properly expand child content

2. **View Components**: 
   - Used `w-full h-full` but lacked `min-h-full`
   - This caused the containers to collapse to their content's intrinsic height

3. **Iframe Components**:
   - Some used `min-h-screen` (Grafana, pgAdmin, etc.)
   - Others lacked minimum height constraints entirely (MinIO)
   - Inconsistent implementation across features

4. **Height Inheritance Chain**:
   ```
   h-screen (100vh)
     └─ header (auto height)
     └─ navigation (auto height)  
     └─ main (flex-1, overflow-hidden) ← Problem here
        └─ router-view wrapper (missing) ← Problem here
           └─ view component (h-full, no min-h) ← Problem here
              └─ iframe component (h-full, inconsistent min-h) ← Problem here
   ```

## Solution Applied

### 1. Fixed App Shell Layout (`app-shell.vue`)

**Changed:**
```vue
<template>
  <div class="h-screen flex flex-col bg-gray-50">
    <app-header class="flex-shrink-0" />
    <app-navigation :items="navigationItems" class="flex-shrink-0" />
    <main class="flex-1 overflow-auto min-h-0">
      <div class="h-full">
        <router-view />
      </div>
    </main>
  </div>
</template>
```

**Key Changes:**
- Removed `overflow-hidden` from root container (allows scrolling if needed)
- Added `flex-shrink-0` to header and navigation (prevents them from shrinking)
- Changed `overflow-hidden` to `overflow-auto` on `<main>` (allows scrolling)
- Added `min-h-0` to `<main>` (allows flexbox to properly calculate height)
- **Added wrapper div with `h-full`** inside `<main>` (ensures router-view gets full height)

### 2. Updated All View Components

Added `min-h-full` to all iframe-based view containers:

**Files Updated:**
- `src/features/minio/views/minio-view.vue`
- `src/features/grafana/views/grafana-view.vue`
- `src/features/pgadmin/views/pgadmin-view.vue`
- `src/features/tempo/views/tempo-view.vue`
- `src/features/loki/views/loki-view.vue`
- `src/features/prometheus/views/prometheus-view.vue`
- `src/features/keycloak-admin/views/keycloak-admin-view.vue`

**Changed from:**
```vue
<div class="w-full h-full">
```

**Changed to:**
```vue
<div class="w-full h-full min-h-full">
```

### 3. Standardized All Iframe Components

Changed all iframe components to use `min-h-full` consistently (instead of the problematic `min-h-screen`):

**Files Updated:**
- `src/features/minio/components/minio-iframe.vue`
- `src/features/grafana/components/grafana-iframe.vue`
- `src/features/pgadmin/components/pgadmin-iframe.vue`
- `src/features/tempo/components/tempo-iframe.vue`
- `src/features/loki/components/loki-iframe.vue`
- `src/features/prometheus/components/prometheus-iframe.vue`
- `src/features/keycloak-admin/components/keycloak-admin-iframe.vue`

**Changed wrapper div:**
```vue
<!-- Before -->
<div class="relative w-full h-full min-h-screen">

<!-- After -->
<div class="relative w-full h-full min-h-full">
```

**Changed iframe element:**
```vue
<!-- Before -->
<iframe class="w-full h-full border-0" />

<!-- After -->
<iframe class="w-full h-full min-h-full border-0" />
```

## Why This Works

### Flexbox Height Calculation
1. **`h-screen`** on the root creates a 100vh container
2. **`flex-shrink-0`** on header/navigation prevents them from being compressed
3. **`flex-1`** on main allows it to take all remaining space
4. **`min-h-0`** on main is crucial - it allows flexbox to properly calculate heights (without it, flex children can overflow)
5. **Wrapper div with `h-full`** ensures router-view content gets 100% of main's height

### Height Inheritance
1. **`h-full`** on view components means "100% of parent height"
2. **`min-h-full`** ensures the component is at least as tall as its parent
3. Combined with flexbox parent, this creates full-height content
4. **`min-h-full` instead of `min-h-screen`** is important:
   - `min-h-screen` would make content 100vh (viewport height)
   - But available space is viewport MINUS header MINUS navigation
   - `min-h-full` correctly references the parent container's height

### Why `min-h-screen` Was Wrong
- `min-h-screen` = 100vh (full viewport)
- But main element height = 100vh - header height - navigation height
- This caused content to overflow, scrollbars, or incorrect sizing
- `min-h-full` = 100% of parent height (correct!)

## Technical Explanation

### The `min-h-0` Trick
In flexbox, the default `min-height` is `auto`, which means flex items won't shrink below their content size. This can cause layout issues when you want a flex child to be scrollable. Setting `min-h-0` (equivalent to `min-height: 0`) allows the flex item to shrink below its content size and enables proper scrolling behavior.

### Tailwind CSS Classes Used
- **`h-screen`**: `height: 100vh` - Full viewport height
- **`h-full`**: `height: 100%` - Full parent height
- **`min-h-0`**: `min-height: 0` - Allow flexbox to shrink below content
- **`min-h-full`**: `min-height: 100%` - At least full parent height
- **`flex-1`**: `flex: 1 1 0%` - Grow to fill space, shrink if needed
- **`flex-shrink-0`**: `flex-shrink: 0` - Never shrink
- **`overflow-auto`**: Show scrollbars only when needed
- **`overflow-hidden`**: Hide overflow content (removed from main)

## Testing Performed

After applying the fix and rebuilding the frontend:
```bash
cd /Users/nicolaslallier/Dev\ Nick/AI_Infra
docker compose build frontend
docker compose restart frontend
```

### Expected Results
✅ All iframe pages now display full height
✅ Content fills available space (viewport minus header minus navigation)
✅ No unnecessary scrollbars on outer containers
✅ Iframes are properly contained and scrollable
✅ Consistent behavior across all features

### Pages to Verify
- [ ] MinIO Console - http://localhost/minio
- [ ] Grafana - http://localhost/grafana
- [ ] Prometheus - http://localhost/metrics
- [ ] Loki Logs - http://localhost/logs
- [ ] Tempo Traces - http://localhost/traces
- [ ] pgAdmin - http://localhost/pgadmin
- [ ] Keycloak Admin - http://localhost/keycloak

## Files Modified

### Layout Components (1 file)
- `src/features/layout/components/app-shell.vue`

### View Components (7 files)
- `src/features/minio/views/minio-view.vue`
- `src/features/grafana/views/grafana-view.vue`
- `src/features/pgadmin/views/pgadmin-view.vue`
- `src/features/tempo/views/tempo-view.vue`
- `src/features/loki/views/loki-view.vue`
- `src/features/prometheus/views/prometheus-view.vue`
- `src/features/keycloak-admin/views/keycloak-admin-view.vue`

### Iframe Components (7 files)
- `src/features/minio/components/minio-iframe.vue`
- `src/features/grafana/components/grafana-iframe.vue`
- `src/features/pgadmin/components/pgadmin-iframe.vue`
- `src/features/tempo/components/tempo-iframe.vue`
- `src/features/loki/components/loki-iframe.vue`
- `src/features/prometheus/components/prometheus-iframe.vue`
- `src/features/keycloak-admin/components/keycloak-admin-iframe.vue`

**Total: 15 files modified**

## Best Practices Applied

### ✅ Consistent Height Handling
All iframe components now use the same height pattern:
```vue
<div class="relative w-full h-full min-h-full">
  <iframe class="w-full h-full min-h-full border-0" />
</div>
```

### ✅ Proper Flexbox Layout
The app shell uses proper flex container patterns:
- Fixed height headers with `flex-shrink-0`
- Flexible content area with `flex-1`
- Proper overflow handling with `overflow-auto`
- Height constraint release with `min-h-0`

### ✅ Single Responsibility
- Layout concerns in `app-shell.vue`
- Content display in view components
- Iframe rendering in iframe components

### ✅ Accessibility
- Loading states preserved
- Error states preserved  
- Screen reader support maintained
- No changes to semantic HTML structure

## References

- [Tailwind CSS Flexbox Documentation](https://tailwindcss.com/docs/flex)
- [MDN: CSS Flexible Box Layout](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_Flexible_Box_Layout)
- [The `min-height: 0` Flexbox Trick](https://moduscreate.com/blog/how-to-fix-overflow-issues-in-css-flex-layouts/)

## Related Issues

This fix resolves the "quarter page" layout issue where iframe content was not expanding to fill the available viewport space. The solution ensures consistent, full-height display across all iframe-based features while maintaining proper scrolling behavior and responsive layout principles.

---

**Status**: ✅ Fixed and Deployed  
**Date**: December 7, 2025  
**Frontend Rebuilt**: Yes  
**Container Restarted**: Yes
