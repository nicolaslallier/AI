# Keycloak User Management Guide

This guide explains how to manage users, roles, and groups in Keycloak using the provided scripts.

## Quick Start

### 1. List All Users

To see all users and their current roles/groups:

```bash
./scripts/list-keycloak-users.sh
```

This will show:
- Username, email, and enabled status
- All assigned roles
- All assigned groups

### 2. Assign Roles to a User

To assign one or more roles to a user:

```bash
./scripts/assign-user-roles.sh <username> <role1> [role2] [role3]
```

**Examples:**

```bash
# Assign DevOps role to testuser
./scripts/assign-user-roles.sh testuser ROLE_DEVOPS

# Assign multiple roles
./scripts/assign-user-roles.sh testuser ROLE_DBA ROLE_DEVOPS

# Assign all roles
./scripts/assign-user-roles.sh admin-user ROLE_DBA ROLE_DEVOPS ROLE_READONLY_MONITORING
```

### 3. Assign Groups to a User

Groups automatically grant their associated roles:

```bash
./scripts/assign-user-groups.sh <username> <group1> [group2] [group3]
```

**Examples:**

```bash
# Add user to DevOps group (grants ROLE_DEVOPS)
./scripts/assign-user-groups.sh testuser DevOps

# Add user to multiple groups
./scripts/assign-user-groups.sh testuser DBAs DevOps

# Add user to all groups
./scripts/assign-user-groups.sh admin-user DBAs DevOps Monitoring
```

## Available Roles

| Role Name | Description | Access |
|-----------|-------------|--------|
| `ROLE_DBA` | Database Administrator | Full access to pgAdmin and database management |
| `ROLE_DEVOPS` | DevOps Engineer | Access to infrastructure tools and monitoring |
| `ROLE_READONLY_MONITORING` | Monitoring User | Read-only access to monitoring dashboards |

## Available Groups

| Group Name | Associated Roles | Description |
|------------|------------------|-------------|
| `DBAs` | `ROLE_DBA` | Database administrators group |
| `DevOps` | `ROLE_DEVOPS` | DevOps engineers group |
| `Monitoring` | `ROLE_READONLY_MONITORING` | Monitoring users group |

## Roles vs Groups

**When to use Roles:**
- Direct role assignment for temporary access
- Fine-grained permission control
- When a user needs specific permissions without group membership

**When to use Groups:**
- Organizational structure (teams, departments)
- Consistent role assignment for team members
- Easier management of multiple users with same permissions

**Recommendation:** Use groups for most cases, as they provide better organization and are easier to manage at scale.

## Step-by-Step Workflow

### Scenario 1: New Developer Joining the Team

```bash
# 1. Create the user (if not already created)
./scripts/create-test-user.sh developer1 SecurePass123!

# 2. Assign to DevOps group
./scripts/assign-user-groups.sh developer1 DevOps

# 3. Verify assignment
./scripts/list-keycloak-users.sh
```

### Scenario 2: Promote User to DBA

```bash
# Add DBA role in addition to existing DevOps role
./scripts/assign-user-roles.sh developer1 ROLE_DBA

# Or add to DBAs group
./scripts/assign-user-groups.sh developer1 DBAs
```

### Scenario 3: Grant Temporary Monitoring Access

```bash
# Just assign the monitoring role (no group needed)
./scripts/assign-user-roles.sh contractor1 ROLE_READONLY_MONITORING
```

### Scenario 4: Full Admin Access

```bash
# Assign all groups for comprehensive access
./scripts/assign-user-groups.sh admin-user DBAs DevOps Monitoring
```

## Manual Assignment via Keycloak Admin Console

If you prefer to use the web interface:

### 1. Access Keycloak Admin Console

Navigate to: **http://localhost/auth**

Login with:
- Username: `admin`
- Password: `admin` (or your configured admin password)

### 2. Select the Realm

1. Click on the realm dropdown (top-left corner)
2. Select **"infra-admin"**

### 3. Navigate to Users

1. Click **"Users"** in the left sidebar
2. Click on the username you want to modify

### 4. Assign Roles

1. Go to the **"Role mapping"** tab
2. Click **"Assign role"**
3. Select the roles you want to assign:
   - `ROLE_DBA`
   - `ROLE_DEVOPS`
   - `ROLE_READONLY_MONITORING`
4. Click **"Assign"**

### 5. Assign Groups (Alternative)

1. Go to the **"Groups"** tab
2. Click **"Join Group"**
3. Select the groups:
   - `DBAs` (grants ROLE_DBA)
   - `DevOps` (grants ROLE_DEVOPS)
   - `Monitoring` (grants ROLE_READONLY_MONITORING)
4. Click **"Join"**

### 6. Verify

Check the **"Role mapping"** tab to see all effective roles (both direct and inherited from groups).

