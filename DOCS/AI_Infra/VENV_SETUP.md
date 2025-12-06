# Virtual Environment Setup (RECOMMENDED)

## The Issue
Modern Python (via Homebrew) protects system packages with PEP 668. This is GOOD - it prevents breaking your system Python.

## Solution: Use Virtual Environment (Best Practice)

### Automatic Setup (Recommended)
```bash
# This will create and configure a virtual environment automatically
make test-setup
```

The script will:
1. Create a `venv/` directory
2. Install all test dependencies inside it
3. Keep your system Python clean

### Manual Setup
```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate

# Install dependencies
pip install -r tests/requirements.txt

# Run tests
pytest tests/unit/nginx -v
```

### Using the Virtual Environment

#### Every Time You Want to Run Tests:
```bash
# Activate the virtual environment
source venv/bin/activate

# Now you can run tests
make test
pytest tests/unit/nginx -v

# When done, deactivate
deactivate
```

#### Or Run Directly Without Activation:
```bash
# Use the venv Python directly
./venv/bin/pytest tests/unit/nginx -v

# Or run all tests
./venv/bin/pytest tests/ -v
```

## Quick Commands

```bash
# Setup once
make test-setup

# Run tests (after setup)
source venv/bin/activate
make test

# Or run directly
./venv/bin/pytest tests/unit/nginx -v
```

## Add to .gitignore

The `venv/` directory should be in .gitignore:
```bash
echo "venv/" >> .gitignore
```

## Benefits of Virtual Environment

✅ Isolated dependencies - won't break system Python
✅ Project-specific versions - different projects can have different package versions
✅ Reproducible - same environment across team members
✅ Safe - can delete `venv/` and recreate anytime
✅ Best practice - industry standard approach

## Troubleshooting

### Issue: "No module named 'pytest'"
**Solution**: Make sure virtual environment is activated
```bash
source venv/bin/activate
pip install -r tests/requirements.txt
```

### Issue: Want to start fresh
**Solution**: Delete and recreate
```bash
rm -rf venv
make test-setup
```

### Issue: Don't want to activate every time
**Solution**: Use direct path
```bash
# Add to your Makefile or scripts
./venv/bin/pytest tests/ -v
```

## Alternative: Docker (No Python Install Needed)

If you prefer not to manage Python locally at all:

```bash
docker run --rm \
  -v $(pwd):/app \
  -w /app \
  python:3.10-alpine \
  sh -c "pip install -r tests/requirements.txt && pytest tests/unit/nginx -v"
```

## Summary

**Recommended approach:**
1. Run `make test-setup` (creates venv automatically)
2. Run `source venv/bin/activate` (when you want to run tests)
3. Run tests: `make test` or `pytest tests/unit/nginx -v`

This is the **industry standard** and **safest** way to manage Python dependencies!

