# Testing Strategy

## Overview

This project maintains a minimum of 90% test coverage with a focus on Test-Driven Development (TDD).

## Test Types

### Unit Tests
- Test individual functions/methods
- Fast execution
- Mock external dependencies
- Focus on edge cases

### Component Tests
- Test Vue components in isolation
- Use Vue Test Utils
- Test component behavior, not implementation
- Verify props, events, slots

### Integration Tests
- Test feature modules as a whole
- Verify component interactions
- Test composable + store integration

### E2E Tests
- Test user workflows
- Use Playwright
- Test critical paths
- Run in CI/CD pipeline

## Running Tests

```bash
# Unit and component tests
make test

# Watch mode (TDD)
make test-watch

# E2E tests
make test-e2e

# Coverage report
make test-coverage
```

## Coverage Requirements

- **Lines**: 90%+
- **Functions**: 90%+
- **Branches**: 90%+
- **Statements**: 90%+

Tests are blocking in CI/CD if coverage falls below thresholds.

## Best Practices

1. Write tests before implementation (TDD)
2. Test behavior, not implementation
3. Use descriptive test names
4. Follow AAA pattern (Arrange, Act, Assert)
5. One assertion per test (when practical)
6. Mock external dependencies
7. Test error cases and edge cases

For detailed TDD practices, see [TDD Guide](./TDD_GUIDE.md).

