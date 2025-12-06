# Architecture Documentation

## Overview

AI Front is built using a feature-based architecture with strict adherence to SOLID principles and clean code practices.

## Architecture Layers

### 1. Features Layer (`src/features/`)

Self-contained feature modules with all related code:

```
features/
└── counter/
    ├── components/      # Feature-specific components
    ├── composables/     # Feature hooks
    ├── stores/          # Pinia stores
    ├── types/           # TypeScript types
    ├── utils/           # Utility functions
    ├── views/           # Page components
    └── index.ts         # Public API
```

**Benefits:**
- High cohesion within features
- Low coupling between features
- Easy to add/remove features
- Clear ownership and boundaries

### 2. Shared Layer (`src/shared/`)

Reusable code across multiple features:

```
shared/
├── components/     # Reusable UI components
├── composables/    # Shared hooks
├── types/          # Common type definitions
└── utils/          # Helper functions
```

### 3. Core Layer (`src/core/`)

Application-wide concerns:

```
core/
├── router/         # Vue Router configuration
├── config/         # App configuration
└── services/       # Shared services
```

## Data Flow

```
User Interaction
    ↓
Component (View)
    ↓
Event Handler
    ↓
Composable (use-counter)
    ↓
Store Action (counter-store)
    ↓
State Update
    ↓
Reactive Update to Component
```

## State Management

### Pinia Stores
- Feature-specific stores
- Composition API style
- Strict typing
- Minimal, focused responsibilities

### Composables
- Abstraction layer over stores
- Expose only what's needed
- Make testing easier
- Follow Interface Segregation Principle

## Component Architecture

### Component Hierarchy

```
App.vue
└── RouterView
    └── HomeView (Container)
        ├── CounterDisplay (Presentational)
        ├── CounterControls (Presentational)
        └── CounterHistory (Presentational)
```

### Component Types

**Container Components**
- Handle business logic
- Connect to stores/composables
- Pass data to presentational components
- Handle errors

**Presentational Components**
- Pure UI components
- Receive data via props
- Emit events for interactions
- No direct store access

## Design Patterns

### 1. Composable Pattern
- Reusable logic extraction
- Better than mixins
- Type-safe
- Easy to test

### 2. Provider/Injection Pattern
- For deep dependencies
- Avoid prop drilling
- Maintain loose coupling

### 3. Factory Pattern
- Create services/clients
- Enable dependency injection
- Support testing

## Testing Strategy

See [Testing Documentation](./TESTING.md) for details.

## Build & Deployment

See [CI/CD Documentation](./CICD.md) and [Docker Documentation](./DOCKER.md).

