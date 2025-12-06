# System Architecture Documentation

## Overview

This document describes the architecture of the AI Infrastructure project, a multi-service platform designed for scalable AI applications with comprehensive observability, caching, messaging, and search capabilities.

## Architecture Principles

### 1. Service-Oriented Architecture (SOA)

The system is built using a service-oriented approach with the following characteristics:

- **Loose Coupling**: Services communicate through well-defined interfaces (REST APIs, message queues)
- **High Cohesion**: Each service has a single, well-defined responsibility
- **Autonomy**: Services can be developed, deployed, and scaled independently
- **Statelessness**: Application services are designed to be stateless for horizontal scaling

### 2. Separation of Concerns

Services are organized into distinct tiers:

- **Presentation Tier**: Client-facing APIs (Python FastAPI, Node.js Express)
- **Business Logic Tier**: Application services with domain logic
- **Data Tier**: Persistent storage (PostgreSQL), caching (Redis), search (Elasticsearch)
- **Integration Tier**: Message queuing (RabbitMQ) for async communication
- **Observability Tier**: Monitoring (Prometheus) and visualization (Grafana)

### 3. Security by Design

- **Network Segmentation**: Isolated Docker networks per tier
- **Least Privilege**: Services only access resources they need
- **Defense in Depth**: Multiple layers of security (network, application, data)
- **Secrets Management**: No hardcoded credentials, environment-based configuration

## System Components

### Data Tier

#### PostgreSQL Database
- **Purpose**: Primary relational data store
- **Version**: 16 (Alpine)
- **Key Features**:
  - ACID compliance for transactional integrity
  - Advanced indexing (B-tree, GiST, GIN)
  - Full-text search capabilities
  - JSON/JSONB support
  - Replication-ready configuration
  
- **Configuration Highlights**:
  - Connection pooling: 200 max connections
  - Shared buffers: 256MB
  - Effective cache size: 1GB
  - WAL configuration for durability
  - Query logging for slow queries (>1s)

- **Network Access**: `data-net`, `monitoring-net`
- **Persistent Storage**: Named volume `postgres_data`

#### Redis Cache
- **Purpose**: Distributed caching and session storage
- **Version**: 7 (Alpine)
- **Key Features**:
  - In-memory data store with sub-millisecond latency
  - Persistence (RDB + AOF)
  - Pub/Sub messaging
  - LRU eviction policy
  - Cluster-ready configuration

- **Configuration Highlights**:
  - Max memory: 512MB
  - Eviction policy: allkeys-lru
  - Persistence: AOF with everysec fsync
  - Security: Password authentication

- **Network Access**: `data-net`, `monitoring-net`
- **Persistent Storage**: Named volume `redis_data`

#### Elasticsearch
- **Purpose**: Full-text search and analytics engine
- **Version**: 8.11.3
- **Key Features**:
  - Distributed search and analytics
  - RESTful API
  - Real-time indexing
  - Aggregations and analytics
  - Security features (X-Pack)

- **Configuration Highlights**:
  - Single-node deployment (development)
  - JVM heap: 512MB
  - Security enabled with basic auth
  - Index management and lifecycle policies

- **Network Access**: `backend-net`, `monitoring-net`
- **Persistent Storage**: Named volume `elasticsearch_data`

### Integration Tier

#### RabbitMQ Message Queue
- **Purpose**: Asynchronous message broker
- **Version**: 3 (Management Alpine)
- **Key Features**:
  - AMQP 0-9-1 protocol
  - Multiple exchange types (direct, topic, fanout)
  - Message persistence
  - Dead letter exchanges
  - Management UI and API

- **Configuration Highlights**:
  - Multiple virtual hosts (/, /app, /tasks)
  - High availability policies
  - TTL and max-length queue limits
  - Priority queue support
  - Management plugin enabled

- **Network Access**: `backend-net`, `monitoring-net`
- **Persistent Storage**: Named volume `rabbitmq_data`
- **Management UI**: Port 15672

### Presentation Tier

#### Frontend Application (Vue 3 SPA)
- **Purpose**: User-facing web application
- **Technology Stack**:
  - Vue 3: Progressive JavaScript framework with Composition API
  - TypeScript: Type safety and better developer experience
  - Vite: Fast build tool and dev server
  - Tailwind CSS: Utility-first CSS framework
  - Pinia: State management
  - Vue Router: Client-side routing

