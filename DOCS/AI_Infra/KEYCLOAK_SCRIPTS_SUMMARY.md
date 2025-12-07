# Keycloak User Management Scripts - Implementation Summary

## ✅ What Has Been Created

I've created a comprehensive set of scripts and documentation to help you manage Keycloak users and roles **without needing to access the admin console menu**.

### 📜 Scripts Created

#### 1. **assign-user-roles.sh** - Assign Roles to Users
- **Location**: `scripts/assign-user-roles.sh`
- **Purpose**: Directly assign one or more roles to a Keycloak user
- **Usage**: `./scripts/assign-user-roles.sh <username> <role1> [role2] [role3]`
- **Features**:
  - Validates user exists before assignment
  - Checks if role already assigned (prevents duplicates)
  - Shows detailed progress with color-coded output
  - Verifies final role assignments
  - Provides helpful error messages

**Example:**
```bash
./scripts/assign-user-roles.sh testuser ROLE_DEVOPS
./scripts/assign-user-roles.sh admin ROLE_DBA ROLE_DEVOPS ROLE_READONLY_MONITORING
```

#### 2. **assign-user-groups.sh** - Assign Groups to Users
- **Location**: `scripts/assign-user-groups.sh`
- **Purpose**: Add users to groups (which automatically grant associated roles)
- **Usage**: `./scripts/assign-user-groups.sh <username> <group1> [group2] [group3]`
- **Features**:
  - Groups automatically grant their associated roles
  - Better for team/organizational management
  - Shows both group and role assignments
  - Validates group existence

**Example:**
```bash
./scripts/assign-user-groups.sh testuser DevOps
./scripts/assign-user-groups.sh dba-admin DBAs DevOps
```

#### 3. **list-keycloak-users.sh** - View All Users
- **Location**: `scripts/list-keycloak-users.sh`
- **Purpose**: Display all users with their roles and groups
- **Usage**: `./scripts/list-keycloak-users.sh`
- **Features**:
  - Lists all users in the realm
  - Shows email, status (enabled/disabled)
  - Displays all assigned roles
  - Shows all group memberships
  - Color-coded for easy reading

**Example:**
```bash
./scripts/list-keycloak-users.sh
```

### 📚 Documentation Created

#### 1. **KEYCLOAK_USER_MANAGEMENT.md** - Comprehensive Guide
- **Location**: `KEYCLOAK_USER_MANAGEMENT.md`
- **Contents**:
  - Complete usage instructions for all scripts
  - Manual web console steps (if needed)
  - Available roles and groups reference
  - Troubleshooting guide
  - Best practices
  - Security considerations
  - Complete workflow examples

#### 2. **QUICK_REFERENCE_USER_MANAGEMENT.md** - Quick Reference Card
- **Location**: `QUICK_REFERENCE_USER_MANAGEMENT.md`
- **Contents**:
  - One-page quick reference
  - All roles and groups in tables
  - Common command examples
  - Typical scenarios with commands
  - Links to full documentation

#### 3. **README.md** - Updated
- **Location**: `README.md`
- **Changes**: Added user management section with quick commands

### 🎯 Available Roles (From Your Configuration)

| Role Name | Description | What It Grants |
|-----------|-------------|----------------|
| `ROLE_DBA` | Database Administrator | Full access to pgAdmin and database management |
| `ROLE_DEVOPS` | DevOps Engineer | Access to infrastructure tools and monitoring |
| `ROLE_READONLY_MONITORING` | Monitoring User | Read-only access to monitoring dashboards |

### 🎯 Available Groups (From Your Configuration)

| Group Name | Path | Associated Role |
|------------|------|-----------------|
| `DBAs` | `/DBAs` | `ROLE_DBA` |
| `DevOps` | `/DevOps` | `ROLE_DEVOPS` |
| `Monitoring` | `/Monitoring` | `ROLE_READONLY_MONITORING` |

## 🚀 How to Use

### Most Common Use Case: Assign Role to Existing User

```bash
# 1. First, check which users exist
./scripts/list-keycloak-users.sh

# 2. Assign a role to your user
./scripts/assign-user-roles.sh <your-username> ROLE_DEVOPS

# 3. Verify the assignment
./scripts/list-keycloak-users.sh | grep -A 5 "<your-username>"
```

### Creating New User with Roles

