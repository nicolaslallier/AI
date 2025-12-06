# Makefile Guide - CI/CD Management

This guide explains how to use the Makefile for managing your AI Infrastructure development and CI/CD operations.

## Quick Start

```bash
# View all available commands
make help

# Initial setup (first time only)
make setup

# Start development environment
make up

# View logs
make logs

# Run tests
make test

# Stop everything
make down
```

## Command Categories

### 🚀 Setup & Installation

```bash
make setup              # First-time setup - creates .env, makes scripts executable
make check              # Check prerequisites (Docker, Compose, env file)
make install-hooks      # Install git pre-commit hooks
```

### 🔧 Development

```bash
make up                 # Start all services in development mode
make up-build           # Start services and rebuild images
make up-prod            # Start in production mode
make down               # Stop all services
make restart            # Restart all services
make ps                 # Show status of all services
```

### 📊 Logs & Monitoring

```bash
make logs               # Follow logs from all services
make logs-service SERVICE=postgres    # Follow specific service logs
make watch FILTER=error              # Watch logs with grep filter
make stats              # Show resource usage statistics
make health             # Check health of all services
```

### 🏗️ Building & Images

```bash
make build              # Build all service images
make build-nocache      # Build without cache
make build-python       # Build only Python service
make build-nodejs       # Build only Node.js service
make pull               # Pull all service images
```

### 🧪 Testing

```bash
make test               # Run all tests
make test-python        # Run Python tests only
make test-nodejs        # Run Node.js tests only
make test-coverage      # Run tests with coverage report
make ci-test            # Run complete CI test pipeline
```

### 📝 Code Quality

```bash
make lint               # Lint all services
make lint-python        # Lint Python code
make lint-nodejs        # Lint Node.js code
make format             # Format code for all services
make format-python      # Format Python code with Black
make format-nodejs      # Format Node.js code with Prettier
```

### 🗄️ Database Operations

```bash
make db-migrate         # Run database migrations
make db-seed            # Seed database with sample data
make db-backup          # Backup PostgreSQL database
make db-restore BACKUP=backups/file.sql.gz    # Restore from backup
make db-shell           # Open PostgreSQL shell
```

### 🔌 Service Management

```bash
make shell-python       # Open bash shell in Python service
make shell-nodejs       # Open shell in Node.js service
make shell-redis        # Open Redis CLI
make restart-python     # Restart Python service
make restart-nodejs     # Restart Node.js service
```

### 📈 Monitoring & Dashboards

```bash
make metrics            # Open Prometheus (http://localhost:9090)
make dashboard          # Open Grafana (http://localhost:3000)
make rabbitmq-ui        # Open RabbitMQ Management UI
make api-docs           # Open API documentation
make urls               # Display all service URLs
```

### 🚢 CI/CD Operations

```bash
make ci-test            # Run CI test pipeline
make ci-build           # Build for CI/CD
make ci-deploy-staging  # Deploy to staging
make ci-deploy-prod     # Deploy to production (with confirmation)
```

### 🧹 Cleanup

```bash
make clean              # Stop and remove containers
make clean-volumes      # Stop and remove volumes (⚠️ DELETES DATA)
make clean-images       # Remove all project images
make clean-all          # Complete cleanup (everything)
make prune              # Clean up Docker system (dangling resources)
```

### 🔒 Security

```bash
make security-scan      # Scan images for vulnerabilities
make audit              # Audit dependencies for security issues
```

### ⚡ Performance

```bash
make benchmark          # Run performance benchmarks
make profile            # Profile application performance
make disk-usage         # Show Docker disk usage
```

### 🛠️ Utilities

```bash
make version            # Show versions of all components
make env                # Show environment variables
make inspect SERVICE=postgres    # Inspect service environment
make update-deps        # Update all dependencies
```

## Common Workflows

### Initial Setup

```bash
# 1. Clone repository
git clone <repo-url>
cd AI_Infra

# 2. Initial setup
make setup

# 3. Review and customize .env
nano .env

# 4. Start services
make up

# 5. Check everything is running
make ps
make health
```

### Daily Development

```bash
# Start your day
make up

# View logs while developing
make logs

# Restart a service after changes
make restart-python

# Format and lint before committing
make format
make lint

# Run tests
make test

# Stop when done
make down
```

### Testing Workflow

```bash
# Start services
make up

# Run specific tests
make test-python
make test-nodejs

# Check test coverage
make test-coverage

# Run complete CI pipeline locally
make ci-test
```

### Database Workflow

```bash
# Create a backup before migrations
make db-backup

# Run migrations
make db-migrate

# Seed test data
make db-seed

# Access database shell if needed
make db-shell

# Restore if something goes wrong
make db-restore BACKUP=backups/postgres_backup_20240101_120000.sql.gz
```

### Debugging Workflow

```bash
# Check service status
make ps
make health

# View logs for specific service
make logs-service SERVICE=postgres

# Watch for errors
make watch FILTER=error

# Check resource usage
make stats

# Access service shell
make shell-python

# Inspect environment
make inspect SERVICE=python-service
```

### CI/CD Workflow

