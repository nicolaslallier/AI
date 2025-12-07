# How to Run Tests - Quick Guide

## First Time Setup (One Time Only)

### Step 1: Install Python 3.12

```bash
# Install Python 3.12 (if you have Python 3.14)
brew install python@3.12
```

### Step 2: Setup Test Environment

```bash
# Run the automated setup script
./QUICK_START_TESTING.sh

# OR manually
rm -rf venv
python3.12 -m venv venv
source venv/bin/activate
pip install -r tests/requirements.txt
```

### Step 3: Verify Setup

```bash
source venv/bin/activate
python --version  # Should show 3.12.x
pytest --version  # Should show pytest version
```

## Running Tests

### Option 1: Using Make (Recommended)

```bash
# Run all tests
make test

# Run specific test suites
make test-unit          # Unit tests only
make test-integration   # Integration tests only
make test-e2e          # End-to-end tests only
make test-nginx        # Nginx-specific tests only
```

**Note:** The Makefile commands now automatically activate the virtual environment!

### Option 2: Using pytest Directly

```bash
# Activate venv first
source venv/bin/activate

# Run all unit tests
pytest tests/unit -v

# Run specific test file
pytest tests/unit/nginx/test_nginx_config_syntax.py -v

# Run with coverage
pytest tests/unit --cov --cov-report=html

# Run tests matching a pattern
pytest tests/unit -k "nginx" -v
```

### Option 3: Using Test Scripts

```bash
# These now auto-activate the venv!
./scripts/test/run-unit-tests.sh
./scripts/test/run-integration-tests.sh
./scripts/test/run-e2e-tests.sh
./scripts/test/run-all-tests.sh
```

## Quick Test Examples

### Test Nginx Configuration

```bash
source venv/bin/activate
pytest tests/unit/nginx/test_nginx_config_syntax.py -v
```

### Test Database Connection

```bash
source venv/bin/activate
pytest tests/unit/database/test_postgres_connections.py -v
```

### Test with Specific Markers

```bash
source venv/bin/activate
pytest tests/ -m "unit" -v              # Only unit tests
pytest tests/ -m "integration" -v       # Only integration tests
pytest tests/ -m "nginx" -v             # Only nginx tests
```

## Troubleshooting

### Error: "pytest: command not found"

**Solution:** Activate the virtual environment first
```bash
source venv/bin/activate
```

### Error: "No module named 'pytest'"

**Solution:** Install dependencies
```bash
source venv/bin/activate
pip install -r tests/requirements.txt
```

### Error: "Virtual environment not found"

**Solution:** Run setup first
```bash
./QUICK_START_TESTING.sh
# OR
make test-setup
```

### Error: Python 3.14 compatibility issues

**Solution:** Use Python 3.12
```bash
brew install python@3.12
rm -rf venv
python3.12 -m venv venv
source venv/bin/activate
pip install -r tests/requirements.txt
```

## Test Reports

After running tests, reports are generated in:

- **HTML Coverage Report:** `tests/reports/coverage-html/index.html`
- **JUnit XML:** `tests/reports/junit-*.xml`
- **HTML Test Report:** `tests/reports/*-tests.html`

View reports:
```bash
open tests/reports/coverage-html/index.html
open tests/reports/unit-tests.html
```

## Common Workflows

### Daily Development Testing

```bash
# Quick unit test run
source venv/bin/activate
pytest tests/unit/nginx -v
```

### Before Committing Code

```bash
# Run all tests
make test

# Or run unit + linting
make test-unit
make lint
```

### CI/CD Pipeline Testing

```bash
# Full test suite with coverage
make test-setup
make test
```

### Testing Specific Components

```bash
source venv/bin/activate

# Test Nginx
pytest tests/unit/nginx -v

# Test Database
pytest tests/unit/database -v

# Test Keycloak
pytest tests/unit/keycloak -v
```

## Quick Reference

```bash
# Setup (once)
./QUICK_START_TESTING.sh

# Activate venv (each session)
source venv/bin/activate

# Run tests
make test                    # All tests
make test-unit               # Unit tests only
pytest tests/unit/nginx -v   # Specific tests

# View reports
open tests/reports/coverage-html/index.html
```

## Summary

1. ✅ Run `./QUICK_START_TESTING.sh` (first time only)
2. ✅ Always activate venv: `source venv/bin/activate`
3. ✅ Run tests: `make test` or `pytest tests/unit -v`
4. ✅ View reports in `tests/reports/`

That's it! 🎉