```bash
# 1. Create the user
./scripts/create-test-user.sh newuser SecurePass123!

# 2. Assign to a group (recommended)
./scripts/assign-user-groups.sh newuser DevOps

# 3. Or assign roles directly
./scripts/assign-user-roles.sh newuser ROLE_DEVOPS ROLE_READONLY_MONITORING

# 4. Verify
./scripts/list-keycloak-users.sh
```

### Grant Full Admin Access

```bash
# Grant all roles to a user
./scripts/assign-user-roles.sh admin-user ROLE_DBA ROLE_DEVOPS ROLE_READONLY_MONITORING

# Or add to all groups
./scripts/assign-user-groups.sh admin-user DBAs DevOps Monitoring
```

## 🔧 Technical Details

### How the Scripts Work

1. **Authentication**: Scripts use Keycloak Admin REST API
   - Authenticate with admin credentials
   - Get access token for admin operations

2. **User Lookup**: Query users endpoint with exact username match
   - Retrieve user ID (required for role/group operations)

3. **Role/Group Assignment**: Use Keycloak's role mapping endpoints
   - For roles: POST to `/users/{id}/role-mappings/realm`
   - For groups: PUT to `/users/{id}/groups/{groupId}`

4. **Verification**: Query current assignments
   - Fetch and display all roles and groups after operation

### Environment Variables

All scripts respect these environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `KEYCLOAK_ADMIN` | `admin` | Admin username |
| `KEYCLOAK_ADMIN_PASSWORD` | `admin` | Admin password |

**Custom credentials example:**
```bash
KEYCLOAK_ADMIN=myadmin KEYCLOAK_ADMIN_PASSWORD=mypass ./scripts/assign-user-roles.sh user1 ROLE_DBA
```

### Prerequisites

- Keycloak must be running (`docker ps | grep keycloak`)
- Keycloak must be accessible at `http://localhost/auth`
- Python 3 must be available (for JSON parsing)
- `curl` must be available

## 📋 Complete Workflow Example

Here's a complete example of onboarding a new developer:

```bash
# Step 1: Check if Keycloak is running
docker ps | grep keycloak

# Step 2: List current users to see what exists
./scripts/list-keycloak-users.sh

# Step 3: Create new user if needed
./scripts/create-test-user.sh john.developer SecurePass123!

# Step 4: Assign appropriate role
./scripts/assign-user-roles.sh john.developer ROLE_DEVOPS

# Step 5: Optionally add monitoring access
./scripts/assign-user-roles.sh john.developer ROLE_READONLY_MONITORING

# Step 6: Verify final setup
./scripts/list-keycloak-users.sh | grep -A 10 "john.developer"

# Step 7: User can now login at http://localhost/home
echo "User can login at: http://localhost/home"
echo "Username: john.developer"
echo "Password: SecurePass123!"
```

## 🎨 Script Output Examples

### Successful Role Assignment
```
═══════════════════════════════════════════════════════
   Keycloak Role Assignment Script
═══════════════════════════════════════════════════════

Target User: testuser
Roles to assign:
  • ROLE_DEVOPS

1️⃣  Getting admin access token...
✅ Access token obtained
2️⃣  Looking up user: testuser
✅ User found (ID: abc-123-def)
3️⃣  Fetching available realm roles...
4️⃣  Assigning roles...

  Assigning role: ROLE_DEVOPS
    ✅ Role assigned successfully

5️⃣  Verifying current role assignments...

Current roles for user 'testuser':
  • ROLE_DEVOPS - DevOps Engineer - Access to infrastructure tools and monitoring

═══════════════════════════════════════════════════════
   Summary
═══════════════════════════════════════════════════════
✅ Successfully assigned: 1

🎉 Role assignment completed!
```

### User List Output
```
Found 3 user(s):

1. admin-dba
   Email: dba-admin@example.com
   Status: ✅ Enabled
   ID: xyz-789
   Roles:
     • ROLE_DBA - Database Administrator - Full access to pgAdmin
   Groups:
     • DBAs (/DBAs)

2. devops-user
   Email: devops@example.com
   Status: ✅ Enabled
   ID: abc-456
   Roles:
     • ROLE_DEVOPS - DevOps Engineer
   Groups:
     • DevOps (/DevOps)

3. testuser
   Email: testuser@example.com
   Status: ✅ Enabled
   ID: def-123
   Roles:
     • ROLE_DEVOPS - DevOps Engineer
   Groups: None assigned
```