```bash
# Run full CI pipeline locally
make ci-test

# Build for deployment
make ci-build

# Deploy to staging
make ci-deploy-staging

# If staging looks good, deploy to production
make ci-deploy-prod
```

### Cleanup Workflow

```bash
# Regular cleanup (keeps data)
make clean

# Clean everything for fresh start
make clean-all

# Clean up Docker system
make prune
```

## Advanced Usage

### Conditional Service Start

```bash
# Start only database services
docker-compose up -d postgres redis rabbitmq

# Use Makefile for other operations
make logs-service SERVICE=postgres
```

### Environment-Specific Commands

```bash
# Development
make up

# Production
make up-prod

# Staging (modify .env first)
ENV_FILE=.env.staging make up-prod
```

### Parallel Execution

```bash
# Build services in parallel (automatic with Docker Compose)
make build

# Run tests in parallel (if configured)
make test
```

### Custom Filters

```bash
# Watch logs for specific patterns
make watch FILTER=ERROR
make watch FILTER="user_id=123"
make watch FILTER="python-service"
```

## Integration with CI/CD

### GitHub Actions

A complete GitHub Actions workflow is provided in `.github/workflows/ci.yml`:

```yaml
# Automatically runs on:
# - Push to main or develop
# - Pull requests to main or develop

# Pipeline stages:
1. Lint code
2. Build Docker images
3. Run tests
4. Security scanning
5. Deploy to staging (develop branch)
6. Deploy to production (main branch)
```

### GitLab CI

Create `.gitlab-ci.yml`:

```yaml
stages:
  - lint
  - build
  - test
  - deploy

lint:
  stage: lint
  script: make lint

build:
  stage: build
  script: make build

test:
  stage: test
  script: make ci-test

deploy-staging:
  stage: deploy
  script: make ci-deploy-staging
  only: [develop]

deploy-production:
  stage: deploy
  script: make ci-deploy-prod
  only: [main]
```

### Jenkins

Create `Jenkinsfile`:

```groovy
pipeline {
    agent any
    
    stages {
        stage('Setup') {
            steps {
                sh 'make setup'
            }
        }
        stage('Lint') {
            steps {
                sh 'make lint'
            }
        }
        stage('Build') {
            steps {
                sh 'make build'
            }
        }
        stage('Test') {
            steps {
                sh 'make ci-test'
            }
        }
        stage('Deploy') {
            when { branch 'main' }
            steps {
                sh 'make ci-deploy-prod'
            }
        }
    }
}
```

## Tips & Best Practices

### 1. Pre-commit Hooks

Install git hooks to run checks before committing:

```bash
make install-hooks
```

This will automatically run linting and tests before each commit.

### 2. Regular Maintenance

```bash
# Weekly
make update-deps      # Update dependencies
make security-scan    # Check for vulnerabilities
make db-backup        # Backup database

# Monthly
make prune            # Clean up Docker system
```

### 3. Monitoring

```bash
# Keep these open during development
make logs             # Terminal 1: All logs
make stats            # Terminal 2: Resource usage
make dashboard        # Browser: Grafana dashboard
```

### 4. Troubleshooting

```bash
# Service won't start
make logs-service SERVICE=problematic-service
make inspect SERVICE=problematic-service
make health

# Database issues
make db-shell
# Check tables, connections, etc.

# Redis issues
make shell-redis
# Run Redis commands

# Complete reset
make clean-all
make setup
make up
```

## Environment Variables

The Makefile respects these environment variables:

```bash
# Override Docker Compose files
COMPOSE_FILE=docker-compose.yml
COMPOSE_DEV_FILE=docker-compose.dev.yml

# Override .env location
ENV_FILE=.env.production

# Docker Buildkit
DOCKER_BUILDKIT=1
```

## Customization

### Adding New Commands

Edit the Makefile and add your command:

```makefile
.PHONY: my-command
my-command: ## Description of my command
	@echo "$(BLUE)Running my command...$(NC)"
	# Your commands here
	@echo "$(GREEN)✓ Done$(NC)"
```

### Service-Specific Commands

```makefile
.PHONY: deploy-service
deploy-service: ## Deploy specific service
	@docker-compose up -d --build $(SERVICE)
	@echo "$(GREEN)✓ $(SERVICE) deployed$(NC)"

# Usage: make deploy-service SERVICE=python-service
```

## Troubleshooting

### "make: command not found"

Install make:
```bash
# macOS
brew install make

# Ubuntu/Debian
sudo apt-get install build-essential

# Windows
# Install via WSL or use Windows Make
```

### Permission Denied

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Or run setup again
make setup
```

### Docker Not Running

```bash
# Check Docker status
make check

# Start Docker Desktop (macOS/Windows)
# Or start Docker daemon (Linux)
sudo systemctl start docker
```

## Additional Resources

- [Makefile Documentation](https://www.gnu.org/software/make/manual/)
- [Docker Compose CLI](https://docs.docker.com/compose/reference/)
- [GitHub Actions](https://docs.github.com/en/actions)
- [Project README](README.md)
- [Architecture Documentation](ARCHITECTURE.md)

---

**Pro Tip**: Run `make help` anytime to see all available commands with descriptions!

