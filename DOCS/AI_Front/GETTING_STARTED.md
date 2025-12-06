# Getting Started with AI Front

Welcome to your new Vue 3 SPA development environment! This guide will help you get up and running quickly.

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd "/Users/nicolaslallier/Dev Nick/AI_Front"
make install
```

This will:
- Install all npm packages with exact versions
- Set up git hooks (Husky)
- Install Playwright browsers for E2E testing

### 2. Start Development Server

```bash
make dev
```

The application will open automatically at http://localhost:3000

### 3. Run Tests

```bash
# Watch mode (TDD)
make test-watch

# Single run with coverage
make test
```

## 📁 Project Structure

```
AI_Front/
├── src/
│   ├── features/          # Feature modules (counter example included)
│   ├── shared/            # Shared utilities and components
│   ├── core/              # Core app logic (router, config)
│   ├── assets/            # Static assets
│   ├── App.vue            # Root component
│   └── main.ts            # Entry point
├── tests/
│   └── e2e/               # Playwright E2E tests
├── docs/                  # Comprehensive documentation
├── Makefile               # CI/CD automation
├── Dockerfile             # Multi-stage Docker build
├── .cursorrules           # Cursor AI configuration
└── README.md              # Main documentation
```

## 🎯 What's Included

### Development Tools
✅ **Vue 3** with Composition API
✅ **TypeScript** with strict mode
✅ **Tailwind CSS** for styling
✅ **Vite** for fast builds
✅ **ESLint** + **Prettier** (auto-enforced)
✅ **Vitest** for unit tests (90%+ coverage required)
✅ **Playwright** for E2E tests

### Quality Assurance
✅ **Husky** git hooks (pre-commit checks)
✅ **Commitlint** (conventional commits)
✅ **90% test coverage** threshold
✅ **JSDoc** documentation requirements
✅ **SOLID principles** enforcement

### Deployment
✅ **Docker** with multi-stage builds
✅ **Makefile** CI/CD automation
✅ **GitHub Actions**, **GitLab CI**, **Jenkins** configs
✅ **Nginx** production configuration

## 🏗️ Architecture Overview

This project uses a **feature-based architecture**:

```
features/
└── counter/              # Example feature
    ├── components/       # UI components
    ├── composables/      # Business logic hooks
    ├── stores/           # Pinia state management
    ├── types/            # TypeScript definitions
    ├── utils/            # Helper functions
    ├── views/            # Page components
    └── index.ts          # Public API