- **Key Features**:
  - Single Page Application (SPA) architecture
  - Component-based architecture with feature modules
  - Type-safe development with TypeScript
  - Responsive design with Tailwind CSS
  - Client-side routing with SPA fallback
  - Production-optimized build with code splitting
  - 90%+ test coverage with Vitest and Playwright

- **Multi-Stage Docker Build**:
  - Build stage: Node.js 20 for compiling Vue app
  - Production stage: Nginx Alpine for serving static assets
  - Optimized bundle size with tree shaking
  - Asset caching with immutable cache headers

- **Deployment**:
  - Served via internal nginx at port 80
  - Proxied through main nginx reverse proxy at root path (/)
  - Health check endpoint at /health

- **Network Access**: `frontend-net`, `monitoring-net`

#### Reverse Proxy (Nginx)
- **Purpose**: Central entry point for all web traffic
- **Routing Configuration**:
  - `/` - Frontend Vue.js application
  - `/monitoring/grafana/` - Grafana dashboards
  - `/monitoring/prometheus/` - Prometheus metrics UI
  - `/monitoring/tempo/` - Tempo tracing UI
  - `/monitoring/loki/` - Loki log aggregation UI
  - `/health` - Health check endpoint

- **Features**:
  - SPA routing support with fallback to index.html
  - Static asset caching with 1-year expiration
  - Gzip compression for text resources
  - WebSocket support for Grafana Live
  - Request/response logging

- **Network Access**: `frontend-net`, `monitoring-net`

### Application Tier

#### Python Service (FastAPI)
- **Purpose**: High-performance Python microservice
- **Technology Stack**:
  - FastAPI: Modern, async web framework
  - Uvicorn: ASGI server
  - SQLAlchemy: ORM for database access
  - Pydantic: Data validation
  - Asyncpg: Async PostgreSQL driver

- **Key Features**:
  - Async/await for I/O operations
  - Automatic OpenAPI documentation
  - Type hints and validation
  - Dependency injection
  - Structured logging

- **Multi-Stage Docker Build**:
  - Base stage: Common dependencies
  - Dependencies stage: Poetry packages
  - Development stage: Hot-reload enabled
  - Production stage: Optimized runtime

- **Network Access**: `frontend-net`, `backend-net`, `data-net`

#### Node.js Service (TypeScript)
- **Purpose**: TypeScript-based microservice
- **Technology Stack**:
  - Express: Web framework
  - TypeScript: Type safety
  - Prisma/pg: Database clients
  - Winston: Logging
  - Joi: Validation

- **Key Features**:
  - Strong typing with TypeScript
  - Async/await for all I/O
  - Middleware-based architecture
  - Dependency injection support
  - Structured logging

- **Multi-Stage Docker Build**:
  - Base stage: Node.js setup
  - Dependencies stage: npm install
  - Development stage: Hot-reload with nodemon
  - Build stage: TypeScript compilation
  - Production stage: Optimized runtime

- **Network Access**: `frontend-net`, `backend-net`, `data-net`

### Observability Tier

#### Prometheus
- **Purpose**: Metrics collection and alerting
- **Version**: Latest
- **Key Features**:
  - Time-series database
  - PromQL query language
  - Pull-based metrics collection
  - Alert rule evaluation
  - Service discovery

- **Scrape Targets**:
  - Node Exporter (system metrics)
  - PostgreSQL Exporter
  - Redis Exporter
  - RabbitMQ metrics endpoint
  - Elasticsearch metrics
  - Application services (/metrics)

- **Alert Rules**:
  - Instance down
  - High CPU/memory usage
  - Database connection issues
  - Queue depth warnings

- **Network Access**: `monitoring-net`
- **Persistent Storage**: Named volume `prometheus_data`

#### Grafana
- **Purpose**: Metrics visualization and dashboards
- **Version**: Latest
- **Key Features**:
  - Rich dashboard creation
  - Multiple data source support
  - Alerting and notifications
  - User management
  - Dashboard provisioning

- **Pre-configured Dashboards**:
  - System Overview (CPU, memory, disk)
  - Service Health monitoring
  - Database performance
  - Cache hit rates
  - Queue metrics

