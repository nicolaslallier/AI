# Troubleshooting: Script Argument Issue

## The Problem

When you ran:
```bash
./scripts/assign-user-groups.sh testuser DevOps
```

The script received strange numbers (20, 12, 61, etc.) instead of "DevOps".

## Possible Causes

1. **Hidden characters** in the command (copy/paste issue)
2. **Terminal encoding issue**
3. **Shell alias or function** interfering
4. **Script file corruption**

## Solutions to Try

### Solution 1: Type the command manually (don't copy/paste)

Make sure to type it character by character:

```bash
./scripts/assign-user-groups.sh testuser DevOps
```

### Solution 2: Use quotes around the group name

```bash
./scripts/assign-user-groups.sh testuser "DevOps"
```

### Solution 3: Use the role assignment script instead

This might work better:

```bash
./scripts/assign-user-roles.sh testuser ROLE_DEVOPS
```

### Solution 4: Debug what the script is receiving

Run this to see what arguments are being passed:

```bash
./scripts/debug-args.sh testuser DevOps
```

This will show you exactly what the script sees.

### Solution 5: Check for shell aliases

```bash
type assign-user-groups.sh
alias | grep assign
```

If there's an alias, unset it:

```bash
unalias assign-user-groups.sh
```

### Solution 6: Run with bash explicitly

```bash
bash ./scripts/assign-user-groups.sh testuser DevOps
```

### Solution 7: Check the script file

Make sure the script wasn't corrupted:

```bash
file scripts/assign-user-groups.sh
head -5 scripts/assign-user-groups.sh
```

## Quick Workaround: Use Roles Instead of Groups

If the group assignment continues to fail, you can assign roles directly:

```bash
# For DevOps access:
./scripts/assign-user-roles.sh testuser ROLE_DEVOPS

# For Database Admin access:
./scripts/assign-user-roles.sh testuser ROLE_DBA

# For Monitoring access:
./scripts/assign-user-roles.sh testuser ROLE_READONLY_MONITORING

# For all access:
./scripts/assign-user-roles.sh testuser ROLE_DBA ROLE_DEVOPS ROLE_READONLY_MONITORING
```

## Expected Output

When working correctly, you should see:

```
═══════════════════════════════════════════════════════
   Keycloak Group Assignment Script
═══════════════════════════════════════════════════════

Target User: testuser
Groups to assign:
  • DevOps

1️⃣  Getting admin access token...
✅ Access token obtained
2️⃣  Looking up user: testuser
✅ User found (ID: ...)
3️⃣  Fetching available groups...
4️⃣  Assigning groups...

  Assigning group: DevOps
    ✅ Added to group successfully
```

## Please Try This First

**Run the debug script to see what's happening:**

```bash
./scripts/debug-args.sh testuser DevOps
```

Then share the output so we can see what's being passed to the script.

## Alternative: Use Direct Role Assignment

Since groups might have an issue, use the role script which should work:

```bash
# Grant DevOps permissions
./scripts/assign-user-roles.sh testuser ROLE_DEVOPS

# Verify it worked
./scripts/list-keycloak-users.sh
```

This will give you the same permissions as the DevOps group.

