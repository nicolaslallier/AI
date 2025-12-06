# Nginx DNS Resolution Architecture

## Visual Architecture Comparison

### Before: Static Upstream Resolution (Problematic)

```
┌─────────────────────────────────────────────────────────────────┐
│  NGINX STARTUP                                                  │
│                                                                 │
│  1. Parse nginx.conf                                           │
│  2. Resolve ALL upstream hosts via DNS                         │
│     ┌──────────────────────────────────────────┐              │
│     │  upstream frontend { server frontend:80; }│              │
│     │  upstream grafana  { server grafana:3000; }│             │
│     │  upstream prometheus { server prometheus:9090; }│        │
│     │  upstream tempo    { server tempo:3200; }│               │
│     │  upstream loki     { server loki:3100; }  ❌ DNS FAIL   │
│     │  upstream pgadmin  { server pgadmin:80; } │              │
│     └──────────────────────────────────────────┘              │
│                                                                 │
│  3. IF any DNS fails → EXIT WITH ERROR                         │
│  4. Cache resolved IPs FOREVER                                 │
│                                                                 │
│  ❌ RESULT: Nginx won't start if Loki is unavailable          │
└─────────────────────────────────────────────────────────────────┘

Problems:
  ❌ Tight coupling between services
  ❌ All services must be available at startup
  ❌ Cascading failures
  ❌ No dynamic service discovery
  ❌ Requires Nginx restart when services change
```

### After: Dynamic Runtime Resolution (Resilient)

```
┌─────────────────────────────────────────────────────────────────┐
│  NGINX STARTUP                                                  │
│                                                                 │
│  1. Parse nginx.conf                                           │
│  2. Load resolver configuration                                │
│     ┌──────────────────────────────────────────┐              │
│     │  resolver 127.0.0.11 valid=10s ipv6=off; │              │
│     │  # Docker's internal DNS server          │              │
│     └──────────────────────────────────────────┘              │
│                                                                 │
│  3. No DNS lookups yet - just configure resolver               │
│  4. Start successfully ✅                                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  REQUEST HANDLING (Runtime)                                     │
│                                                                 │
│  Request: GET /monitoring/loki/                                │
│                                                                 │
│  1. Extract upstream from variable                             │
│     ┌──────────────────────────────────────────┐              │
│     │  set $loki_upstream http://loki:3100;    │              │
│     │  proxy_pass $loki_upstream;              │              │
│     └──────────────────────────────────────────┘              │
│                                                                 │
│  2. Perform DNS lookup (if cache expired)                      │
│     ┌──────────────────────────────────────────┐              │
│     │  Query: loki                              │              │
│     │  Answer: 172.31.0.5 (cache for 10s)      │              │
│     └──────────────────────────────────────────┘              │
│                                                                 │
│  3. IF DNS fails → Return 502 (but Nginx keeps running) ⚠️    │
│  4. IF DNS succeeds → Proxy request to service ✅              │
│                                                                 │
│  ✅ RESULT: Nginx runs regardless of service availability     │
└─────────────────────────────────────────────────────────────────┘

Benefits:
  ✅ Loose coupling between services
  ✅ Services can start in any order
  ✅ Graceful degradation
  ✅ Automatic service discovery
  ✅ No Nginx restart needed
```

## DNS Resolution Timeline

```
Time    Event                           Nginx Behavior                  Service Status
─────────────────────────────────────────────────────────────────────────────────────

T+0s    Docker Compose Up               Nginx starts immediately        Services starting
        |                               ✅ Healthy                       
        |                               
T+5s    Loki container starts          No DNS lookup yet                Loki: healthy
        |                               (no requests received)           Grafana: healthy
        |                                                                Prometheus: healthy
        |                               
T+10s   First request arrives          DNS lookup for loki              All services: healthy
        GET /monitoring/loki/           → 172.31.0.5 (cache 10s)        
        |                               ✅ Request proxied successfully  
        |                               
T+15s   More requests                  Use cached DNS result            All services: healthy
        GET /monitoring/loki/           (no lookup needed)               
        |                               ✅ Fast response                 
        |                               
T+20s   Cache expires                  Next request triggers            All services: healthy
        |                               new DNS lookup                   
        |                               
T+20s   Loki restarts                  In-flight requests may fail      Loki: restarting
        docker restart loki             ⚠️ 502 Bad Gateway              Grafana: healthy
        |                                                                Prometheus: healthy
        |                               
T+22s   DNS cache expires              Stale cache (old IP)             Loki: restarting
        Request arrives                 ⚠️ 502 Bad Gateway (expected)   
        |                               
T+30s   Cache refreshed                DNS resolves new IP              Loki: healthy
        Request arrives                 → 172.31.0.6 (new container)    
        |                               ✅ Request succeeds              
        |                               
T+35s   Normal operation               Cached DNS, fast routing         All services: healthy
        All requests                    ✅ All services accessible       

Legend:
  ✅ Success / Healthy
  ⚠️ Warning / Temporary failure
  ❌ Error / Fatal failure
```