- **Data Sources**:
  - Prometheus (default)
  - PostgreSQL (direct queries)
  - Elasticsearch (logs)

- **Network Access**: `monitoring-net`, `frontend-net`
- **Persistent Storage**: Named volume `grafana_data`

#### Exporters
- **Node Exporter**: Host system metrics
- **PostgreSQL Exporter**: Database metrics
- **Redis Exporter**: Cache metrics
- **RabbitMQ Built-in**: Queue metrics

## Network Architecture

### Network Segmentation

```
┌─────────────────────────────────────────────────────────┐
│                     Frontend Network                     │
│  - Vue 3 SPA (Frontend Container)                       │
│  - Nginx Reverse Proxy (Main Entry Point)              │
│  - Routes: /, /monitoring/*                             │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                     Backend Network                      │
│  - Python Service (FastAPI)                             │
│  - Node.js Service (TypeScript)                         │
│  - RabbitMQ (Message Queue)                            │
│  - Elasticsearch (Search Engine)                        │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                      Data Network                        │
│  - PostgreSQL (Primary Database)                        │
│  - Redis (Cache & Sessions)                             │
│  - Database Exporters                                   │
└─────────────────────────────────────────────────────────┘
                            │
┌─────────────────────────────────────────────────────────┐
│                   Monitoring Network                     │
│  - Prometheus (Metrics Collection)                      │
│  - Grafana (Visualization)                              │
│  - Tempo (Distributed Tracing)                          │
│  - Loki (Log Aggregation)                               │
│  - All Exporters                                        │
│  - All Services (metrics endpoints)                     │
└─────────────────────────────────────────────────────────┘
```

### Network Policies

- **frontend-net** (172.50.0.0/24): User-facing services (Vue.js app, Nginx reverse proxy)
- **backend-net** (172.21.0.0/24): Internal application services
- **data-net** (172.22.0.0/24): Data persistence layer
- **monitoring-net** (172.31.0.0/24): Observability stack

Services can belong to multiple networks based on communication needs.

## Data Flow Patterns

### Request Flow (Synchronous)

```
Client → Application Service → [Cache Check] Redis
                              ↓ Cache Miss
                              → PostgreSQL → Response
                              → [Cache Update] Redis
```

### Task Processing Flow (Asynchronous)

```
Client → Application Service → RabbitMQ → Worker Service
                                          ↓
                                     PostgreSQL
                                          ↓
                                  Notification Service
```

### Search Flow

```
Client → Application Service → Elasticsearch
                              ↓ Search Query
                              → Results + Aggregations
                              → Response
```

### Event-Driven Flow

```
Service A → Event → RabbitMQ (Topic Exchange)
                         ↓
                    ┌────┴────┬────────┐
                    ↓         ↓        ↓
               Service B  Service C  Service D
```

## Communication Patterns

### Synchronous Communication
- **REST APIs**: HTTP/HTTPS for client-service and service-service calls
- **Direct Database Access**: PostgreSQL for transactional data
- **Cache Queries**: Redis for high-speed data retrieval
- **Search Queries**: Elasticsearch for full-text search

### Asynchronous Communication
- **Message Queues**: RabbitMQ for background jobs
- **Event Publishing**: Topic exchanges for event broadcasting
- **Task Distribution**: Work queues for load distribution

## Scalability Strategies

### Horizontal Scaling

Application services are designed for horizontal scaling:
- **Stateless Design**: No local state, session data in Redis
- **Load Balancing**: Can add multiple instances behind load balancer
- **Database Pooling**: Connection pooling prevents connection exhaustion
- **Caching**: Redis reduces database load

### Vertical Scaling

Resource limits can be adjusted per service:
```yaml
deploy:
  resources:
    limits:
      cpus: '2'
      memory: 2G
```

### Database Scaling

PostgreSQL can be scaled using:
- **Read Replicas**: For read-heavy workloads
- **Connection Pooling**: PgBouncer for connection management
- **Partitioning**: Table partitioning for large datasets
- **Sharding**: Application-level sharding for massive scale

### Cache Scaling

Redis can be scaled using:
- **Redis Cluster**: Automatic sharding across nodes
- **Sentinel**: High availability and failover
- **Multi-tier Caching**: Application cache + Redis

