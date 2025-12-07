# Git Submodule Management Guide

## Overview

This project uses Git submodules to manage the frontend application (`frontend/ai-front`). This guide explains how to work with submodules effectively using the Makefile commands.

## Quick Reference

```bash
# Most common operations
make submodule-refresh          # Pull latest changes from remote
make submodule-status           # Check submodule status
make frontend-submodule-update  # Update only frontend submodule
```

## Available Makefile Commands

### 1. `make submodule-init`
**Purpose**: Initialize git submodules for the first time

**When to use**:
- After cloning the repository for the first time
- When submodule directories are empty

**What it does**:
```bash
git submodule init
git submodule update
```

**Example**:
```bash
$ make submodule-init
Initializing git submodules...
Submodule 'frontend/ai-front' (https://github.com/nicolaslallier/AI_Front.git) registered for path 'frontend/ai-front'
✓ Submodules initialized
```

---

### 2. `make submodule-update`
**Purpose**: Update submodules to the latest commit from their remote repositories

**When to use**:
- When you want to update to the latest version of the frontend
- After other team members have updated the submodule reference

**What it does**:
```bash
git submodule update --remote --merge
```

**Example**:
```bash
$ make submodule-update
Updating git submodules...
Submodule path 'frontend/ai-front': checked out '1234abc'
✓ Submodules updated to latest
```

---

### 3. `make submodule-refresh` ⭐ **RECOMMENDED**
**Purpose**: Complete refresh of submodules (most commonly used)

**When to use**:
- Daily development workflow
- After pulling main branch changes
- When submodule seems out of sync
- When you want the latest version of everything

**What it does**:
```bash
git submodule update --init --recursive --remote
```

**Example**:
```bash
$ make submodule-refresh
Refreshing git submodules...
Fetching submodule frontend/ai-front
From https://github.com/nicolaslallier/AI_Front
   1234abc..5678def  main     -> origin/main
✓ Submodules refreshed

Git submodule status:
 5678def frontend/ai-front (v1.2.3)

Frontend submodule details:
origin  https://github.com/nicolaslallier/AI_Front.git (fetch)
origin  https://github.com/nicolaslallier/AI_Front.git (push)

5678def feat: add new dashboard component
```

---

### 4. `make submodule-status`
**Purpose**: Show current status of all submodules

**When to use**:
- To check which commit the submodule is on
- To verify submodule state
- For debugging submodule issues

**What it does**:
```bash
git submodule status
# Plus detailed information about frontend submodule
```

**Example**:
```bash
$ make submodule-status
Git submodule status:
 5678def frontend/ai-front (v1.2.3)

Frontend submodule details:
origin  https://github.com/nicolaslallier/AI_Front.git (fetch)
origin  https://github.com/nicolaslallier/AI_Front.git (push)

5678def feat: add new dashboard component
```

---

### 5. `make submodule-pull`
**Purpose**: Pull latest changes in all submodules from their main branch

**When to use**:
- Similar to `submodule-refresh` but specifically pulls from main
- When you know you want main branch updates

**What it does**:
```bash
git submodule foreach git pull origin main
```

---

### 6. `make submodule-clean`
**Purpose**: Remove untracked files from submodules

**When to use**:
- When submodule has build artifacts or temp files
- Before doing a clean build
- To resolve "dirty" submodule status

**What it does**:
```bash
git submodule foreach --recursive git clean -fd
```

**⚠️ Warning**: This will delete untracked files!

---

### 7. `make submodule-reset`
**Purpose**: Reset submodules to their committed state

**When to use**:
- When submodule is in a broken state
- To discard all local changes in submodules
- For troubleshooting

**What it does**:
```bash
git submodule deinit -f .
git submodule update --init --recursive
```

**⚠️ Warning**: This will discard all local changes in submodules!

---

### 8. `make submodule-sync`
**Purpose**: Sync submodule URLs from .gitmodules file

**When to use**:
- When submodule repository URL has changed
- After modifying .gitmodules
- For fixing submodule URL mismatches

**What it does**:
```bash
git submodule sync --recursive
git submodule update --init --recursive
```

---

### 9. `make frontend-submodule-update`
**Purpose**: Update only the frontend submodule specifically

**When to use**:
- When you only want to update the frontend
- For targeted updates
- In your development workflow

**What it does**:
```bash
cd frontend/ai-front && git fetch origin && git pull origin main
git add frontend/ai-front
```

**Example**:
```bash
$ make frontend-submodule-update
Updating frontend submodule...
From https://github.com/nicolaslallier/AI_Front
 * branch            main       -> FETCH_HEAD
Updating 1234abc..5678def
Fast-forward
 src/components/Dashboard.vue | 45 ++++++++++++++++++++++++++++++++++++++
Frontend submodule updated. Don't forget to commit if needed.
✓ Frontend submodule updated
```

---

## Common Workflows

### 1. First-Time Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd AI_Infra

# Run setup (includes submodule initialization)
make setup

# Or manually initialize submodules
make submodule-init
```

### 2. Daily Development

```bash
# Pull latest changes from main repo
git pull origin main