## Network Topology

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL CLIENTS                             │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                │ HTTP :80
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  HOST MACHINE                                                       │
│                                                                     │
│  Port Mapping: 80:80                                                │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DOCKER NETWORK: monitoring-net (172.31.0.0/24)                     │
│  DOCKER NETWORK: frontend-net (172.50.0.0/24)                       │
│                                                                     │
│  ┌─────────────────────────────────────────────────────┐           │
│  │  NGINX (ai_infra_nginx)                             │           │
│  │  ┌───────────────────────────────────────────────┐  │           │
│  │  │  DNS Resolver: 127.0.0.11                     │  │           │
│  │  │  Cache: 10 seconds                            │  │           │
│  │  │  Networks: frontend-net, monitoring-net       │  │           │
│  │  └───────────────────────────────────────────────┘  │           │
│  └────┬─────┬──────┬──────┬──────┬──────┬─────────────┘           │
│       │     │      │      │      │      │                           │
│       │     │      │      │      │      │                           │
│  ┌────▼──┐ ┌▼────┐ ┌▼───┐ ┌▼──┐ ┌▼──┐ ┌▼─────┐                   │
│  │Frontend│ │Grafa│ │Prom│ │Tem│ │Lok│ │pgAdm │                   │
│  │ :80    │ │:3000│ │:909│ │:32│ │:31│ │ :80  │                   │
│  │        │ │     │ │ 0  │ │00 │ │00 │ │      │                   │
│  └────────┘ └─────┘ └────┘ └───┘ └───┘ └──┬───┘                   │
│  frontend-  monitor- monito monitor monit   │                      │
│  net        ing-net  ring-   ring-   ring-  │                      │
│                      net     net     net     │                      │
│                                              │                      │
│                                              ▼                      │
│                            ┌───────────────────────────┐            │
│  DOCKER NETWORK:           │  POSTGRES                 │            │
│  database-net              │  :5432                    │            │
│  (172.23.0.0/24)           │  Internal only            │            │
│                            └───────────────────────────┘            │
│                                                                     │
│  ┌─────────────────────────────────────────────────────┐           │
│  │  DOCKER EMBEDDED DNS (127.0.0.11)                   │           │
│  │  ┌─────────────────────────────────────────────┐    │           │
│  │  │  Service Discovery Table                    │    │           │
│  │  │  ─────────────────────────────────────────  │    │           │
│  │  │  frontend    → 172.50.0.2                   │    │           │
│  │  │  grafana     → 172.31.0.3                   │    │           │
│  │  │  prometheus  → 172.31.0.4                   │    │           │
│  │  │  tempo       → 172.31.0.5                   │    │           │
│  │  │  loki        → 172.31.0.6                   │    │           │
│  │  │  pgadmin     → 172.50.0.3                   │    │           │
│  │  │  postgres    → 172.23.0.2                   │    │           │
│  │  │  ─────────────────────────────────────────  │    │           │
│  │  │  Updated in real-time as services start     │    │           │
│  │  └─────────────────────────────────────────────┘    │           │
│  └─────────────────────────────────────────────────────┘           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Request Flow with DNS Resolution

