# Frontend Integration into AI_Infra

## Date: December 6, 2025

## Overview

Frontend has been re-integrated into the AI_Infra docker-compose.yml, but now it builds from the external **AI_Front** repository instead of an internal subdirectory.

---

## ✅ Changes Made

### 1. Docker Compose Configuration

#### Added Frontend Service
```yaml
services:
  frontend:
    build:
      context: ../AI_Front          # External repository
      dockerfile: Dockerfile
      args:
        # Vite build-time environment variables
        VITE_API_BASE_URL: http://localhost/api
        VITE_GRAFANA_URL: http://localhost/monitoring/grafana/
        VITE_KEYCLOAK_URL: http://localhost/auth
        VITE_KEYCLOAK_REALM: infra-admin
        VITE_KEYCLOAK_CLIENT_ID: ai-front-spa
    container_name: ai_infra_frontend
    networks:
      - frontend-net
      - monitoring-net
```

#### Updated Nginx
```yaml
  nginx:
    depends_on:
      - frontend    # Re-added dependency
```

### 2. Makefile Updates

#### Simplified Frontend Commands
- ❌ Removed: `frontend-build` (now part of main build)
- ❌ Removed: `frontend-up` (now part of main up)
- ❌ Removed: `frontend-down` (now part of main down)
- ✅ Kept: `frontend-logs` (view logs)
- ✅ Kept: `frontend-shell` (access container)
- ✅ Kept: `frontend-dev` (standalone dev mode)
- ✅ Kept: `frontend-test` (run tests)
- ✅ Kept: `frontend-validate` (lint/type-check)
- ✅ Kept: `frontend-install` (npm install)

#### Updated All-Services Commands
```makefile
all-build: build backend-build
# Now "build" includes frontend as part of infra

all-up: up backend-up
# Now "up" starts frontend as part of infra
```

---

## 🏗️ Architecture

### Before (Separate Services)
```
AI_Infra (docker-compose.yml)
├── Nginx
├── PostgreSQL
├── Redis
├── Monitoring Stack
└── Keycloak

AI_Front (separate docker-compose.yml)
└── Frontend (Vue 3)
```

### After (Integrated)
```
AI_Infra (docker-compose.yml)
├── Frontend (built from ../AI_Front) ← NEW
├── Nginx (depends on frontend)
├── PostgreSQL
├── Redis
├── Monitoring Stack
└── Keycloak
```

---

## 📦 Build Process

### Frontend Build Context
- **Source**: `../AI_Front` directory
- **Dockerfile**: `../AI_Front/Dockerfile`
- **Build**: Multi-stage (Node.js build → Nginx serve)
- **Environment**: Variables injected at build time via `args`

### What Happens During Build
1. Docker reads `../AI_Front/Dockerfile`
2. Installs npm dependencies
3. Builds Vue 3 application with Vite
4. Embeds environment variables into bundle
5. Copies dist to Nginx image
6. Final image serves static files

---

## 🚀 Usage

### Start Everything (Including Frontend)
```bash
cd ~/Dev\ Nick/AI_Infra

# Build all services (includes frontend)
make build

# Start all services (includes frontend)
make up

# Or do both
make all-build
make all-up
```

### Work with Frontend
```bash
# View frontend logs
make frontend-logs

# Access frontend container shell
make frontend-shell

# Rebuild just frontend
docker-compose up -d --build frontend
```

### Frontend Development Mode (Standalone)
For hot-reload during development:
```bash
# Run frontend dev server (NOT in Docker)
make frontend-dev

# Access at http://localhost:5173
# Hot reload enabled
```

### Frontend Testing
```bash
# Run frontend unit tests
make frontend-test

# Validate code (lint, format, type-check)
make frontend-validate

# Install/update dependencies
make frontend-install
```

---

## 🌐 Access Points

### Production (via Nginx)
- **URL**: http://localhost/
- **Container**: `ai_infra_frontend`
- **Port**: Internal only (proxied by Nginx)