### Message Queue Scaling

RabbitMQ can be scaled using:
- **Clustering**: Multi-node clusters for high availability
- **Sharding**: Queue sharding for distribution
- **Federation**: Cross-datacenter message routing

## High Availability

### Service Redundancy
- Multiple instances of application services
- Health checks and automatic restart policies
- Circuit breakers for external service calls

### Data Redundancy
- PostgreSQL replication (streaming/logical)
- Redis persistence (RDB + AOF)
- Regular backups with retention policies

### Monitoring and Alerting
- Prometheus scrapes metrics every 15s
- Grafana dashboards for real-time visibility
- Alerts for critical failures
- Health check endpoints on all services

## Security Architecture

### Network Security
- Isolated networks per tier
- No direct external access to data tier
- Firewall rules at infrastructure level
- TLS/SSL for external communications

### Authentication & Authorization
- JWT-based authentication
- API keys for service-to-service
- Role-based access control (RBAC)
- Token expiration and refresh

### Data Security
- Encrypted connections to databases
- Password hashing (bcrypt)
- Input validation and sanitization
- SQL injection prevention (parameterized queries)

### Secrets Management
- Environment variables for configuration
- No hardcoded secrets
- Secret rotation policies
- Consider external secret stores (Vault, AWS Secrets Manager)

## Deployment Strategies

### Development
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up
```
- Hot-reload enabled
- Debug logging
- Development passwords
- All ports exposed

### Production
```bash
docker-compose up -d
```
- Optimized builds
- Production logging
- Strong passwords
- Limited port exposure
- Resource limits enforced

### Blue-Green Deployment
1. Deploy new version alongside current
2. Test new version
3. Switch traffic to new version
4. Keep old version for rollback

### Canary Deployment
1. Deploy new version to small subset
2. Monitor metrics and errors
3. Gradually increase traffic
4. Full rollout or rollback

## Disaster Recovery

### Backup Strategy
- **PostgreSQL**: Daily automated backups
- **Redis**: Periodic RDB snapshots
- **Configuration**: Version-controlled in Git
- **Retention**: 7 days (configurable)

### Recovery Procedures
1. **Service Failure**: Automatic restart via Docker
2. **Data Corruption**: Restore from latest backup
3. **Complete Failure**: Rebuild from infrastructure as code

### RTO and RPO
- **RTO** (Recovery Time Objective): < 1 hour
- **RPO** (Recovery Point Objective): < 24 hours

## Performance Optimization

### Database Optimization
- Indexes on frequently queried columns
- Query plan analysis with EXPLAIN
- Connection pooling
- Read replicas for read-heavy loads

### Caching Strategy
- Cache frequently accessed data
- Appropriate TTL values
- Cache warming on startup
- Cache invalidation on updates

### Application Optimization
- Async I/O for all network calls
- Connection pooling
- Batch operations where possible
- Pagination for large datasets

### Monitoring and Profiling
- APM tools for application performance
- Slow query logging
- Cache hit rate monitoring
- Queue depth monitoring

## Future Enhancements

### Kubernetes Migration
- Helm charts for deployments
- HPA for auto-scaling
- StatefulSets for databases
- Ingress for routing

### Service Mesh
- Istio or Linkerd for traffic management
- mTLS between services
- Advanced routing and retries
- Circuit breakers

### Advanced Monitoring
- Distributed tracing (Jaeger/Zipkin)
- Log aggregation (ELK stack)
- Anomaly detection
- Predictive alerting

### API Gateway
- Kong or Traefik for API management
- Rate limiting
- Authentication/Authorization
- Request transformation

## Conclusion

This architecture provides a solid foundation for building scalable, maintainable AI applications with:

- ✅ **Scalability**: Horizontal and vertical scaling options
- ✅ **Reliability**: High availability and disaster recovery
- ✅ **Security**: Defense in depth with network isolation
- ✅ **Observability**: Comprehensive monitoring and alerting
- ✅ **Maintainability**: Clear separation of concerns and documentation
- ✅ **Performance**: Caching, async processing, and optimization

The modular design allows for gradual evolution and migration to more complex architectures (Kubernetes, service mesh) as requirements grow.

