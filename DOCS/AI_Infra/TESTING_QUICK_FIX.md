# Quick Fix - Python Environment Issues

## The Issues

### Issue 1: pip not found
```
./scripts/test/setup-test-env.sh: line 18: pip: command not found
```

### Issue 2: Externally-managed-environment (PEP 668)
```
error: externally-managed-environment
× This environment is externally managed
```

This is GOOD - modern Python protects your system packages!

## ✅ RECOMMENDED Solution: Virtual Environment

### One Command Setup

```bash
make test-setup
```

This now automatically creates a virtual environment (venv/) and installs everything safely!

### Then Run Tests
```bash
# Activate the virtual environment
source venv/bin/activate

# Run tests
make test
# or
pytest tests/unit/nginx -v

# When done
deactivate
```

## Alternative Solutions

### Solution 1: Manual Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r tests/requirements.txt
pytest tests/unit/nginx -v
```

### Solution 2: Use Docker (No Python Install Needed)
```bash
# Run tests in Docker
docker-compose exec -T postgres pytest --version || \
docker run --rm -v $(pwd):/app -w /app python:3.10 sh -c "pip install -r tests/requirements.txt && pytest tests/unit/nginx -v"
```

### Solution 3: Direct venv execution (no activation needed)
```bash
# After make test-setup
./venv/bin/pytest tests/unit/nginx -v
```

## What Changed

The setup script now automatically:
1. ✅ Creates a virtual environment (`venv/`)
2. ✅ Installs all dependencies inside it
3. ✅ Keeps your system Python clean
4. ✅ Follows Python best practices (PEP 668)

This is the **industry standard** approach!

## Test It Works

```bash
# Verify Python
python3 --version

# Verify pip
pip3 --version

# Install dependencies
pip3 install -r tests/requirements.txt

# Run a quick test
pytest tests/unit/nginx/test_nginx_config_syntax.py -v
```

## No Python? No Problem!

Run tests entirely in Docker:
```bash
docker run --rm \
  -v $(pwd):/app \
  -w /app \
  python:3.10-alpine \
  sh -c "pip install -r tests/requirements.txt && pytest tests/unit/nginx -v"
```

Choose the solution that works best for your setup!