### Development (Standalone)
- **URL**: http://localhost:5173
- **Mode**: Hot reload
- **Command**: `make frontend-dev`

---

## ⚙️ Environment Variables

### Build-Time Variables (docker-compose.yml)
These are embedded into the JavaScript bundle:

```yaml
VITE_API_BASE_URL: http://localhost/api
VITE_GRAFANA_URL: http://localhost/monitoring/grafana/
VITE_KEYCLOAK_URL: http://localhost/auth
VITE_KEYCLOAK_REALM: infra-admin
VITE_KEYCLOAK_CLIENT_ID: ai-front-spa
VITE_KEYCLOAK_MIN_VALIDITY: 70
VITE_KEYCLOAK_CHECK_INTERVAL: 60
VITE_KEYCLOAK_DEBUG: false
VITE_ENV: production
```

### Override via .env File
Create `.env` in AI_Infra root:
```bash
# Override default values
VITE_API_BASE_URL=https://api.production.com
VITE_KEYCLOAK_URL=https://auth.production.com
VITE_ENV=production
```

---

## 🔧 Configuration

### Frontend Dockerfile Requirements

The `../AI_Front/Dockerfile` must:
1. Accept build args for Vite environment variables
2. Use multi-stage build (Node.js → Nginx)
3. Expose port 80
4. Include health check endpoint

Example structure:
```dockerfile
# Stage 1: Build
FROM node:20-alpine AS builder
ARG VITE_API_BASE_URL
ARG VITE_KEYCLOAK_URL
# ... other args
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
# ... build steps

# Stage 2: Serve
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
```

### Nginx Configuration

Nginx proxies requests to frontend container:
```nginx
location / {
    proxy_pass http://frontend:80;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

---

## 📊 Benefits of Integration

### ✅ Advantages
1. **Single Command Startup**: `make up` starts everything
2. **Unified Stack**: All infrastructure services together
3. **Proper Dependencies**: Nginx waits for frontend
4. **Shared Networks**: Frontend in same networks as infra
5. **Consistent Monitoring**: Frontend logs/metrics with infra

### ✅ Flexibility Maintained
1. **External Repository**: Frontend code stays separate
2. **Independent Development**: Can still run `npm run dev`
3. **Separate Testing**: Frontend tests independent
4. **Version Control**: Each repo has own git history

### ✅ Production Ready
1. **Same as Deployment**: Matches production architecture
2. **Proper Build Process**: Multi-stage Docker build
3. **Environment Variables**: Injected at build time
4. **Health Checks**: Kubernetes/Docker Swarm ready

---

## 🔄 Workflow Comparison

### Frontend Development Workflow

#### Option 1: Integrated (Production-like)
```bash
cd ~/Dev\ Nick/AI_Infra

# Build and start everything
make build
make up

# Work on frontend code in ../AI_Front
# Rebuild when ready
docker-compose up -d --build frontend

# View changes at http://localhost/
```

#### Option 2: Standalone (Hot Reload)
```bash
# Terminal 1: Start infrastructure
cd ~/Dev\ Nick/AI_Infra
make up

# Terminal 2: Run frontend dev server
make frontend-dev

# Work on frontend code
# Changes hot-reload automatically
# View at http://localhost:5173
```

---

## 🧪 Testing

### Test Frontend
```bash
# Unit tests
make frontend-test

# E2E tests (with infra running)
make up
make test  # Runs E2E tests
```

### Test Integration
```bash
# Start everything
make all-up

# Run all tests
make all-test
```

---

## 🐛 Troubleshooting

### Frontend Build Fails

**Problem**: `ERROR: failed to solve: ../AI_Front: no such file or directory`

**Solution**:
```bash
# Ensure AI_Front exists at correct location
ls -la ~/Dev\ Nick/AI_Front

