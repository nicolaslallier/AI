# Quick Start - Testing

## 🚀 Get Started in 3 Minutes

### 1. Install Dependencies
```bash
pip install -r tests/requirements.txt
```

### 2. Setup Test Environment
```bash
make test-setup
```

### 3. Run Tests
```bash
# Run everything
make test

# Or run specific tests
make test-unit         # Unit tests only
make test-nginx        # Nginx tests
```

## 📊 View Results

```bash
# Open coverage report
open tests/reports/coverage-html/index.html

# View test reports
ls -lh tests/reports/
```

## 🎯 Common Commands

```bash
make test              # Run all tests
make test-unit         # Unit tests
make test-integration  # Integration tests
make test-e2e          # End-to-end tests
make test-coverage     # Coverage report
make test-clean        # Clean artifacts
```

## 📖 Documentation

- `TESTING.md` - Complete guide
- `TESTING_COMPLETE.md` - Implementation details
- `tests/README.md` - Quick reference

## 💡 Examples

See `tests/unit/nginx/` for complete test examples.

Use utilities from `tests/utils/` for common operations.

## ✅ What's Ready

- ✅ Complete Nginx tests (81+ test cases)
- ✅ All test utilities (50+ functions)
- ✅ Test automation scripts
- ✅ Makefile targets
- ✅ Documentation

Ready to use! 🎉
