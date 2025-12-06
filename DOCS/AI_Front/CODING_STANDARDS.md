# Coding Standards

This document outlines the coding standards and conventions for the AI Front project.

## Table of Contents

1. [File Naming](#file-naming)
2. [Code Style](#code-style)
3. [TypeScript](#typescript)
4. [Vue Components](#vue-components)
5. [Import Organization](#import-organization)
6. [Documentation](#documentation)
7. [Error Handling](#error-handling)

## File Naming

### Components
- Use **kebab-case** for all Vue component files
- Examples: `user-profile.vue`, `auth-button.vue`, `counter-display.vue`

### TypeScript/JavaScript Files
- Use **kebab-case** for all TS/JS files
- Examples: `use-auth.ts`, `api-client.ts`, `counter-validator.ts`

### Test Files
- Same name as source file with `.spec.ts` or `.test.ts` suffix
- Examples: `counter-store.spec.ts`, `auth-service.test.ts`

## Code Style

### Quotes and Semicolons
```typescript
// ✅ Good: Single quotes with semicolons
const message = 'Hello, world';
const name = 'John Doe';

// ❌ Bad: Double quotes or missing semicolons
const message = "Hello, world"
const name = "John Doe"
```

### Line Length
- Maximum 120 characters per line
- Break long lines at logical points

### Indentation
- Use 2 spaces for indentation
- No tabs

### Trailing Commas
```typescript
// ✅ Good: Trailing commas in multi-line structures
const obj = {
  foo: 1,
  bar: 2,
};

const arr = [
  'item1',
  'item2',
];

// ❌ Bad: Missing trailing commas
const obj = {
  foo: 1,
  bar: 2
};
```

### Arrow Functions
```typescript
// ✅ Good: Prefer arrow functions
const double = (x: number): number => x * 2;
const greet = (name: string): string => `Hello, ${name}`;

// ❌ Bad: Function expressions
const double = function(x: number): number {
  return x * 2;
};
```

## TypeScript

### Strict Mode
- Always use TypeScript strict mode
- No `any` types - use `unknown` or proper typing

```typescript
// ✅ Good: Explicit types
function processData(data: UserData): Result {
  return transformData(data);
}

// ❌ Bad: Using any
function processData(data: any): any {
  return transformData(data);
}
```

### Explicit Return Types
```typescript
// ✅ Good: Explicit return type
export function calculateTotal(items: Item[]): number {
  return items.reduce((sum, item) => sum + item.price, 0);
}

// ❌ Bad: Implicit return type
export function calculateTotal(items: Item[]) {
  return items.reduce((sum, item) => sum + item.price, 0);
}
```

### Interfaces vs Types
```typescript
// ✅ Good: Use interfaces for object shapes
export interface User {
  id: string;
  name: string;
  email: string;
}

// ✅ Good: Use type for unions and complex types
export type UserRole = 'admin' | 'user' | 'guest';
export type Result<T> = Success<T> | Error;
```

## Vue Components

### Component Structure
Use Composition API with standard `<script>` syntax (not `<script setup>`):

```vue
<template>
  <!-- Template here -->
</template>

<script lang="ts">
import { defineComponent, ref, computed, onMounted } from 'vue';
import type { PropType } from 'vue';

/**
 * Component description
 */
export default defineComponent({
  name: 'ComponentName',

  props: {
    // Props definition
  },

  emits: {
    // Emits definition
  },

  setup(props, { emit }) {
    // 1. Imports (external → internal → types → styles)
    // 2. Props access
    // 3. Emits definition
    // 4. Composables
    // 5. Reactive state (ref, reactive)
    // 6. Computed properties
    // 7. Methods/functions
    // 8. Lifecycle hooks
    // 9. Return statement

    return {
      // Exposed API
    };
  },
});
</script>
```

### Props Definition
```typescript
props: {
  userId: {
    type: String as PropType<string>,
    required: true,
  },
  
  isActive: {
    type: Boolean as PropType<boolean>,
    default: false,
  },
  
  items: {
    type: Array as PropType<Item[]>,
    required: true,
  },
}
```

### Emits Definition
```typescript
emits: {
  /**
   * Emitted when user clicks the button
   */
  click: (event: MouseEvent) => true,
  
  /**
   * Emitted when value changes
   */
  'update:modelValue': (value: string) => true,
}
```

## Import Organization

Imports must be organized in strict order with blank lines between groups:

```typescript
// 1. Node built-in modules
import { fileURLToPath } from 'node:url';

// 2. External dependencies
import { createApp } from 'vue';
import { createPinia } from 'pinia';

// 3. Internal application modules
import App from './App.vue';
import router from '@core/router';
import { useAuthStore } from '@features/auth';

// 4. Type imports
import type { User } from '@shared/types';
import type { RouteRecordRaw } from 'vue-router';

// 5. CSS/asset imports
import './assets/main.css';
```

## Documentation

### JSDoc Requirements

All exported functions, classes, and composables must have JSDoc:

```typescript
/**
 * Fetches user data from the API with error handling and caching
 * 
 * @param userId - The unique identifier of the user
 * @returns Promise resolving to user data object
 * @throws {ApiError} When the API request fails
 * @throws {ValidationError} When userId is invalid
 * @example
 * const user = await fetchUser('123');
 * console.log(user.name);
 */
export async function fetchUser(userId: string): Promise<User> {
  // Implementation
}
```

### JSDoc Tags
- `@description` - Clear description of purpose
- `@param` - Each parameter with type and description
- `@returns` - Return value type and description
- `@throws` - Document any thrown errors
- `@example` - Usage example for complex functions

## Error Handling

### Comprehensive Error Handling
```typescript
// ✅ Good: Comprehensive error handling
async function fetchData(): Promise<Data> {
  try {
    const response = await api.get('/data');
    return processResponse(response);
  } catch (error) {
    if (error instanceof NetworkError) {
      Logger.error('Network request failed', error);
      throw new ApiError('Unable to fetch data. Please check your connection.');
    }
    if (error instanceof ValidationError) {
      Logger.error('Validation failed', error);
      throw new ApiError('Invalid data received from server.');
    }
    Logger.error('Unexpected error', error);
    throw error;
  }
}

// ❌ Bad: Generic error handling
async function fetchData(): Promise<Data> {
  try {
    return await api.get('/data');
  } catch (error) {
    console.log('Error:', error);
    throw error;
  }
}
```

### Custom Error Classes
```typescript
export class ApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public statusCode?: number
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
```

## Anti-Patterns to Avoid

### Forbidden Practices
1. ❌ Using `any` type
2. ❌ Console.log in production code
3. ❌ Commented-out code
4. ❌ Magic numbers/strings (use constants)
5. ❌ Deeply nested conditionals
6. ❌ Functions longer than 50 lines
7. ❌ Cyclomatic complexity > 10
8. ❌ Mutating props in Vue components
9. ❌ Direct DOM manipulation (use refs)

### Code Smells Requiring Refactoring
1. 🔄 Duplicate code (DRY principle)
2. 🔄 Large components (split into smaller components)
3. 🔄 Complex conditionals (extract to functions)
4. 🔄 Inline styles (use Tailwind classes)
5. 🔄 Missing error handling
6. 🔄 Missing tests
7. 🔄 Insufficient type safety

## Code Review Checklist

Before submitting code for review:

- [ ] All linting rules pass
- [ ] Code is formatted with Prettier
- [ ] TypeScript has no errors
- [ ] All functions have JSDoc documentation
- [ ] Tests are written and pass (90%+ coverage)
- [ ] Error handling is comprehensive
- [ ] No console.log statements
- [ ] No commented-out code
- [ ] Imports are properly organized
- [ ] Component props have proper types
- [ ] Emits are properly documented

## Enforcement

These standards are enforced through:
- ESLint configuration
- Prettier configuration
- TypeScript strict mode
- Pre-commit hooks (Husky)
- Code review process
- Cursor AI assistant rules

For questions or clarifications, refer to the [Cursor AI documentation](./CURSOR_AI.md).

