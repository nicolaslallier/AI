# Docker Documentation

## Overview

The application is containerized using Docker with multi-stage builds for optimal production deployment.

## Docker Files

- `Dockerfile` - Multi-stage build configuration
- `docker-compose.yml` - Local development and production
- `.dockerignore` - Files excluded from Docker context
- `nginx.conf` - Production web server configuration

## Multi-Stage Build

### Stage 1: Build
```dockerfile
FROM node:20-alpine AS builder
# Install dependencies
# Build application
```

### Stage 2: Production
```dockerfile
FROM nginx:1.25-alpine
# Copy nginx config
# Copy built assets
# Expose port 80
```

**Benefits:**
- Smaller final image
- No dev dependencies in production
- Faster deployment
- Better security

## Local Development

### Build and Run

```bash
# Build Docker image
make docker-build

# Run container
make docker-run

# Access at http://localhost:8080
```

### Docker Compose

```bash
# Production mode
docker-compose up

# Development mode (with hot reload)
docker-compose --profile dev up
```

## Production Deployment

### Build for Production

```bash
# Build optimized image
docker build -t ai-front:latest .

# Tag for registry
docker tag ai-front:latest registry.example.com/ai-front:latest

# Push to registry
docker push registry.example.com/ai-front:latest
```

### Run in Production

```bash
# Run with environment variables
docker run -d \
  -p 80:80 \
  --name ai-front \
  --restart unless-stopped \
  ai-front:latest
```

## Nginx Configuration

The `nginx.conf` file is optimized for Vue SPA:

- **SPA Routing**: All routes serve index.html
- **Gzip Compression**: Enabled for faster loading
- **Cache Control**: Aggressive caching for assets
- **Security Headers**: X-Frame-Options, CSP, etc.
- **Health Check**: `/health` endpoint

## Health Checks

Docker includes health checks:

```yaml
healthcheck:
  test: ["CMD", "wget", "--spider", "http://localhost:80/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

## Environment Variables

No environment variables required at runtime (values are built into the bundle).

## Volume Mounts (Development)

For development with hot reload:

```yaml
volumes:
  - .:/app
  - /app/node_modules
```

## Image Size Optimization

- Multi-stage builds
- Alpine-based images
- Minimal nginx configuration
- No dev dependencies in production
- Gzip compression enabled

## Troubleshooting

### Container won't start
```bash
# Check logs
docker logs ai-front

# Inspect container
docker inspect ai-front
```

### Port conflicts
```bash
# Use different port
docker run -p 8081:80 ai-front:latest
```

### Permission issues
```bash
# Ensure nginx can read files
RUN chmod -R 755 /usr/share/nginx/html
```

## Best Practices

1. Use specific image tags, not `latest`
2. Implement health checks
3. Use non-root user when possible
4. Minimize image layers
5. Use `.dockerignore` effectively
6. Scan images for vulnerabilities
7. Keep images updated

## Security

- Regular security scans
- Minimal base images
- No secrets in images
- Security headers in nginx
- Regular updates

## Monitoring

- Container logs: `docker logs -f ai-front`
- Resource usage: `docker stats ai-front`
- Health status: `docker inspect --format='{{.State.Health.Status}}' ai-front`

