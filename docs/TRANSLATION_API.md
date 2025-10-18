# SQL Translation REST API

**Microservice for translating IRIS SQL to PostgreSQL equivalents**

The Translation API provides a standalone REST interface for SQL translation, separate from the PGWire protocol server. This enables pre-translation of queries, testing, debugging, and integration with external tools.

---

## Table of Contents

- [Quick Start](#quick-start)
- [API Endpoints](#api-endpoints)
- [Request/Response Models](#requestresponse-models)
- [Features](#features)
- [Performance & SLA](#performance--sla)
- [Usage Examples](#usage-examples)
- [Integration Patterns](#integration-patterns)
- [Monitoring & Debugging](#monitoring--debugging)

---

## Quick Start

### Start the API Server

```bash
# Using uvicorn directly
uvicorn iris_pgwire.sql_translator.api:get_translation_api --reload --port 8000

# Or using Python
python -c "
from iris_pgwire.sql_translator.api import get_translation_api
import uvicorn

app = get_translation_api()
uvicorn.run(app, host='0.0.0.0', port=8000)
"
```

### Access Interactive Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **API Root**: http://localhost:8000/

### Simple Translation Request

```bash
# Using curl
curl -X POST "http://localhost:8000/translate" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "SELECT TOP 10 * FROM users WHERE age > 21",
    "enable_caching": true,
    "validation_level": "semantic"
  }'
```

```python
# Using Python httpx
import httpx

async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:8000/translate",
        json={
            "sql": "SELECT TOP 10 * FROM users WHERE age > 21",
            "enable_caching": True,
            "validation_level": "semantic"
        }
    )
    result = response.json()
    print(result['translated_sql'])
```

---

## API Endpoints

### `POST /translate`

Translate IRIS SQL to PostgreSQL equivalent.

**Request Body**:
```json
{
  "sql": "SELECT TOP 10 * FROM users",
  "session_id": "optional-session-id",
  "enable_caching": true,
  "enable_validation": true,
  "enable_debug": false,
  "validation_level": "semantic",
  "parameters": {},
  "metadata": {}
}
```

**Response**:
```json
{
  "success": true,
  "original_sql": "SELECT TOP 10 * FROM users",
  "translated_sql": "SELECT * FROM users LIMIT 10",
  "construct_mappings": [...],
  "performance_stats": {
    "total_time_ms": 2.34,
    "parse_time_ms": 1.12,
    "validation_time_ms": 0.45
  },
  "warnings": [],
  "timestamp": "2025-01-18T10:30:00Z"
}
```

### `GET /cache/stats`

Get translation cache statistics.

**Response**:
```json
{
  "total_entries": 1234,
  "hit_rate": 0.85,
  "average_lookup_ms": 0.23,
  "memory_usage_mb": 12.5,
  "oldest_entry_age_minutes": 45,
  "constitutional_compliance": {
    "cache_lookup_sla_ms": 1.0,
    "sla_compliance_rate": 0.99
  }
}
```

### `POST /cache/invalidate`

Invalidate translation cache entries.

**Request Body**:
```json
{
  "pattern": "SELECT%",  // Optional: SQL pattern for selective invalidation
  "confirm": true        // Required: Must be true to proceed
}
```

**Response**:
```json
{
  "invalidated_count": 42,
  "pattern": "SELECT%",
  "timestamp": "2025-01-18T10:30:00Z"
}
```

### `GET /stats`

Get comprehensive API and translator statistics.

**Response**:
```json
{
  "api_stats": {
    "total_requests": 10000,
    "total_errors": 5,
    "error_rate": 0.0005,
    "uptime_seconds": 86400,
    "requests_per_second": 115.7,
    "sla_violations": 3,
    "sla_compliance_rate": 0.9997
  },
  "translator_stats": {
    "total_translations": 9995,
    "average_translation_time_ms": 2.1,
    "cache_hit_rate": 0.85
  },
  "constitutional_compliance": {
    "api_sla_requirement_ms": 5.0,
    "api_sla_violations": 3,
    "overall_compliance_status": "compliant"
  }
}
```

### `GET /health`

Health check endpoint for monitoring.

**Response**:
```json
{
  "status": "healthy",  // "healthy", "degraded", or "unhealthy"
  "timestamp": "2025-01-18T10:30:00Z",
  "uptime_seconds": 86400,
  "requests_processed": 10000,
  "error_rate": 0.0005,
  "sla_compliance": "compliant"
}
```

### `GET /`

API root with service information and available endpoints.

---

## Request/Response Models

### TranslationRequest

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `sql` | string | ✅ Yes | - | IRIS SQL to translate (1-50,000 chars) |
| `session_id` | string | No | null | Optional session identifier for tracking |
| `enable_caching` | boolean | No | true | Enable translation result caching |
| `enable_validation` | boolean | No | true | Enable semantic validation |
| `enable_debug` | boolean | No | false | Enable debug tracing |
| `validation_level` | string | No | "semantic" | Validation rigor: basic, semantic, strict, exhaustive |
| `parameters` | object | No | null | Query parameters for parameterized queries |
| `metadata` | object | No | null | Additional metadata for tracking |

### TranslationResponse

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Whether translation succeeded |
| `original_sql` | string | Original IRIS SQL |
| `translated_sql` | string | Translated PostgreSQL SQL |
| `construct_mappings` | array | Applied construct mappings |
| `performance_stats` | object | Performance metrics |
| `warnings` | array | Translation warnings |
| `validation_result` | object | Validation results (if enabled) |
| `debug_trace` | object | Debug trace (if enabled) |
| `timestamp` | string | Response timestamp (ISO 8601) |

---

## Features

### 1. High-Performance Caching

- **Sub-millisecond lookups**: Average <0.5ms cache hit
- **Intelligent invalidation**: Pattern-based or full cache clearing
- **Memory-efficient**: Automatic eviction based on usage
- **Hit rate tracking**: Monitor cache effectiveness

### 2. Multiple Validation Levels

| Level | Description | Use Case | Performance |
|-------|-------------|----------|-------------|
| `basic` | Syntax validation only | Production (fastest) | ~0.5ms |
| `semantic` | Syntax + semantic checks | Default (recommended) | ~1-2ms |
| `strict` | Full validation with warnings | Testing/debugging | ~2-3ms |
| `exhaustive` | All validations + deep analysis | Development/analysis | ~3-5ms |

### 3. Constitutional Compliance

- **5ms SLA**: Translation API targets sub-5ms response times
- **SLA Tracking**: Violations logged and reported in `/stats`
- **Automatic Monitoring**: Health endpoint reflects SLA compliance
- **Performance Metrics**: Detailed timing for all operations

### 4. Debug Tracing

When `enable_debug: true`:
- Parsing step breakdown
- Mapping decision logs
- Performance timing for each stage
- Warning and error details

### 5. Error Handling

Standardized error responses with:
- HTTP status codes (400, 422, 500, 503)
- Error codes for programmatic handling
- Detailed error messages
- Timestamp for debugging

---

## Performance & SLA

### Response Time Targets

| Operation | Target | Typical |
|-----------|--------|---------|
| Cache hit | <1ms | 0.2-0.5ms |
| Simple query translation | <5ms | 2-3ms |
| Complex query translation | <10ms | 5-8ms |
| Vector query translation | <5ms | 3-4ms |
| Cache invalidation | <50ms | 10-20ms |

### Throughput

- **Single instance**: 200-500 requests/second
- **With caching**: 1000+ requests/second (85% hit rate)
- **Concurrent connections**: 100+ simultaneous

### SLA Compliance

**Constitutional Requirement**: 99.9% of requests < 5ms

Monitoring:
```bash
# Check SLA compliance
curl http://localhost:8000/stats | jq '.api_stats.sla_compliance_rate'
# Expected: > 0.999 (99.9%)
```

---

## Usage Examples

### Example 1: Basic Query Translation

```python
import httpx

async def translate_query(sql: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/translate",
            json={"sql": sql}
        )
        result = response.json()
        return result['translated_sql']

# Usage
translated = await translate_query("SELECT TOP 100 * FROM users")
print(translated)  # "SELECT * FROM users LIMIT 100"
```

### Example 2: Vector Query Translation

```python
async def translate_vector_query(sql: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/translate",
            json={
                "sql": sql,
                "enable_debug": True,
                "validation_level": "semantic"
            }
        )
        result = response.json()

        print(f"Original: {result['original_sql']}")
        print(f"Translated: {result['translated_sql']}")
        print(f"Time: {result['performance_stats']['total_time_ms']}ms")

        if result['warnings']:
            print(f"Warnings: {result['warnings']}")

# Vector similarity query
vector_sql = """
    SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2]', FLOAT)) as score
    FROM docs ORDER BY score DESC LIMIT 10
"""
await translate_vector_query(vector_sql)
```

### Example 3: Batch Translation with Caching

```python
async def batch_translate(queries: list[str]):
    async with httpx.AsyncClient() as client:
        # First pass - populate cache
        tasks = [
            client.post(
                "http://localhost:8000/translate",
                json={"sql": sql, "enable_caching": True}
            )
            for sql in queries
        ]

        responses = await asyncio.gather(*tasks)

        # Second pass - should hit cache
        tasks = [
            client.post(
                "http://localhost:8000/translate",
                json={"sql": sql, "enable_caching": True}
            )
            for sql in queries
        ]

        cached_responses = await asyncio.gather(*tasks)

        # Check cache effectiveness
        stats_response = await client.get("http://localhost:8000/cache/stats")
        stats = stats_response.json()

        print(f"Cache hit rate: {stats['hit_rate']*100:.1f}%")
        print(f"Average lookup: {stats['average_lookup_ms']:.2f}ms")

# Usage
queries = [
    "SELECT * FROM users",
    "SELECT COUNT(*) FROM orders",
    "SELECT TOP 10 * FROM products"
]
await batch_translate(queries)
```

### Example 4: Integration with BI Dashboard

```python
class BIDashboardTranslator:
    """Pre-translate BI dashboard queries on startup"""

    def __init__(self, api_url: str = "http://localhost:8000"):
        self.api_url = api_url
        self.translated_queries = {}

    async def initialize_dashboard(self, dashboard_id: str, queries: dict):
        """Pre-translate all dashboard queries"""
        async with httpx.AsyncClient() as client:
            for widget_id, sql in queries.items():
                response = await client.post(
                    f"{self.api_url}/translate",
                    json={
                        "sql": sql,
                        "session_id": dashboard_id,
                        "metadata": {"widget_id": widget_id},
                        "enable_caching": True
                    }
                )

                result = response.json()
                self.translated_queries[widget_id] = result['translated_sql']

        return self.translated_queries

# Usage
translator = BIDashboardTranslator()
dashboard_queries = {
    "sales_chart": "SELECT region, SUM(sales) FROM orders GROUP BY region",
    "top_products": "SELECT TOP 10 product_id, COUNT(*) FROM orders GROUP BY product_id"
}
translated = await translator.initialize_dashboard("dash_123", dashboard_queries)
```

---

## Integration Patterns

### Pattern 1: Pre-Translation Proxy

```python
"""
Translation proxy for existing applications.
Intercepts IRIS SQL, translates, forwards to PostgreSQL.
"""

from fastapi import FastAPI, Request
import httpx

app = FastAPI()
translation_api = "http://localhost:8000"

@app.post("/query")
async def query_proxy(request: Request):
    body = await request.json()
    iris_sql = body.get("sql")

    # Translate IRIS SQL to PostgreSQL
    async with httpx.AsyncClient() as client:
        translation_response = await client.post(
            f"{translation_api}/translate",
            json={"sql": iris_sql, "enable_caching": True}
        )
        result = translation_response.json()

    # Execute translated SQL against PostgreSQL/PGWire
    pg_sql = result['translated_sql']
    # ... execute pg_sql and return results
```

### Pattern 2: Query Optimization Pipeline

```python
"""
Analyze and optimize queries before execution.
"""

async def optimize_query(sql: str) -> dict:
    async with httpx.AsyncClient() as client:
        # Translate with full validation
        response = await client.post(
            "http://localhost:8000/translate",
            json={
                "sql": sql,
                "validation_level": "exhaustive",
                "enable_debug": True
            }
        )

        result = response.json()

        # Analyze translation for optimization opportunities
        optimizations = {
            "original_sql": result['original_sql'],
            "optimized_sql": result['translated_sql'],
            "warnings": result['warnings'],
            "performance_impact": result['performance_stats']
        }

        return optimizations
```

### Pattern 3: Microservice Architecture

```python
"""
Translation API as a standalone microservice in container orchestration.
"""

# docker-compose.yml
"""
services:
  translation-api:
    image: iris-translation-api:latest
    ports:
      - "8000:8000"
    environment:
      - CACHE_SIZE=10000
      - LOG_LEVEL=info
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  app-server:
    image: my-app:latest
    environment:
      - TRANSLATION_API_URL=http://translation-api:8000
    depends_on:
      - translation-api
"""
```

---

## Monitoring & Debugging

### Health Monitoring

```bash
# Simple health check
curl http://localhost:8000/health

# Detailed monitoring with stats
curl http://localhost:8000/stats | jq '{
  uptime: .api_stats.uptime_seconds,
  requests: .api_stats.total_requests,
  error_rate: .api_stats.error_rate,
  sla_violations: .api_stats.sla_violations,
  sla_compliance: .api_stats.sla_compliance_rate
}'
```

### Performance Analysis

```python
async def analyze_api_performance():
    async with httpx.AsyncClient() as client:
        stats_response = await client.get("http://localhost:8000/stats")
        stats = stats_response.json()

        # Check SLA compliance
        sla_compliance = stats['api_stats']['sla_compliance_rate']
        if sla_compliance < 0.999:
            print(f"⚠️ SLA compliance below target: {sla_compliance*100:.2f}%")

        # Check error rate
        error_rate = stats['api_stats']['error_rate']
        if error_rate > 0.01:
            print(f"⚠️ High error rate: {error_rate*100:.2f}%")

        # Check cache effectiveness
        cache_stats = await client.get("http://localhost:8000/cache/stats")
        cache = cache_stats.json()

        hit_rate = cache['hit_rate']
        if hit_rate < 0.80:
            print(f"⚠️ Cache hit rate below target: {hit_rate*100:.1f}%")
```

### Debug Tracing

```bash
# Enable debug mode for detailed analysis
curl -X POST "http://localhost:8000/translate" \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "SELECT TOP 10 * FROM users",
    "enable_debug": true,
    "validation_level": "exhaustive"
  }' | jq '.debug_trace'
```

### Log Analysis

The API logs include:
- Request/response timing
- SLA violations
- Cache hit/miss events
- Validation warnings
- Error details with stack traces

---

## Production Deployment

### Environment Variables

```bash
# API Configuration
TRANSLATION_API_PORT=8000
TRANSLATION_API_HOST=0.0.0.0
TRANSLATION_API_WORKERS=4

# Cache Configuration
TRANSLATION_CACHE_SIZE=10000
TRANSLATION_CACHE_TTL_SECONDS=3600

# Performance Tuning
TRANSLATION_SLA_MS=5.0
TRANSLATION_VALIDATION_LEVEL=semantic

# Logging
LOG_LEVEL=info
LOG_FORMAT=json
```

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD ["uvicorn", "iris_pgwire.sql_translator.api:get_translation_api", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: translation-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: translation-api
  template:
    metadata:
      labels:
        app: translation-api
    spec:
      containers:
      - name: api
        image: iris-translation-api:latest
        ports:
        - containerPort: 8000
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: translation-api
spec:
  selector:
    app: translation-api
  ports:
  - port: 8000
    targetPort: 8000
  type: LoadBalancer
```

---

## Summary

The SQL Translation API provides:

✅ **REST interface** for IRIS → PostgreSQL translation
✅ **High performance** with <5ms SLA and caching
✅ **Multiple validation levels** for different use cases
✅ **Constitutional compliance** with SLA tracking
✅ **Production-ready** monitoring and health checks
✅ **Easy integration** with existing systems
✅ **Comprehensive documentation** via Swagger/ReDoc

**Use Cases**:
- Pre-translation of queries for BI dashboards
- Query testing and debugging
- Integration with external tools
- Microservice architectures
- Query optimization pipelines

**Demo**: Run `examples/translation_api_demo.py` to see all features in action