```

Each feature is self-contained and follows SOLID principles.

## 📚 Essential Documentation

Start with these documents:

1. **[README.md](./README.md)** - Main documentation and commands
2. **[docs/CODING_STANDARDS.md](./docs/CODING_STANDARDS.md)** - Code style rules
3. **[docs/TDD_GUIDE.md](./docs/TDD_GUIDE.md)** - Testing approach
4. **[docs/CURSOR_AI.md](./docs/CURSOR_AI.md)** - Working with AI assistant
5. **[docs/SOLID_PRINCIPLES.md](./docs/SOLID_PRINCIPLES.md)** - Architecture principles

## 💻 Common Commands

### Development
```bash
make dev              # Start dev server
make test-watch       # TDD mode
```

### Code Quality
```bash
make validate         # Run all checks
make lint-fix         # Fix linting issues
make format           # Format code
```

### Testing
```bash
make test             # Unit tests with coverage
make test-e2e         # E2E tests
make test-coverage    # Open coverage report
```

### Build & Deploy
```bash
make build            # Production build
make docker-build     # Build Docker image
make pipeline         # Full CI/CD pipeline
```

## 🎨 Example Feature: Counter

A complete counter feature is included as a reference:

- **View**: `src/features/counter/views/home-view.vue`
- **Components**: Display, controls, history
- **Store**: Pinia store with validation
- **Tests**: 100% coverage with unit and E2E tests
- **Composable**: Abstraction layer over store

Study this feature to understand the architecture.

## 🧪 Test-Driven Development

This project follows strict TDD:

1. **Write test first** (red)
2. **Implement minimal code** (green)
3. **Refactor** while keeping tests green

See `src/features/counter/` for TDD examples.

## 🤖 Cursor AI Assistant

The project includes a `.cursorrules` file that configures Cursor AI to:

- Enforce coding standards automatically
- Always create tests with code
- Provide detailed technical explanations
- Follow SOLID principles
- Generate comprehensive JSDoc

Read [docs/CURSOR_AI.md](./docs/CURSOR_AI.md) to learn how to work effectively with the AI.

## 📝 Coding Standards Highlights

- **Files**: kebab-case (e.g., `user-profile.vue`)
- **Quotes**: Single quotes with semicolons
- **Line Length**: 120 characters max
- **Components**: Composition API (not `<script setup>`)
- **Imports**: Strict ordering (external → internal → types)
- **Documentation**: JSDoc for all public APIs
- **Testing**: 90%+ coverage required

## 🔐 Git Workflow

### Commit Messages

Follow Conventional Commits:

```bash
feat: add user authentication
fix: resolve routing issue
docs: update README
test: add unit tests for login
refactor: improve store structure
```

### Pre-Commit Checks

Automated checks run before each commit:
- ✅ Linting (ESLint)
- ✅ Formatting (Prettier)
- ✅ Type checking (TypeScript)
- ✅ Commit message format

## 🐳 Docker Support

### Local Development
```bash
make docker-build     # Build image
make docker-run       # Run container
```

### Production Deployment
```bash
docker-compose up     # Run with compose
```

The Dockerfile uses multi-stage builds for optimal size.

## 🚢 Deployment

### Using Makefile
```bash
make deploy-staging       # Deploy to staging
make deploy-production    # Deploy to production
make smoke-test          # Post-deployment tests
make rollback            # Rollback if needed
```

### CI/CD Platforms

Choose your platform:
- **GitHub Actions**: `.github/workflows/ci.yml`
- **GitLab CI**: `.gitlab-ci.yml`
- **Jenkins**: `Jenkinsfile`

All use Makefile for consistency.

## 🎓 Learning Resources

### Within This Project
- Study the counter feature implementation
- Read all documentation in `docs/`
- Review test examples
- Examine configuration files

### External Resources
- [Vue 3 Documentation](https://vuejs.org)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/)
- [Vitest Documentation](https://vitest.dev)
- [Playwright Docs](https://playwright.dev)
- [SOLID Principles](https://en.wikipedia.org/wiki/SOLID)

## 🆘 Getting Help

### Documentation
1. Check `docs/` folder for detailed guides
2. Read inline code comments and JSDoc
3. Review example counter feature

### Cursor AI
Ask the AI assistant for help:
- "Explain how this feature works"
- "Review my code for issues"
- "How do I implement X following our standards?"

### Common Issues

**Tests failing**: Check coverage meets 90% threshold
**Lint errors**: Run `make lint-fix`
**Type errors**: Ensure strict TypeScript compliance
**Git hooks failing**: Ensure code quality checks pass

## 🎯 Next Steps

1. ✅ **Explore** the counter feature to understand patterns
2. ✅ **Read** the documentation (start with CODING_STANDARDS.md)
3. ✅ **Create** your first feature following the architecture
4. ✅ **Write** tests first (TDD approach)
5. ✅ **Ask** Cursor AI for guidance
6. ✅ **Run** `make validate` before committing
7. ✅ **Review** your code against SOLID principles

## 📊 Project Status

✅ All configuration complete
✅ Example feature implemented
✅ Tests passing (100% coverage in example)
✅ Documentation comprehensive
✅ CI/CD pipelines configured
✅ Docker deployment ready
✅ Cursor AI rules configured

You're ready to start developing! 🎉

---

**Questions?** Check the documentation or ask Cursor AI for help following our coding standards.

