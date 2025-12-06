# Test-Driven Development Guide

This guide explains the TDD approach used in the AI Front project and provides best practices for writing tests.

## Table of Contents

1. [TDD Philosophy](#tdd-philosophy)
2. [Test Structure](#test-structure)
3. [Writing Tests](#writing-tests)
4. [Coverage Requirements](#coverage-requirements)
5. [Test Types](#test-types)
6. [Best Practices](#best-practices)

## TDD Philosophy

### Red-Green-Refactor Cycle

```
1. 🔴 RED: Write a failing test
2. 🟢 GREEN: Write minimal code to make it pass
3. 🔵 REFACTOR: Improve code while keeping tests green
```

### Why TDD?

- **Design First**: Tests force you to think about the API before implementation
- **Documentation**: Tests serve as living documentation
- **Confidence**: Comprehensive tests enable safe refactoring
- **Quality**: Catches bugs early in development
- **Coverage**: Ensures all code paths are tested

## Test Structure

### File Organization

```
src/
├── features/
│   └── counter/
│       ├── utils/
│       │   ├── counter-validator.ts
│       │   └── counter-validator.spec.ts  # Test next to source
│       ├── stores/
│       │   ├── counter-store.ts
│       │   └── counter-store.spec.ts
│       └── composables/
│           ├── use-counter.ts
│           └── use-counter.spec.ts
└── tests/
    └── e2e/
        └── counter.spec.ts  # E2E tests separate
```

### Test File Structure

```typescript
import { describe, it, expect, beforeEach, afterEach } from 'vitest';

describe('FeatureName or FunctionName', () => {
  // Setup and teardown
  beforeEach(() => {
    // Runs before each test
  });

  afterEach(() => {
    // Runs after each test
  });

  describe('specific functionality', () => {
    it('should behave in expected way when condition', () => {
      // Arrange
      const input = setupTestData();

      // Act
      const result = functionUnderTest(input);

      // Assert
      expect(result).toBe(expectedValue);
    });
  });
});
```

## Writing Tests

### AAA Pattern: Arrange, Act, Assert

```typescript
it('should increment counter by specified amount', () => {
  // Arrange - Set up test data and conditions
  const store = useCounterStore();
  const initialValue = store.count;
  const increment = 5;

  // Act - Execute the function/method being tested
  store.increment(increment);

  // Assert - Verify the expected outcome
  expect(store.count).toBe(initialValue + increment);
});
```

### Test Naming Conventions

Use descriptive names that explain:
- **What** is being tested
- **When** (under what conditions)
- **Expected behavior**

```typescript
// ✅ Good: Clear and descriptive
it('should throw RangeError when value exceeds maximum limit', () => {
  expect(() => validateCounterValue(1001)).toThrow(RangeError);
});

// ❌ Bad: Vague and unclear
it('should work', () => {
  expect(true).toBe(true);
});
```

### Testing Edge Cases

Always test:
- **Happy path**: Normal, expected usage
- **Edge cases**: Boundary values, empty inputs
- **Error cases**: Invalid inputs, error conditions

```typescript
describe('validateCounterValue', () => {
  // Happy path
  it('should return true for valid values within range', () => {
    expect(validateCounterValue(0)).toBe(true);
    expect(validateCounterValue(500)).toBe(true);
  });

  // Edge cases
  it('should accept boundary values', () => {
    expect(validateCounterValue(1000)).toBe(true);
    expect(validateCounterValue(-1000)).toBe(true);
  });

  // Error cases
  it('should throw RangeError when value exceeds maximum', () => {
    expect(() => validateCounterValue(1001)).toThrow(RangeError);
  });
});
```

## Coverage Requirements

### Minimum Thresholds

The project enforces **90% coverage** across:
- Lines
- Functions
- Branches
- Statements

### Running Coverage

```bash
# Generate coverage report
make test

# View coverage report in browser
make test-coverage
```

### What to Cover

**Always Test:**
- ✅ All exported functions
- ✅ All public methods
- ✅ All branches (if/else, switch)
- ✅ Error handling paths
- ✅ Edge cases and boundaries

**Can Skip:**
- ❌ Type definitions
- ❌ Configuration files
- ❌ Main entry point
- ❌ Simple getters/setters with no logic

## Test Types

### Unit Tests

Test individual functions/methods in isolation:

```typescript
// counter-validator.spec.ts
describe('validateStepValue', () => {
  it('should return true for valid positive steps', () => {
    expect(validateStepValue(1)).toBe(true);
    expect(validateStepValue(10)).toBe(true);
  });

  it('should throw RangeError when step is zero', () => {
    expect(() => validateStepValue(0)).toThrow(RangeError);
  });
});
```

### Component Tests

Test Vue components with Vue Test Utils:

```typescript
import { mount } from '@vue/test-utils';
import CounterDisplay from './counter-display.vue';

describe('CounterDisplay', () => {
  it('should display the count value', () => {
    const wrapper = mount(CounterDisplay, {
      props: {
        count: 42,
        doubleCount: 84,
      },
    });

    expect(wrapper.text()).toContain('42');
  });

  it('should apply positive color class when count is positive', () => {
    const wrapper = mount(CounterDisplay, {
      props: {
        count: 5,
        doubleCount: 10,
        isPositive: true,
      },
    });

    expect(wrapper.find('.text-green-600').exists()).toBe(true);
  });
});
```

### Store Tests

Test Pinia stores with proper setup:

```typescript
import { setActivePinia, createPinia } from 'pinia';
import { useCounterStore } from './counter-store';

describe('counter-store', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('should increment count by 1', () => {
    const store = useCounterStore();
    store.increment();
    expect(store.count).toBe(1);
  });
});
```

### Composable Tests

Test composables that use stores:

```typescript
import { setActivePinia, createPinia } from 'pinia';
import { useCounter } from './use-counter';

describe('use-counter', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('should provide counter functionality', () => {
    const { count, increment } = useCounter();
    increment();
    expect(count.value).toBe(1);
  });
});
```

### E2E Tests

Test user workflows with Playwright:

```typescript
import { test, expect } from '@playwright/test';

test.describe('Counter Feature', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should increment counter when button clicked', async ({ page }) => {
    await page.getByRole('button', { name: 'Increment' }).click();
    await expect(page.locator('text=/^1$/').first()).toBeVisible();
  });
});
```

## Best Practices

### 1. One Assertion Per Test (When Possible)

```typescript
// ✅ Good: Single, focused assertion
it('should increment count', () => {
  store.increment();
  expect(store.count).toBe(1);
});

it('should add value to history', () => {
  store.increment();
  expect(store.history).toContain(1);
});

// ❌ Bad: Multiple unrelated assertions
it('should increment', () => {
  store.increment();
  expect(store.count).toBe(1);
  expect(store.isPositive).toBe(true);
  expect(store.doubleCount).toBe(2);
  expect(store.history.length).toBe(2);
});
```

### 2. Test Behavior, Not Implementation

```typescript
// ✅ Good: Tests behavior
it('should display error message when validation fails', () => {
  const wrapper = mount(LoginForm);
  wrapper.find('input[type="email"]').setValue('invalid');
  wrapper.find('form').trigger('submit');
  expect(wrapper.text()).toContain('Invalid email');
});

// ❌ Bad: Tests implementation details
it('should set isError to true', () => {
  const wrapper = mount(LoginForm);
  expect(wrapper.vm.isError).toBe(true);
});
```

### 3. Use Descriptive Test Data

```typescript
// ✅ Good: Clear test data
const validUser = {
  id: '123',
  name: 'John Doe',
  email: 'john@example.com',
};

// ❌ Bad: Unclear test data
const user = {
  id: '1',
  name: 'a',
  email: 'a@a.com',
};
```

### 4. Mock External Dependencies

```typescript
import { vi } from 'vitest';

it('should fetch user data from API', async () => {
  // Mock the API call
  const mockFetch = vi.fn().mockResolvedValue({
    id: '123',
    name: 'John Doe',
  });

  const result = await fetchUser('123', mockFetch);
  
  expect(mockFetch).toHaveBeenCalledWith('/users/123');
  expect(result.name).toBe('John Doe');
});
```

### 5. Test Error Paths

```typescript
it('should throw ApiError when request fails', async () => {
  const mockFetch = vi.fn().mockRejectedValue(new Error('Network error'));
  
  await expect(fetchUser('123', mockFetch)).rejects.toThrow(ApiError);
});
```

## TDD Workflow Example

### Step 1: Write the Test (Red)

```typescript
// counter-validator.spec.ts
describe('validateCounterValue', () => {
  it('should return true for valid values', () => {
    expect(validateCounterValue(0)).toBe(true);
  });
});
```

### Step 2: Run Test (Should Fail)

```bash
npm run test:watch
# Test fails: validateCounterValue is not defined
```

### Step 3: Write Minimal Code (Green)

```typescript
// counter-validator.ts
export function validateCounterValue(value: number): boolean {
  return true; // Minimal implementation
}
```

### Step 4: Add More Tests

```typescript
it('should throw error for values exceeding maximum', () => {
  expect(() => validateCounterValue(1001)).toThrow(RangeError);
});
```

### Step 5: Implement Full Logic

```typescript
export function validateCounterValue(value: number, max = 1000): boolean {
  if (value > max) {
    throw new RangeError(`Value cannot exceed ${max}`);
  }
  return true;
}
```

### Step 6: Refactor

```typescript
export function validateCounterValue(
  value: number,
  min = -1000,
  max = 1000
): boolean {
  if (value < min || value > max) {
    throw new RangeError(`Value must be between ${min} and ${max}`);
  }
  return true;
}
```

## Common Testing Patterns

### Testing Async Operations

```typescript
it('should fetch data successfully', async () => {
  const data = await fetchData();
  expect(data).toBeDefined();
});
```

### Testing Computed Properties

```typescript
it('should calculate doubleCount correctly', () => {
  const store = useCounterStore();
  store.setValue(5);
  expect(store.doubleCount).toBe(10);
});
```

### Testing Reactive State

```typescript
it('should update reactive state', async () => {
  const { count, increment } = useCounter();
  
  increment();
  
  await nextTick(); // Wait for reactivity
  expect(count.value).toBe(1);
});
```

## Troubleshooting

### Common Issues

**Issue**: Tests pass individually but fail together
**Solution**: Clean up state in `beforeEach` or `afterEach`

**Issue**: Async tests are flaky
**Solution**: Use `await` properly and `waitFor` utilities

**Issue**: Coverage is not reaching 90%
**Solution**: Check coverage report to find untested branches

## Resources

- [Vitest Documentation](https://vitest.dev)
- [Vue Test Utils](https://test-utils.vuejs.org)
- [Playwright Documentation](https://playwright.dev)
- [Testing Library Best Practices](https://kentcdodds.com/blog/common-mistakes-with-react-testing-library)

## Next Steps

- Review [Testing Strategy](./TESTING.md)
- Learn about [SOLID Principles](./SOLID_PRINCIPLES.md)
- Read [Coding Standards](./CODING_STANDARDS.md)