```
┌─────────────────────────────────────────────────────────────────────┐
│  Scenario: User accesses Grafana dashboard                         │
└─────────────────────────────────────────────────────────────────────┘

1. CLIENT REQUEST
   ┌────────────────────┐
   │  Browser           │
   │  GET /monitoring/  │
   │      grafana/      │
   └─────────┬──────────┘
             │
             ▼
2. NGINX RECEIVES REQUEST
   ┌────────────────────────────────────────┐
   │  Nginx Container                       │
   │  ─────────────────────────────────────│
   │  Match: location /monitoring/grafana/  │
   │  Execute: set $grafana_upstream        │
   │           http://grafana:3000          │
   └─────────┬──────────────────────────────┘
             │
             ▼
3. DNS RESOLUTION DECISION
   ┌────────────────────────────────────────┐
   │  Check DNS Cache                       │
   │  ─────────────────────────────────────│
   │  Is "grafana" cached?                  │
   │  Is cache still valid (<10s old)?     │
   └────┬───────────────────────────┬───────┘
        │                           │
        │ Cache HIT                 │ Cache MISS
        │ (Skip DNS)                │ (Lookup needed)
        ▼                           ▼
   ┌────────────────┐         ┌─────────────────────┐
   │  Use Cached IP │         │  Query Docker DNS   │
   │  172.31.0.3    │         │  127.0.0.11         │
   └────────┬───────┘         └─────────┬───────────┘
            │                           │
            │                           ▼
            │                 ┌──────────────────────┐
            │                 │ Docker DNS Response  │
            │                 │ grafana → 172.31.0.3 │
            │                 │ Cache for 10s        │
            │                 └─────────┬────────────┘
            │                           │
            └───────────────────────────┘
                            │
                            ▼
4. PROXY REQUEST TO UPSTREAM
   ┌────────────────────────────────────────┐
   │  Nginx forwards to Grafana             │
   │  ─────────────────────────────────────│
   │  Destination: http://172.31.0.3:3000   │
   │  Headers: Host, X-Real-IP, etc.        │
   └─────────┬──────────────────────────────┘
             │
             ▼
5. GRAFANA PROCESSES REQUEST
   ┌────────────────────────────────────────┐
   │  Grafana Container                     │
   │  ─────────────────────────────────────│
   │  Receives request                      │
   │  Generates dashboard HTML              │
   │  Returns response                      │
   └─────────┬──────────────────────────────┘
             │
             ▼
6. NGINX RETURNS RESPONSE
   ┌────────────────────────────────────────┐
   │  Nginx forwards response               │
   │  ─────────────────────────────────────│
   │  Status: 200 OK                        │
   │  Content: Dashboard HTML               │
   └─────────┬──────────────────────────────┘
             │
             ▼
7. CLIENT RECEIVES RESPONSE
   ┌────────────────────┐
   │  Browser           │
   │  Renders Grafana   │
   │  Dashboard         │
   └────────────────────┘

Total Time Breakdown:
  DNS Resolution: 0-2ms (0ms if cached, 1-2ms if lookup needed)
  Nginx Processing: <1ms
  Grafana Response: 50-200ms (typical)
  Network Overhead: <5ms
  ────────────────────────
  Total: 51-208ms (DNS overhead is negligible)
```

## Failure Scenarios

### Scenario 1: Service Temporarily Unavailable

```
┌─────────────────────────────────────────────────────────────────────┐
│  Scenario: Loki is restarting                                      │
└─────────────────────────────────────────────────────────────────────┘

Time    Action                  Nginx Behavior              User Experience
────────────────────────────────────────────────────────────────────────────

T+0s    User requests           DNS lookup: loki → NULL     
        /monitoring/loki/       (service not found)         

        Nginx Decision:         ✅ Nginx stays running      ⚠️ Error page
        Return 502              ⚠️ Log warning              "Bad Gateway"
                                                            (monitoring 
                                                             temporarily down)

T+10s   Loki comes online      DNS cache expired            
        Container healthy       

T+11s   User requests again     DNS lookup: loki →          ✅ Success
        /monitoring/loki/       172.31.0.6 ✅               Logs dashboard
                                                            loads normally

Impact:  ⚠️ Temporary (10-15s)   ✅ No restart needed       ⚠️ Brief downtime
         disruption             ✅ Other services OK        ✅ Auto-recovery
```

### Scenario 2: Service Never Started

```
┌─────────────────────────────────────────────────────────────────────┐
│  Scenario: Loki service excluded from startup                      │
│  Command: docker-compose up -d nginx frontend grafana prometheus   │
└─────────────────────────────────────────────────────────────────────┘

Service         Status          Nginx Behavior              User Access
────────────────────────────────────────────────────────────────────────────

Frontend        ✅ Running      Routes to 172.50.0.2        ✅ http://localhost/
                                                           (Main app works)

Grafana         ✅ Running      Routes to 172.31.0.3        ✅ /monitoring/grafana/
                                                           (Monitoring works)

Prometheus      ✅ Running      Routes to 172.31.0.4        ✅ /monitoring/prometheus/
                                                           (Metrics work)

Loki            ❌ Not Started  DNS lookup fails            ⚠️ /monitoring/loki/
                                Returns 502                 (Shows error)

Tempo           ❌ Not Started  DNS lookup fails            ⚠️ /monitoring/tempo/
                                Returns 502                 (Shows error)

Result:  Core application works ✅
         Partial monitoring works ✅  
         Missing services show 502 ⚠️
         System is functional ✅
```