## Troubleshooting

### Script Reports "Failed to get admin access token"

**Solution:** Check that Keycloak is running and accessible:

```bash
# Check if Keycloak container is running
docker ps | grep keycloak

# Verify Keycloak is responding
curl -s http://localhost/auth/realms/infra-admin | grep -q "infra-admin" && echo "OK" || echo "FAIL"
```

### User Not Found

**Solution:** Create the user first:

```bash
./scripts/create-test-user.sh <username> <password>
```

Or check existing users:

```bash
./scripts/list-keycloak-users.sh
```

### Role Already Assigned Warning

This is informational only. The script detected the user already has the role and skipped it.

### HTTP 401 or 403 Errors

**Solution:** Admin credentials may be incorrect. Check your environment variables:

```bash
# Set correct admin credentials
export KEYCLOAK_ADMIN=admin
export KEYCLOAK_ADMIN_PASSWORD=admin
```

## Environment Variables

All scripts use these environment variables (with defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `KEYCLOAK_ADMIN` | `admin` | Keycloak admin username |
| `KEYCLOAK_ADMIN_PASSWORD` | `admin` | Keycloak admin password |

**Example with custom credentials:**

```bash
KEYCLOAK_ADMIN=myadmin KEYCLOAK_ADMIN_PASSWORD=mypass ./scripts/assign-user-roles.sh testuser ROLE_DEVOPS
```

## Best Practices

### 1. Use Groups for Team Management

Assign users to groups rather than individual roles. This makes it easier to:
- Manage permissions at scale
- Understand organizational structure
- Audit access controls

### 2. Follow Principle of Least Privilege

Only grant the minimum permissions needed:
- Developers → `DevOps` group only
- DBAs → `DBAs` + `DevOps` groups
- Contractors → `ROLE_READONLY_MONITORING` only

### 3. Regular Access Reviews

Periodically review user access:

```bash
./scripts/list-keycloak-users.sh > user-audit-$(date +%Y%m%d).txt
```

### 4. Document Role Assignments

Keep a record of why users have specific roles:
- Comment in commit messages
- Maintain a spreadsheet
- Use Keycloak's user attributes to store notes

### 5. Use Temporary Passwords for Initial Creation

When creating users, set `temporary: true` to force password change on first login:

```bash
./scripts/create-test-user.sh newuser TempPass123!
```

## Security Considerations

### Password Policy

The realm enforces these password requirements:
- Minimum 12 characters
- At least 1 uppercase letter
- At least 1 lowercase letter
- At least 1 digit
- At least 1 special character
- Cannot be same as username
- Last 3 passwords cannot be reused

### Brute Force Protection

Keycloak is configured with brute force protection:
- Max 5 failed login attempts
- 15-minute lockout after failures
- Progressive wait times between attempts

### Session Settings

- Access token lifespan: 60 minutes
- SSO session idle timeout: 30 minutes
- SSO session max lifespan: 10 hours

## Integration with Applications

### Frontend (ai-front-spa)

The Vue 3 frontend automatically receives user roles in the JWT token:

```typescript
// Roles are available in the token
const token = keycloak.tokenParsed;
const roles = token.realm_access?.roles || [];

// Check if user has specific role
const hasDBAccess = roles.includes('ROLE_DBA');
```

### pgAdmin

pgAdmin uses the `pgadmin-client` OAuth client. Users need `ROLE_DBA` to access pgAdmin.

### Grafana

Grafana can be configured to respect these roles for dashboard access:
- `ROLE_DEVOPS` → Editor access
- `ROLE_READONLY_MONITORING` → Viewer access
- `ROLE_DBA` → Admin access (with proper configuration)

## Complete Workflow Example

Here's a complete workflow for onboarding a new team member:

```bash
# 1. Create user account
./scripts/create-test-user.sh john.doe SecurePass123!

# 2. List users to verify creation
./scripts/list-keycloak-users.sh

# 3. Assign to appropriate group
./scripts/assign-user-groups.sh john.doe DevOps

# 4. Optionally add additional role if needed
./scripts/assign-user-roles.sh john.doe ROLE_READONLY_MONITORING

# 5. Verify final permissions
./scripts/list-keycloak-users.sh | grep -A 10 "john.doe"

# 6. Send credentials to user
echo "Login at: http://localhost/home"
echo "Username: john.doe"
echo "Password: SecurePass123! (temporary, will be forced to change)"
```

## References

- [Keycloak Documentation](https://www.keycloak.org/documentation)
- [Keycloak Admin REST API](https://www.keycloak.org/docs-api/latest/rest-api/index.html)
- [OIDC Protocol](https://openid.net/connect/)

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review Keycloak logs: `docker logs ai_infra_keycloak`
3. Consult the main README.md in the project root