## 🔒 Security Notes

### Password Requirements
The realm enforces strict password policies:
- Minimum 12 characters
- At least 1 uppercase letter
- At least 1 lowercase letter
- At least 1 digit
- At least 1 special character
- Cannot be same as username
- Last 3 passwords cannot be reused

### Brute Force Protection
- Max 5 failed login attempts
- 15-minute lockout after failures
- Progressive wait times between attempts

### Best Practices
1. **Use temporary passwords** when creating users (force password change on first login)
2. **Use groups** for organizational management (easier to audit)
3. **Grant minimum permissions** (principle of least privilege)
4. **Regular access reviews** - use list script to audit user access

## 🐛 Troubleshooting

### "Failed to get admin access token"
**Cause**: Keycloak not running or admin credentials incorrect

**Solution**:
```bash
# Check if Keycloak is running
docker ps | grep keycloak

# Check if accessible
curl -s http://localhost/auth/realms/infra-admin | grep -q "infra-admin" && echo "OK" || echo "FAIL"

# Verify admin credentials in docker-compose.yml
grep KEYCLOAK_ADMIN docker-compose.yml
```

### "User not found"
**Cause**: Username doesn't exist or typo

**Solution**:
```bash
# List all users to see exact usernames
./scripts/list-keycloak-users.sh
```

### "Role not found in realm"
**Cause**: Typo in role name (role names are case-sensitive)

**Solution**: Use exact role names:
- `ROLE_DBA` (not `role_dba` or `ROLE_Dba`)
- `ROLE_DEVOPS` (not `ROLE_DevOps`)
- `ROLE_READONLY_MONITORING`

### "Group not found"
**Cause**: Typo in group name (group names are case-sensitive)

**Solution**: Use exact group names:
- `DBAs` (not `dbas` or `DBAS`)
- `DevOps` (not `devops` or `DEVOPS`)
- `Monitoring` (not `monitoring`)

## 📁 File Locations

```
AI_Infra/
├── scripts/
│   ├── create-test-user.sh          (existing - creates users)
│   ├── assign-user-roles.sh         (NEW - assigns roles)
│   ├── assign-user-groups.sh        (NEW - assigns groups)
│   └── list-keycloak-users.sh       (NEW - lists users)
│
├── KEYCLOAK_USER_MANAGEMENT.md      (NEW - full guide)
├── QUICK_REFERENCE_USER_MANAGEMENT.md (NEW - quick reference)
└── README.md                         (UPDATED - added user mgmt section)
```

## ✅ All Scripts Are Executable

All scripts have been made executable with `chmod +x`:
- ✅ `scripts/assign-user-roles.sh`
- ✅ `scripts/assign-user-groups.sh`
- ✅ `scripts/list-keycloak-users.sh`
- ✅ `scripts/create-test-user.sh` (already existed)

## 🎯 Your Next Steps

1. **Test the user list script**:
   ```bash
   ./scripts/list-keycloak-users.sh
   ```

2. **Assign roles to your existing user**:
   ```bash
   # Replace 'your-username' with your actual Keycloak username
   ./scripts/assign-user-roles.sh your-username ROLE_DEVOPS
   ```

3. **Verify the assignment**:
   ```bash
   ./scripts/list-keycloak-users.sh | grep -A 5 "your-username"
   ```

4. **Login to test**:
   - Go to http://localhost/home
   - Login with your username/password
   - You should now have the assigned roles

## 📞 Support

- **Full Documentation**: See `KEYCLOAK_USER_MANAGEMENT.md`
- **Quick Reference**: See `QUICK_REFERENCE_USER_MANAGEMENT.md`
- **Main README**: See `README.md` (user management section)

## 🎉 Summary

You now have **three powerful scripts** to manage Keycloak users without touching the admin console:

1. 📋 **List users** - See all users and their permissions
2. 🎯 **Assign roles** - Grant specific permissions to users
3. 👥 **Assign groups** - Add users to organizational groups

All scripts include:
- ✅ Error handling and validation
- ✅ Color-coded output for easy reading
- ✅ Detailed progress information
- ✅ Verification of assignments
- ✅ Helpful error messages

**You're all set to manage your Keycloak users!** 🚀

