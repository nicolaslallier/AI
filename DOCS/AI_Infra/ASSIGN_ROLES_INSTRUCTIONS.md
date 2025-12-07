# How to Assign Roles to Your User - Step by Step

## Current Situation

You've lost access to the Keycloak admin console menu, but you need to assign roles to your user. Here's how to do it using the command-line scripts.

## Step 1: Find Your Username

First, let's see what users exist in the system:

```bash
./scripts/list-keycloak-users.sh
```

This will show you all users with their current roles and groups.

## Step 2: Choose Your Approach

You have two options:

### Option A: Assign Groups (Recommended)

Groups are easier to manage and automatically grant the associated roles:

```bash
# For a developer/DevOps user:
./scripts/assign-user-groups.sh <your-username> DevOps

# For a database administrator:
./scripts/assign-user-groups.sh <your-username> DBAs DevOps

# For full admin access (all permissions):
./scripts/assign-user-groups.sh <your-username> DBAs DevOps Monitoring
```

### Option B: Assign Roles Directly

For more granular control:

```bash
# DevOps access:
./scripts/assign-user-roles.sh <your-username> ROLE_DEVOPS

# Database admin + DevOps:
./scripts/assign-user-roles.sh <your-username> ROLE_DBA ROLE_DEVOPS

# Full access (all roles):
./scripts/assign-user-roles.sh <your-username> ROLE_DBA ROLE_DEVOPS ROLE_READONLY_MONITORING
```

## Step 3: Complete Examples

Replace `<your-username>` with your actual username from Step 1:

### If your username is "admin":
```bash
./scripts/assign-user-groups.sh admin DBAs DevOps Monitoring
```

### If your username is "nicolas" or "nicolaslallier":
```bash
./scripts/assign-user-groups.sh nicolas DBAs DevOps Monitoring
```

### If your username is "testuser":
```bash
./scripts/assign-user-groups.sh testuser DevOps
```

## Step 4: Verify the Assignment

After running the command, verify it worked:

```bash
./scripts/list-keycloak-users.sh | grep -A 10 "<your-username>"
```

Or list all users again to see the changes:

```bash
./scripts/list-keycloak-users.sh
```

## Quick Command Template

**Copy this and replace `<your-username>`**:

```bash
# For full admin access (recommended):
./scripts/assign-user-groups.sh <your-username> DBAs DevOps Monitoring

# Then verify:
./scripts/list-keycloak-users.sh
```

## What Each Group/Role Grants

| Group/Role | Access |
|------------|--------|
| **DBAs** / ROLE_DBA | Full pgAdmin access, database management |
| **DevOps** / ROLE_DEVOPS | Prometheus, Grafana, infrastructure monitoring |
| **Monitoring** / ROLE_READONLY_MONITORING | Read-only monitoring dashboards |

## Troubleshooting

### "User not found"
- Run `./scripts/list-keycloak-users.sh` to see exact usernames
- Check spelling and case (usernames are case-sensitive)

### "Failed to get admin access token"
- Make sure Keycloak is running: `docker ps | grep keycloak`
- Verify it's accessible: `curl http://localhost/auth`

### Need to create a new user first?
```bash
./scripts/create-test-user.sh <username> <password>
# Example:
./scripts/create-test-user.sh nicolas SecurePass123!
```

## After Assignment

Once roles are assigned, you can:
1. Login at **http://localhost/home**
2. Access services based on your roles:
   - pgAdmin: http://localhost/pgadmin/ (requires ROLE_DBA)
   - Grafana: http://localhost/monitoring/grafana/ (requires ROLE_DEVOPS or ROLE_READONLY_MONITORING)

## Need Help?

See full documentation:
- **KEYCLOAK_USER_MANAGEMENT.md** - Complete guide
- **QUICK_REFERENCE_USER_MANAGEMENT.md** - Quick reference
- **KEYCLOAK_SCRIPTS_SUMMARY.md** - Detailed script documentation

