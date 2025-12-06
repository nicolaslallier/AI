# Testing Guide

Comprehensive testing framework for the AI Infrastructure.

## Quick Start

```bash
# Install dependencies
pip install -r tests/requirements.txt

# Setup test environment
./scripts/test/setup-test-env.sh

# Run all tests
./scripts/test/run-all-tests.sh
```

## Test Structure

```
tests/
├── unit/           # Unit tests for each service
├── integration/    # Integration tests between services  
├── e2e/            # End-to-end user acceptance tests
├── performance/    # k6 load and performance tests
├── api/            # Postman/Newman API tests
├── regression/     # Regression test suite
├── utils/          # Shared test utilities
├── fixtures/       # Test data and mocks
└── config/         # Test configuration

```

## Running Tests

### Unit Tests
```bash
make test-unit
# or
pytest tests/unit -v
```

### Integration Tests
```bash
make test-integration
# or
./scripts/test/run-integration-tests.sh
```

### E2E Tests
```bash
make test-e2e
# or
./scripts/test/run-e2e-tests.sh
```

### All Tests
```bash
make test
# or
./scripts/test/run-all-tests.sh
```

## Test Coverage

Coverage reports are generated in `tests/reports/coverage-html/`

Target coverage: 95%+ for unit tests

## Writing Tests

### Unit Test Example
```python
import pytest

@pytest.mark.unit
def test_example():
    assert True
```

### Integration Test Example
```python
import pytest

@pytest.mark.integration
@pytest.mark.docker
def test_service_integration():
    # Test service interactions
    pass
```

## CI/CD Integration

Tests can be run in CI pipelines using:
```bash
make ci-test
```

## Documentation

- [TESTING_STRATEGY.md](TESTING_STRATEGY.md) - Testing approach
- [TEST_COVERAGE.md](TEST_COVERAGE.md) - Coverage requirements
