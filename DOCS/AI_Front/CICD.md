# CI/CD Documentation

## Overview

The project uses Makefile-based CI/CD for platform-agnostic automation.

## Supported Platforms

- GitHub Actions (`.github/workflows/ci.yml`)
- GitLab CI (`.gitlab-ci.yml`)
- Jenkins (`Jenkinsfile`)

## Pipeline Stages

### 1. Install
```bash
make install
```
- Install dependencies with exact versions
- Set up git hooks
- Install Playwright browsers

### 2. Validate
```bash
make validate
```
- ESLint checks
- Prettier formatting check
- TypeScript type checking

### 3. Test
```bash
make test
make test-e2e
```
- Run unit/component tests
- Generate coverage report (90%+ required)
- Run E2E tests
- Upload test artifacts

### 4. Build
```bash
make build
```
- Production build with Vite
- Generate optimized bundles
- Create dist artifacts

### 5. Docker
```bash
make docker-build
```
- Build Docker image
- Multi-stage build (build + nginx)
- Run smoke tests

### 6. Deploy
```bash
make deploy-staging    # Staging
make deploy-production # Production
```
- Deploy to target environment
- Run smoke tests
- Rollback on failure

## Environment-Specific Pipelines

### Pull Request
```
install → validate → test → build
```

### Develop Branch
```
install → validate → test → build → docker → deploy-staging
```

### Main Branch
```
install → validate → test → build → docker → deploy-production
```

## Makefile Commands

See [README.md](../README.md#available-commands) for full command list.

## Adding New CI Platform

1. Create platform-specific config file
2. Define stages/jobs
3. Call Makefile targets for each stage
4. Configure environment variables
5. Set up deployment credentials

## Monitoring

- **GitHub Actions**: Check workflow runs in Actions tab
- **GitLab CI**: Check pipeline status in CI/CD → Pipelines
- **Jenkins**: Check build history in Jenkins dashboard

## Rollback

```bash
make rollback
```

Reverts to previous deployment (platform-specific implementation required).