### Scenario 3: DNS System Failure (Rare)

```
┌─────────────────────────────────────────────────────────────────────┐
│  Scenario: Docker DNS service (127.0.0.11) fails                   │
└─────────────────────────────────────────────────────────────────────┘

Probability: Very Low (Docker internal component failure)
Duration: Until Docker daemon restart
Scope: All containers in the host

Nginx Behavior:
  ❌ All upstream DNS lookups fail
  ⚠️ Cached entries continue working (for up to 10s)
  ⚠️ New requests return 502
  ✅ Nginx continues running (doesn't crash)
  ✅ Static endpoints still work (/health, redirects)

Mitigation:
  1. Monitor DNS resolution errors in Nginx logs
  2. Alert on sustained 502 errors
  3. Have Docker daemon restart procedure ready
  4. Consider external health check monitoring

Recovery:
  1. Restart Docker daemon
  2. Containers auto-restart (restart: unless-stopped)
  3. DNS resolution resumes
  4. Normal operation restored (no config changes needed)
```

## Comparison Matrix

| Aspect | Static Upstreams | Dynamic Resolution |
|--------|-----------------|-------------------|
| **Startup Dependency** | All services required ❌ | Only frontend required ✅ |
| **Service Discovery** | None (static IPs) ❌ | Automatic (via DNS) ✅ |
| **Fault Tolerance** | Fails if any service down ❌ | Continues with available services ✅ |
| **Service Restart** | Requires Nginx reload ❌ | Automatic (within cache timeout) ✅ |
| **DNS Overhead** | None ✅ | Minimal (~1-2ms per 10s) ⚠️ |
| **Cache Efficiency** | Perfect (permanent) ✅ | Very Good (10s TTL) ✅ |
| **Debugging** | Simple (static config) ✅ | Slightly complex (check cache) ⚠️ |
| **Scalability** | Poor (single instance) ❌ | Good (supports discovery) ✅ |
| **Resilience** | Low (brittle) ❌ | High (graceful degradation) ✅ |
| **Complexity** | Low ✅ | Medium ⚠️ |
| **Production Ready** | For monoliths only ⚠️ | For microservices ✅ |

Legend:
  ✅ Positive / Advantage
  ⚠️ Trade-off / Acceptable
  ❌ Negative / Disadvantage

## DNS Cache Tuning Guidelines

```yaml
Scenario                    Recommended Cache TTL   Rationale
─────────────────────────────────────────────────────────────────────

Development Environment     valid=5s                Fast service discovery
                                                    Quick iteration

Staging Environment         valid=10s (default)     Balance speed vs discovery
                                                    Good for testing

Production (low traffic)    valid=30s               Reduce DNS overhead
                                                    Services rarely restart

Production (high traffic)   valid=60s               Minimize DNS queries
                                                    Optimize performance

Production (zero-downtime)  valid=5s + Circuit      Fast failure detection
                            Breaker                 + Service mesh

Container Orchestration     valid=5s                Rapid service movement
(Kubernetes/Swarm)                                 Frequent scaling
```

### Configuration Example

```nginx
# Development - Fast discovery, frequent restarts expected
resolver 127.0.0.11 valid=5s ipv6=off;

# Staging - Balance between discovery and performance
resolver 127.0.0.11 valid=10s ipv6=off;

# Production - Optimize for performance, add fallback
resolver 127.0.0.11 valid=30s ipv6=off;
resolver 8.8.8.8 valid=300s;  # Fallback for external DNS

# Kubernetes - Fast discovery for dynamic orchestration
resolver kube-dns.kube-system.svc.cluster.local valid=5s ipv6=off;
```

## Key Takeaways

1. **Dynamic DNS resolution enables service independence** - Services start in any order
2. **Runtime resolution trades minimal overhead for flexibility** - ~1-2ms DNS query every 10s
3. **Docker's embedded DNS (127.0.0.11) makes this seamless** - No external dependencies
4. **Cache TTL is tunable based on environment** - Balance between performance and discovery
5. **Graceful degradation is built-in** - System works with partial service availability
6. **Zero-downtime updates are possible** - No Nginx restart needed for service changes
7. **Monitoring is essential** - Track 502 errors to detect service health issues
8. **This is microservices best practice** - Aligns with 12-factor app principles

---

**Note**: This architecture document complements the detailed implementation guide in [README-NGINX-DNS.md](README-NGINX-DNS.md)