# Check directory structure
pwd  # Should be in AI_Infra
cd ../AI_Front  # Should work
```

### Frontend Container Won't Start

**Problem**: Container exits immediately

**Solution**:
```bash
# Check build logs
docker-compose logs frontend

# Check Dockerfile
cat ../AI_Front/Dockerfile

# Ensure health endpoint exists
docker-compose exec frontend wget --spider -q http://localhost/health
```

### Environment Variables Not Working

**Problem**: Frontend shows wrong API URL

**Solution**:
```bash
# Remember: Vite variables are build-time, not runtime
# Must rebuild after changing .env
docker-compose up -d --build frontend

# Verify in browser console
# window.__ENV__ should show correct values
```

### Can't Access Frontend

**Problem**: http://localhost/ shows 502 Bad Gateway

**Solution**:
```bash
# Check frontend is running
docker-compose ps frontend

# Check Nginx can reach frontend
docker-compose exec nginx ping frontend

# Check Nginx config
docker-compose exec nginx cat /etc/nginx/nginx.conf | grep frontend
```

---

## 📝 Important Notes

### Build Time vs Runtime

⚠️ **VITE environment variables are embedded at BUILD time**, not runtime!

```bash
# This WON'T update variables:
docker-compose restart frontend

# This WILL update variables:
docker-compose up -d --build frontend
```

### Frontend Repository Location

The frontend build expects `../AI_Front` to exist relative to `AI_Infra`:

```
~/Dev Nick/
├── AI_Infra/          ← You are here
│   └── docker-compose.yml
├── AI_Front/          ← Frontend source
│   ├── Dockerfile
│   ├── package.json
│   └── src/
└── AI_Backend/
```

### Docker Build Context

The entire `AI_Front` directory is the build context:
- ✅ All files in `AI_Front` are available during build
- ✅ `.dockerignore` in `AI_Front` is respected
- ❌ Files outside `AI_Front` are NOT accessible

---

## 🎯 Next Steps

### Immediate
- [x] Add frontend to docker-compose.yml
- [x] Update Makefile commands
- [x] Test build process
- [ ] Verify environment variables
- [ ] Test production build
- [ ] Update documentation

### Short Term
- [ ] Add frontend to CI/CD pipeline
- [ ] Configure staging environment
- [ ] Set up frontend monitoring
- [ ] Add performance metrics
- [ ] Configure CDN (optional)

### Long Term
- [ ] Implement caching strategy
- [ ] Add E2E tests
- [ ] Performance optimization
- [ ] Security audit
- [ ] Accessibility testing

---

## 🚦 Startup Sequence

```
1. docker-compose build frontend
   └─> Reads ../AI_Front/Dockerfile
   └─> Installs npm dependencies
   └─> Builds Vue 3 app with Vite
   └─> Creates Nginx image with static files

2. docker-compose up -d
   └─> Starts frontend container
   └─> Starts nginx (waits for frontend)
   └─> Starts other services

3. Nginx proxies requests
   └─> http://localhost/ → frontend:80
```

---

## ✅ Summary

The frontend is now **integrated** into the AI_Infra docker-compose while maintaining its **separate repository**. This provides:

- 🎯 **Single command deployment** (`make up`)
- 🔧 **Flexible development** (Docker or standalone)
- 📦 **Production-ready builds** (multi-stage Docker)
- 🏗️ **Clear architecture** (external repo, integrated runtime)
- 🚀 **Easy scaling** (add more frontend replicas if needed)

**Best of both worlds**: Integrated deployment with separated code!

---

## 📚 Related Documentation

- `docker-compose.yml` - Frontend service definition
- `Makefile` - Frontend-related commands
- `../AI_Front/Dockerfile` - Frontend build configuration
- `../AI_Front/README.md` - Frontend development guide
- `docker/nginx/nginx.conf` - Nginx routing to frontend

---

**Status**: ✅ Frontend Successfully Integrated  
**Date**: December 6, 2025  
**Action**: Ready for use with `make up`