# Refresh submodules to latest
make submodule-refresh

# Start development
make up
```

### 3. Update Frontend to Latest

```bash
# Option 1: Update all submodules
make submodule-refresh

# Option 2: Update only frontend
make frontend-submodule-update

# Rebuild and restart
make up-build
```

### 4. Check Submodule Status

```bash
# Quick status check
make submodule-status

# Detailed view
cd frontend/ai-front
git status
git log -5 --oneline
```

### 5. Fixing Submodule Issues

```bash
# Try refresh first
make submodule-refresh

# If still broken, clean and reset
make submodule-clean
make submodule-reset

# Last resort: manual cleanup
rm -rf frontend/ai-front
make submodule-init
```

---

## Understanding Submodule Status Symbols

When you run `git submodule status`, you may see different symbols:

- ` ` (no symbol) = Submodule is checked out at correct commit
- `+` = Submodule is checked out to a different commit than recorded
- `-` = Submodule is not initialized
- `U` = Submodule has merge conflicts

**Example**:
```bash
 5678def frontend/ai-front (v1.2.3)  # ✓ Good - checked out at correct commit
+5678def frontend/ai-front (v1.2.3)  # ⚠️ Warning - at different commit
-5678def frontend/ai-front           # ❌ Not initialized
```

---

## Committing Submodule Changes

When you update a submodule, you need to commit the reference update:

```bash
# Update frontend submodule
make frontend-submodule-update

# Check what changed
git status
# Shows: modified:   frontend/ai-front (new commits)

# Add and commit the submodule reference
git add frontend/ai-front
git commit -m "chore: update frontend submodule to latest"
git push
```

---

## Troubleshooting

### Problem: Submodule directory is empty

**Solution**:
```bash
make submodule-init
```

### Problem: Submodule shows as "modified" in git status

**Cause**: Submodule is checked out to a different commit

**Solution**:
```bash
# Option 1: Update to latest
make submodule-refresh

# Option 2: Reset to recorded commit
git submodule update --init --recursive
```

### Problem: Can't pull changes in submodule

**Solution**:
```bash
cd frontend/ai-front
git status  # Check for uncommitted changes
git stash   # Stash if needed
git pull origin main
cd ../..
make submodule-status
```

### Problem: Submodule URL changed

**Solution**:
```bash
# Edit .gitmodules with new URL
vim .gitmodules

# Sync the new URL
make submodule-sync
```

### Problem: Submodule is in detached HEAD state

**This is normal!** Submodules are always in detached HEAD state by design.

To make changes:
```bash
cd frontend/ai-front
git checkout main
# Make your changes
git commit -m "your changes"
git push origin main
cd ../..
make frontend-submodule-update
```

---

## Best Practices

### ✅ DO:
1. **Always refresh submodules after pulling** from main repository
2. **Use `make submodule-refresh`** as your go-to command
3. **Check submodule status** before committing
4. **Commit submodule reference updates** separately with descriptive messages
5. **Document submodule updates** in commit messages

### ❌ DON'T:
1. **Don't make changes directly in submodule** without proper workflow
2. **Don't ignore submodule updates** when pulling main repo
3. **Don't delete submodule directories** manually (use reset commands)
4. **Don't commit dirty submodules** (with uncommitted changes)

---

## Integration with CI/CD

The submodule initialization is integrated into the setup process:

```makefile
# In Makefile
setup: ## Initial setup
    # ... other setup steps ...
    @git submodule update --init --recursive
```

CI/CD pipelines should include:

```yaml
# Example CI configuration
steps:
  - name: Checkout
    run: |
      git clone --recurse-submodules <repo-url>
      # OR
      git clone <repo-url>
      cd <repo>
      make submodule-init
```

---

## Advanced: Working on Submodule Development

If you're actively developing the frontend:

```bash
# 1. Navigate to submodule
cd frontend/ai-front

# 2. Create a feature branch
git checkout -b feature/my-feature

# 3. Make changes and commit
git add .
git commit -m "feat: implement new feature"

# 4. Push to frontend repository
git push origin feature/my-feature

# 5. Create PR in frontend repo

# 6. After merge, update main infrastructure repo
git checkout main
git pull origin main
cd ../..
make frontend-submodule-update
git add frontend/ai-front
git commit -m "chore: update frontend to include new feature"
git push origin main
```

---

## Quick Decision Tree

```
Need to update frontend?
├─ First time? → make submodule-init
├─ Daily update? → make submodule-refresh
├─ Only frontend? → make frontend-submodule-update
├─ Something broken? → make submodule-reset
└─ Check status? → make submodule-status
```

---

## References

- [Git Submodules Documentation](https://git-scm.com/book/en/v2/Git-Tools-Submodules)
- [Frontend Repository](https://github.com/nicolaslallier/AI_Front)
- [Project Makefile](../../Makefile)

---

## Support

For issues with submodules:
1. Check this guide first
2. Run `make submodule-status` to diagnose
3. Try `make submodule-refresh` or `make submodule-reset`
4. Review git submodule documentation
5. Contact team lead if issue persists

