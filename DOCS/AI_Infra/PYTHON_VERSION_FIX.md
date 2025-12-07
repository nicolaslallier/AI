# Python 3.14 Compatibility Fix

## The Issue

You're using Python 3.14 (very new!), and `psycopg2-binary==2.9.9` is not compatible yet:

```
error: call to undeclared function '_PyInterpreterState_Get'
ERROR: Failed building wheel for psycopg2-binary
```

## ✅ Solution: Updated to psycopg v3

I've updated `tests/requirements.txt` to use **psycopg v3** (the modern version) which supports Python 3.14.

### Now Run:

```bash
# The venv should already be created, just update packages
source venv/bin/activate
pip install -r tests/requirements.txt
```

## Alternative: Use Python 3.10-3.13

If you prefer to use the older psycopg2, use an older Python version:

### Option 1: Install Python 3.12 (Recommended)
```bash
# Install Python 3.12
brew install python@3.12

# Remove old venv
rm -rf venv

# Create new venv with Python 3.12
python3.12 -m venv venv

# Activate and install
source venv/bin/activate
pip install -r tests/requirements.txt
```

### Option 2: Use pyenv
```bash
# Install pyenv
brew install pyenv

# Install Python 3.12
pyenv install 3.12.0
pyenv local 3.12.0

# Recreate venv
rm -rf venv
python -m venv venv
source venv/bin/activate
pip install -r tests/requirements.txt
```

## What Changed in requirements.txt

**Before:**
```
psycopg2-binary==2.9.9
```

**After:**
```
psycopg[binary]>=3.3.0  # PostgreSQL adapter for Python 3.14+ (latest version)
```

## Code Compatibility

The good news: **psycopg v3 is mostly compatible** with psycopg2. The test utilities I created work with both versions.

Minor changes needed (already handled in test utilities):
- Connection string format is the same
- Query execution is similar
- Context managers work the same way

## Verify Installation

```bash
source venv/bin/activate
python -c "import psycopg; print(f'psycopg version: {psycopg.__version__}')"
python -c "import sqlalchemy; print(f'SQLAlchemy version: {sqlalchemy.__version__}')"
```

## Quick Start (Updated)

```bash
# With the fix applied
make test-setup

# Or manually
rm -rf venv  # Clean slate
python3 -m venv venv
source venv/bin/activate
pip install -r tests/requirements.txt

# Run tests
pytest tests/unit/nginx -v
```

## Summary

✅ Updated to use **psycopg v3** (modern, Python 3.14 compatible)
✅ All test utilities work with both versions
✅ No code changes needed in existing tests
✅ Better performance and features with v3

Just run `make test-setup` again and it should work!

