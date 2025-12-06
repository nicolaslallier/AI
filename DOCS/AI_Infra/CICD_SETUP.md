# CI/CD Setup Guide

This guide covers the complete CI/CD setup for the AI Infrastructure project using the Makefile and various CI/CD platforms.

## 🎯 Overview

The project includes comprehensive CI/CD automation through:

1. **Makefile** - Local development and CI/CD commands
2. **GitHub Actions** - Automated pipeline for GitHub
3. **GitLab CI** - Automated pipeline for GitLab
4. **Jenkins** - Automated pipeline for Jenkins

## 📋 Table of Contents

- [Makefile Commands](#makefile-commands)
- [Local CI/CD Workflow](#local-cicd-workflow)
- [GitHub Actions Setup](#github-actions-setup)
- [GitLab CI Setup](#gitlab-ci-setup)
- [Jenkins Setup](#jenkins-setup)
- [Deployment Strategies](#deployment-strategies)
- [Best Practices](#best-practices)

---

## Makefile Commands

### Quick Reference

```bash
# Setup & Installation
make setup              # Initial setup
make check              # Verify prerequisites
make install-hooks      # Install git hooks

# Development
make up                 # Start development environment
make down               # Stop services
make logs               # View logs
make restart            # Restart all services

# Building
make build              # Build all images
make build-nocache      # Build without cache
make build-python       # Build Python service
make build-nodejs       # Build Node.js service

# Testing
make test               # Run all tests
make test-python        # Run Python tests
make test-nodejs        # Run Node.js tests
make test-coverage      # Generate coverage report

# Code Quality
make lint               # Lint all code
make format             # Format all code
make security-scan      # Scan for vulnerabilities
make audit              # Audit dependencies

# Database
make db-migrate         # Run migrations
make db-seed            # Load sample data
make db-backup          # Backup database
make db-shell           # Open database shell

# CI/CD
make ci-test            # Run CI pipeline locally
make ci-build           # Build for CI/CD
make ci-deploy-staging  # Deploy to staging
make ci-deploy-prod     # Deploy to production

# Cleanup
make clean              # Clean containers
make clean-volumes      # Clean volumes (deletes data)
make clean-all          # Complete cleanup
make prune              # Clean Docker system
```

### Complete Command List

Run `make help` to see all available commands with descriptions.

---

## Local CI/CD Workflow

### 1. Initial Setup

```bash
# Clone and setup
git clone <repo-url>
cd AI_Infra
make setup

# Review environment
cat .env
```

### 2. Development Cycle

```bash
# Start services
make up

# Make changes to code
# ...

# Test changes
make test

# Lint and format
make lint
make format

# Commit (pre-commit hooks will run automatically)
git add .
git commit -m "feat: add new feature"
```

### 3. Pre-Push Validation

```bash
# Run complete CI pipeline locally
make ci-test

# This runs:
# 1. Prerequisites check
# 2. Build images
# 3. Start services
# 4. Run tests
# 5. Lint code
```

### 4. Deployment

```bash
# Deploy to staging
make ci-deploy-staging

# If staging is good, deploy to production
make ci-deploy-prod
```

---

## GitHub Actions Setup

### Configuration File

Located at: `.github/workflows/ci.yml`

### Pipeline Stages

1. **Lint** - Code quality checks
2. **Build** - Build Docker images
3. **Test** - Run test suites
4. **Security** - Vulnerability scanning
5. **Deploy Staging** - Auto-deploy develop branch
6. **Deploy Production** - Manual deploy main branch

### Setup Steps

1. **Enable GitHub Actions**
   - Go to repository Settings → Actions
   - Enable workflows

2. **Add Secrets**
   - Go to Settings → Secrets and variables → Actions
   - Add required secrets:
     ```
     DOCKER_USERNAME
     DOCKER_PASSWORD
     SSH_PRIVATE_KEY
     STAGING_HOST
     STAGING_USER
     PRODUCTION_HOST
     PRODUCTION_USER
     ```

3. **Configure Environments**
   - Go to Settings → Environments
   - Create `staging` and `production` environments
   - Add environment-specific variables and protection rules

4. **Trigger Pipeline**
   ```bash
   git push origin develop  # Triggers CI + staging deploy
   git push origin main     # Triggers CI + production deploy
   ```

### Workflow Triggers

```yaml
on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]
```

### Customization

Edit `.github/workflows/ci.yml` to:
- Add/remove stages
- Modify deployment targets
- Change trigger conditions
- Add notifications

---

## GitLab CI Setup

### Configuration File

Located at: `.gitlab-ci.yml`

### Pipeline Stages

1. **Lint** - Python and Node.js linting
2. **Build** - Build and push images
3. **Test** - Run tests with coverage
4. **Security** - Vulnerability scanning and audits
5. **Deploy** - Manual deployment to staging/production

### Setup Steps

1. **Configure CI/CD Variables**
   - Go to Settings → CI/CD → Variables
   - Add required variables:
     ```
     CI_REGISTRY_USER
     CI_REGISTRY_PASSWORD
     SSH_PRIVATE_KEY
     STAGING_HOST
     STAGING_USER
     PRODUCTION_HOST
     PRODUCTION_USER
     ```

2. **Configure Runners**
   - Install GitLab Runner (if self-hosted)
   - Register runner with Docker executor
   - Tag runners appropriately

3. **Enable Docker-in-Docker**
   - Ensure runner has Docker service enabled
   - Configure runner to use overlay2 driver

4. **Trigger Pipeline**
   ```bash
   git push origin develop  # Triggers full pipeline
   ```

### Manual Deployments

Deployments are manual by default. Click "Deploy" button in pipeline UI.

### Coverage Reports

Coverage reports are automatically generated and displayed in merge requests.

---

## Jenkins Setup

### Configuration File

Located at: `Jenkinsfile`

### Pipeline Stages

1. **Checkout** - Clone repository
2. **Setup** - Initialize environment
3. **Lint** - Parallel linting
4. **Build** - Build images
5. **Test** - Run tests with reporting
6. **Security** - Parallel security scans
7. **Push Images** - Push to registry
8. **Deploy** - Stage-specific deployment
9. **Health Check** - Verify deployment

### Setup Steps

1. **Install Jenkins Plugins**
   ```
   - Docker Pipeline
   - Docker Compose Build Step
   - Blue Ocean (optional)
   - Slack Notification (optional)
   ```

2. **Configure Jenkins Credentials**
   - Go to Manage Jenkins → Credentials
   - Add credentials:
     - Docker Registry (username/password)
     - SSH Private Key (for deployments)
     - Slack Token (if using notifications)

3. **Create Pipeline Job**
   - New Item → Pipeline
   - Point to your repository
   - Configure branch sources (main, develop)
   - Set Jenkinsfile path

4. **Configure Webhooks**
   - Add webhook in your Git provider
   - Point to Jenkins URL: `http://jenkins-url/github-webhook/`

5. **Run Pipeline**
   ```bash
   git push origin develop
   ```

### Environment Configuration

Set environment variables in Jenkins:
```groovy
environment {
    DOCKER_REGISTRY = credentials('docker-registry')
    STAGING_HOST = credentials('staging-host')
}
```

### Notifications

Configure Slack/email notifications in Jenkinsfile post section.

---

## Deployment Strategies

### 1. Direct Deployment (Current)

```bash
# Deploy directly to server
make ci-deploy-staging
make ci-deploy-prod
```

**Pros:**
- Simple and fast
- Good for small teams

**Cons:**
- Brief downtime during deployment
- No automatic rollback

### 2. Blue-Green Deployment

```bash
# Deploy to "green" environment
make ci-deploy-prod ENVIRONMENT=green

# Switch traffic to green
make switch-traffic TO=green

# Keep blue for rollback
make rollback TO=blue  # if needed
```

**Pros:**
- Zero downtime
- Quick rollback

**Cons:**
- Requires 2x resources
- More complex setup

### 3. Canary Deployment

```bash
# Deploy to small subset (10%)
make ci-deploy-prod CANARY=10

# Monitor metrics
make metrics

# Roll out to 50%
make ci-deploy-prod CANARY=50

# Roll out to 100%
make ci-deploy-prod CANARY=100
```

**Pros:**
- Gradual rollout
- Early issue detection

**Cons:**
- Complex routing
- Longer deployment time

### 4. Rolling Deployment

```bash
# Update instances one by one
make ci-deploy-prod STRATEGY=rolling
```

**Pros:**
- No additional resources
- Gradual rollout

**Cons:**
- Mixed versions running
- Slower deployment

---

## Best Practices

### 1. Branch Strategy

```
main       →  Production (stable releases)
develop    →  Staging (integration testing)
feature/*  →  Development (feature branches)
hotfix/*   →  Production (urgent fixes)
```

### 2. Versioning

Use semantic versioning:
```bash
git tag -a v1.0.0 -m "Release version 1.0.0"
git push origin v1.0.0
```

### 3. Pre-commit Hooks

Install git hooks:
```bash
make install-hooks
```

This automatically runs:
- Code formatting
- Linting
- Unit tests

### 4. Code Review

Always require code review before merging:
- Create pull/merge request
- Run CI pipeline
- Review code changes
- Approve and merge

### 5. Testing Strategy

```bash
# Unit tests (fast, isolated)
make test-python
make test-nodejs

# Integration tests (moderate, with dependencies)
make test

# E2E tests (slow, full system)
make test-e2e  # (implement as needed)
```

### 6. Security

```bash
# Regular security scans
make security-scan

# Dependency audits
make audit

# Keep dependencies updated
make update-deps
```

### 7. Monitoring

Monitor deployments:
```bash
# Check health after deployment
make health

# View metrics
make metrics

# Check logs
make logs
```

### 8. Database Migrations

Always backup before migrations:
```bash
make db-backup
make db-migrate
```

If migration fails:
```bash
make db-restore BACKUP=backups/latest.sql.gz
```

### 9. Rollback Strategy

Be prepared to rollback:
```bash
# Tag before deployment
git tag -a v1.2.3-pre-deploy -m "Pre-deployment checkpoint"

# If issues occur
git revert <commit>
make ci-deploy-prod
```

### 10. Documentation

Keep documentation updated:
- Update README.md for new features
- Document environment variables
- Update architecture diagrams
- Maintain runbooks

---

## Continuous Improvement

### Metrics to Track

1. **Build Time** - How long does CI pipeline take?
2. **Test Coverage** - Are tests comprehensive?
3. **Deployment Frequency** - How often are you deploying?
4. **Lead Time** - Time from commit to production
5. **MTTR** - Mean time to recovery from failures
6. **Change Failure Rate** - % of deployments causing issues

### Optimization Tips

```bash
# Speed up builds
make build --parallel
docker-compose build --parallel

# Use build cache
DOCKER_BUILDKIT=1 make build

# Parallel testing
pytest -n auto  # Python
npm test -- --parallel  # Node.js
```

---

## Troubleshooting

### CI Pipeline Fails

1. **Check logs**
   ```bash
   make logs-service SERVICE=failing-service
   ```

2. **Run locally**
   ```bash
   make ci-test
   ```

3. **Check environment**
   ```bash
   make check
   make env
   ```

### Deployment Fails

1. **Check service health**
   ```bash
   make health
   make ps
   ```

2. **Rollback**
   ```bash
   git revert <bad-commit>
   make ci-deploy-prod
   ```

3. **Check resources**
   ```bash
   make stats
   make disk-usage
   ```

### Test Failures

1. **Run specific test**
   ```bash
   docker-compose exec python-service pytest tests/test_specific.py -v
   ```

2. **Debug mode**
   ```bash
   docker-compose exec python-service pytest --pdb
   ```

3. **Check dependencies**
   ```bash
   make install-python-deps
   make install-nodejs-deps
   ```

---

## Additional Resources

- [Makefile Guide](MAKEFILE_GUIDE.md) - Complete Makefile documentation
- [Architecture](ARCHITECTURE.md) - System architecture details
- [Quick Start](QUICKSTART.md) - Getting started guide
- [README](README.md) - Project overview

---

## Support

For issues with CI/CD:
1. Check service logs: `make logs`
2. Verify health: `make health`
3. Run tests locally: `make test`
4. Review pipeline logs in CI platform
5. Check this documentation

**Happy Deploying! 🚀**

