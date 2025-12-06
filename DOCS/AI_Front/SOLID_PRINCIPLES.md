# SOLID Principles in Vue 3

This guide explains how SOLID principles are applied in the AI Front Vue 3 application.

## Table of Contents

1. [Single Responsibility Principle](#single-responsibility-principle)
2. [Open/Closed Principle](#openclosed-principle)
3. [Liskov Substitution Principle](#liskov-substitution-principle)
4. [Interface Segregation Principle](#interface-segregation-principle)
5. [Dependency Inversion Principle](#dependency-inversion-principle)

## Single Responsibility Principle (SRP)

> A class/module should have one, and only one, reason to change.

### In Vue Components

**Bad**: Component doing too much
```vue
<!-- ❌ Bad: UserProfile handles everything -->
<script lang="ts">
export default defineComponent({
  setup() {
    // Fetches user data
    const fetchUser = async () => { /* ... */ };
    
    // Validates form
    const validateForm = () => { /* ... */ };
    
    // Uploads avatar
    const uploadAvatar = () => { /* ... */ };
    
    // Sends notifications
    const sendNotification = () => { /* ... */ };
  },
});
</script>
```

**Good**: Each concern separated
```vue
<!-- ✅ Good: Focused components and composables -->
<script lang="ts">
import { useUserData } from './composables/use-user-data';
import { useFormValidation } from './composables/use-form-validation';
import { useAvatarUpload } from './composables/use-avatar-upload';

export default defineComponent({
  setup() {
    const { user, fetchUser } = useUserData();
    const { validate } = useFormValidation();
    const { upload } = useAvatarUpload();
    
    return { user, fetchUser, validate, upload };
  },
});
</script>
```

### In Stores

```typescript
// ✅ Good: Counter store only manages counter state
export const useCounterStore = defineStore('counter', () => {
  const count = ref(0);
  
  function increment(): void {
    count.value++;
  }
  
  return { count, increment };
});

// ✅ Good: Separate store for user state
export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(null);
  
  function setUser(newUser: User): void {
    user.value = newUser;
  }
  
  return { user, setUser };
});
```

### In Utils

```typescript
// ✅ Good: Each function has single responsibility
export function validateEmail(email: string): boolean {
  // Only validates email
}

export function formatEmail(email: string): string {
  // Only formats email
}

export function sendEmail(to: string, subject: string): Promise<void> {
  // Only sends email
}
```

## Open/Closed Principle (OCP)

> Software entities should be open for extension, closed for modification.

### Using Composition API

```typescript
// ✅ Good: Base composable open for extension
export function useBaseCounter() {
  const count = ref(0);
  
  function increment(): void {
    count.value++;
  }
  
  return { count, increment };
}

// Extend without modifying base
export function useStepCounter(step = 1) {
  const base = useBaseCounter();
  
  function incrementByStep(): void {
    for (let i = 0; i < step; i++) {
      base.increment();
    }
  }
  
  return { ...base, incrementByStep };
}
```

### Using Plugins

```typescript
// ✅ Good: Extend Vue without modifying core
export const analyticsPlugin = {
  install(app: App) {
    app.config.globalProperties.$track = (event: string) => {
      // Track analytics
    };
  },
};

// Usage
app.use(analyticsPlugin);
```

### Strategy Pattern

```typescript
// ✅ Good: Different validators without modifying base
interface Validator {
  validate(value: string): boolean;
}

class EmailValidator implements Validator {
  validate(value: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }
}

class PhoneValidator implements Validator {
  validate(value: string): boolean {
    return /^\d{10}$/.test(value);
  }
}

// Can add new validators without changing existing code
```

## Liskov Substitution Principle (LSP)

> Objects should be replaceable with instances of their subtypes without altering correctness.

### TypeScript Interfaces

```typescript
// ✅ Good: Proper interface contracts
interface DataSource {
  fetch(): Promise<Data>;
}

class ApiDataSource implements DataSource {
  async fetch(): Promise<Data> {
    return await fetchFromApi();
  }
}

class CacheDataSource implements DataSource {
  async fetch(): Promise<Data> {
    return await fetchFromCache();
  }
}

// Both can be used interchangeably
function loadData(source: DataSource): Promise<Data> {
  return source.fetch();
}
```

### Component Props

```vue
<!-- ✅ Good: Components are interchangeable -->
<script lang="ts">
interface ButtonProps {
  label: string;
  onClick: () => void;
}

// PrimaryButton and SecondaryButton both implement ButtonProps
// Can be swapped without breaking parent
</script>
```

### Composables

```typescript
// ✅ Good: Composables with same interface
interface CounterComposable {
  count: ComputedRef<number>;
  increment: () => void;
  reset: () => void;
}

export function useCounter(): CounterComposable {
  const store = useCounterStore();
  return {
    count: computed(() => store.count),
    increment: store.increment,
    reset: store.reset,
  };
}

export function useLocalCounter(): CounterComposable {
  const count = ref(0);
  return {
    count: computed(() => count.value),
    increment: () => count.value++,
    reset: () => count.value = 0,
  };
}

// Both can be used interchangeably
```

## Interface Segregation Principle (ISP)

> Clients should not be forced to depend on interfaces they don't use.

### Focused Composables

```typescript
// ❌ Bad: Large interface with unused methods
interface UserManager {
  getUser(): User;
  updateUser(data: Partial<User>): void;
  deleteUser(): void;
  getUserPermissions(): Permissions;
  updatePermissions(perms: Permissions): void;
  getUserPreferences(): Preferences;
  updatePreferences(prefs: Preferences): void;
}

// ✅ Good: Small, focused composables
export function useUserData() {
  return {
    getUser,
    updateUser,
  };
}

export function useUserPermissions() {
  return {
    getPermissions,
    updatePermissions,
  };
}

export function useUserPreferences() {
  return {
    getPreferences,
    updatePreferences,
  };
}
```

### Component Props

```vue
<!-- ❌ Bad: Too many props -->
<template>
  <user-card
    :id="user.id"
    :name="user.name"
    :email="user.email"
    :avatar="user.avatar"
    :created-at="user.createdAt"
    :updated-at="user.updatedAt"
    :last-login="user.lastLogin"
    :permissions="user.permissions"
  />
</template>

<!-- ✅ Good: Single user object prop -->
<template>
  <user-card :user="user" />
</template>
```

### Store Actions

```typescript
// ✅ Good: Small, focused stores
export const useAuthStore = defineStore('auth', () => {
  // Only auth-related state and actions
  const token = ref<string | null>(null);
  
  function login(credentials: Credentials): Promise<void> {
    // Login logic
  }
  
  function logout(): void {
    // Logout logic
  }
  
  return { token, login, logout };
});

// Separate store for profile
export const useProfileStore = defineStore('profile', () => {
  // Only profile-related state and actions
});
```

## Dependency Inversion Principle (DIP)

> Depend on abstractions, not concretions.

### Using Composables as Abstractions

```typescript
// ❌ Bad: Direct dependency on store
export default defineComponent({
  setup() {
    const store = useCounterStore();
    return { count: store.count };
  },
});

// ✅ Good: Depend on composable abstraction
export default defineComponent({
  setup() {
    const { count } = useCounter(); // Abstraction
    return { count };
  },
});
```

### Dependency Injection

```typescript
// ✅ Good: Inject dependencies
interface ApiClient {
  get(url: string): Promise<unknown>;
  post(url: string, data: unknown): Promise<unknown>;
}

export function createUserService(client: ApiClient) {
  return {
    async getUser(id: string): Promise<User> {
      return await client.get(`/users/${id}`) as User;
    },
  };
}

// Easy to test with mock client
const mockClient: ApiClient = {
  get: vi.fn(),
  post: vi.fn(),
};

const service = createUserService(mockClient);
```

### Props as Dependencies

```vue
<!-- ✅ Good: Pass dependencies as props -->
<template>
  <user-list :fetcher="userFetcher" />
</template>

<script lang="ts">
export default defineComponent({
  props: {
    fetcher: {
      type: Function as PropType<() => Promise<User[]>>,
      required: true,
    },
  },
  
  async setup(props) {
    const users = await props.fetcher();
    return { users };
  },
});
</script>
```

### Provide/Inject for Deep Dependencies

```typescript
// ✅ Good: Provide abstraction at app level
// main.ts
const apiClient = createApiClient();
app.provide('apiClient', apiClient);

// Component
export default defineComponent({
  setup() {
    const apiClient = inject<ApiClient>('apiClient');
    return { apiClient };
  },
});
```

## SOLID in the Counter Feature

### Single Responsibility

- `counter-validator.ts` - Only validates values
- `counter-store.ts` - Only manages state
- `use-counter.ts` - Only provides interface
- `counter-display.vue` - Only displays UI
- `counter-controls.vue` - Only handles controls

### Open/Closed

- Composables can be extended without modification
- New counter types can be added via new composables
- Store can be extended with plugins

### Liskov Substitution

- `useCounter` interface can be implemented by multiple composables
- Components with same props can be swapped

### Interface Segregation

- Separate composables for different concerns
- Small, focused components
- Minimal props per component

### Dependency Inversion

- Components depend on `useCounter` abstraction, not `useCounterStore`
- Easy to test with mock implementations
- Clear separation between interface and implementation

## Best Practices Checklist

- [ ] Each file has single responsibility
- [ ] Components are small and focused
- [ ] Composables provide clear abstractions
- [ ] Dependencies are injected, not hard-coded
- [ ] Interfaces are small and specific
- [ ] Code is open for extension, closed for modification
- [ ] Related code is grouped by feature, not by type

## Resources

- [SOLID Principles Explained](https://en.wikipedia.org/wiki/SOLID)
- [Clean Architecture](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [Vue 3 Composition API](https://vuejs.org/guide/extras/composition-api-faq.html)

## Next Steps

- Review [Architecture Documentation](./ARCHITECTURE.md)
- Study [Coding Standards](./CODING_STANDARDS.md)
- Practice [TDD](./TDD_GUIDE.md)

