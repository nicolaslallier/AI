# Git Submodule Quick Reference

## 🚀 Most Common Commands

```bash
# Daily workflow - refresh to latest
make submodule-refresh

# Check current status
make submodule-status

# Update only frontend
make frontend-submodule-update

# Initialize after clone
make submodule-init
```

## 📋 All Submodule Commands

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `make submodule-init` | Initialize submodules | First time after cloning |
| `make submodule-update` | Update to latest from remote | Regular updates |
| `make submodule-refresh` | **Complete refresh** | **Most common - daily use** |
| `make submodule-status` | Show current status | Check what version you're on |
| `make submodule-pull` | Pull from main branch | Update to main |
| `make submodule-clean` | Remove untracked files | Clean build artifacts |
| `make submodule-reset` | Reset to committed state | Fix broken state |
| `make submodule-sync` | Sync URLs from .gitmodules | After URL changes |
| `make frontend-submodule-update` | Update frontend only | Targeted frontend update |

## 🎯 Quick Decision Tree

```
┌─ Need to update frontend?
│
├─ First time? ──────────────► make submodule-init
│
├─ Daily update? ────────────► make submodule-refresh
│
├─ Only frontend? ───────────► make frontend-submodule-update
│
├─ Something broken? ────────► make submodule-reset
│
└─ Check status? ────────────► make submodule-status
```

## 💡 Understanding Status Output

The `+` symbol means the submodule is at a different commit than recorded:

```bash
$ make submodule-status
+734ca32 frontend/ai-front    # ⚠️ At different commit (common during development)
 734ca32 frontend/ai-front    # ✓ At correct commit
-734ca32 frontend/ai-front    # ❌ Not initialized
```

## 🔄 Typical Workflows

### Daily Development
```bash
git pull origin main          # Pull main repo updates
make submodule-refresh        # Refresh submodules
make up                       # Start services
```

### Update Frontend Only
```bash
make frontend-submodule-update    # Update frontend
make up-build                     # Rebuild and start
```

### After Cloning
```bash
git clone <repo-url>
cd AI_Infra
make setup                    # Includes submodule init
make up
```

### Fix Broken Submodule
```bash
make submodule-clean          # Clean artifacts
make submodule-reset          # Reset to clean state
make submodule-refresh        # Refresh to latest
```

## 📚 Full Documentation

For comprehensive information, see:
- [Complete Git Submodule Guide](../AI/DOCS/AI_Infra/GIT_SUBMODULE_GUIDE.md)
- [Makefile Guide](../AI/DOCS/AI_Infra/MAKEFILE_GUIDE.md)

## ⚠️ Important Notes

1. **After updating**: Always commit the submodule reference change
   ```bash
   git add frontend/ai-front
   git commit -m "chore: update frontend submodule"
   ```

2. **Detached HEAD is normal**: Submodules always work in detached HEAD state

3. **Before making changes**: If you need to modify the frontend, work in the frontend repo directly

4. **Integration**: `make setup` automatically initializes submodules

## 🆘 Troubleshooting

| Problem | Solution |
|---------|----------|
| Empty submodule directory | `make submodule-init` |
| Submodule shows as modified | `make submodule-refresh` |
| Can't pull changes | Check network, try `make submodule-reset` |
| Wrong version | `make submodule-refresh` |

## 🔗 Related Commands

```bash
make setup                    # Initial setup (includes submodule init)
make frontend-build          # Build frontend Docker image
make frontend-dev            # Run frontend in dev mode
make frontend-logs           # Show frontend logs
```

---

**Quick Tip**: When in doubt, run `make submodule-refresh` - it's safe and updates everything!

