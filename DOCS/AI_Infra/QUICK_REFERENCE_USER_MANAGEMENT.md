# Keycloak User Management - Quick Reference

## 📋 Available Roles

| Role | Description |
|------|-------------|
| `ROLE_DBA` | Full database admin access (pgAdmin) |
| `ROLE_DEVOPS` | Infrastructure and monitoring access |
| `ROLE_READONLY_MONITORING` | View-only monitoring access |

## 📋 Available Groups

| Group | Grants Role |
|-------|-------------|
| `DBAs` | `ROLE_DBA` |
| `DevOps` | `ROLE_DEVOPS` |
| `Monitoring` | `ROLE_READONLY_MONITORING` |

## 🚀 Quick Commands

### List All Users
```bash
./scripts/list-keycloak-users.sh
```

### Create New User
```bash
./scripts/create-test-user.sh <username> <password>

# Example:
./scripts/create-test-user.sh john.doe SecurePass123!
```

### Assign Roles (Direct)
```bash
./scripts/assign-user-roles.sh <username> <role1> [role2] [role3]

# Examples:
./scripts/assign-user-roles.sh john.doe ROLE_DEVOPS
./scripts/assign-user-roles.sh jane.smith ROLE_DBA ROLE_DEVOPS
./scripts/assign-user-roles.sh admin-user ROLE_DBA ROLE_DEVOPS ROLE_READONLY_MONITORING
```

### Assign Groups (Recommended)
```bash
./scripts/assign-user-groups.sh <username> <group1> [group2] [group3]

# Examples:
./scripts/assign-user-groups.sh john.doe DevOps
./scripts/assign-user-groups.sh jane.smith DBAs DevOps
./scripts/assign-user-groups.sh admin-user DBAs DevOps Monitoring
```

## 🎯 Common Scenarios

### New Developer
```bash
./scripts/create-test-user.sh developer SecurePass123!
./scripts/assign-user-groups.sh developer DevOps
```

### Database Administrator
```bash
./scripts/create-test-user.sh dba-admin SecurePass123!
./scripts/assign-user-groups.sh dba-admin DBAs DevOps
```

### Contractor (Read-Only)
```bash
./scripts/create-test-user.sh contractor TempPass123!
./scripts/assign-user-roles.sh contractor ROLE_READONLY_MONITORING
```

### Full Administrator
```bash
./scripts/create-test-user.sh admin SecurePass123!
./scripts/assign-user-groups.sh admin DBAs DevOps Monitoring
```

## 🌐 Manual Administration

**Keycloak Admin Console**: http://localhost/auth/

1. Login with admin credentials
2. Select realm: **infra-admin**
3. Navigate to **Users**
4. Select user → **Role mapping** tab
5. Click **Assign role** or **Join Group**

## 🔑 Login URL

**Frontend Application**: http://localhost/home

## 📚 Full Documentation

See [KEYCLOAK_USER_MANAGEMENT.md](KEYCLOAK_USER_MANAGEMENT.md) for comprehensive guide.

