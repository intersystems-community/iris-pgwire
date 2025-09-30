# IRIS SQL Translation API Documentation

## Overview

The IRIS SQL Translation API is a REST service that translates InterSystems IRIS SQL constructs to PostgreSQL-compatible equivalents. It provides high-performance translation with constitutional compliance monitoring, caching, and comprehensive analytics.

### Constitutional Requirements
- **5ms SLA**: All API endpoints must respond within 5 milliseconds
- **95% Compliance Rate**: Maintain 95% or higher SLA compliance
- **High Reliability**: Comprehensive error handling and graceful degradation

## Base URL

```
http://localhost:8000
```

## Authentication

Currently, the API does not require authentication. In production deployments, consider implementing:
- API key authentication
- JWT token validation
- Rate limiting per client

## Endpoints

### 1. Root Information
**GET** `/`

Returns basic API information and available endpoints.

#### Response
```json
{
  "service": "IRIS SQL Translation API",
  "version": "1.0.0",
  "description": "REST API for translating IRIS SQL constructs to PostgreSQL equivalents",
  "endpoints": {
    "translate": "/translate",
    "cache_stats": "/cache/stats",
    "cache_invalidate": "/cache/invalidate",
    "api_stats": "/stats",
    "health": "/health",
    "docs": "/docs"
  },
  "constitutional_compliance": "Sub-5ms response time SLA enforced"
}
```

### 2. SQL Translation
**POST** `/translate`

Translates IRIS SQL queries to PostgreSQL equivalents with comprehensive analysis.

#### Request Body
```json
{
  "sql": "SELECT %SQLUPPER(name) FROM users WHERE id = 123",
  "session_id": "session_123",
  "enable_caching": true,
  "enable_validation": true,
  "enable_debug": false,
  "validation_level": "semantic",
  "parameters": {
    "timeout_ms": 5000
  },
  "metadata": {
    "source": "application",
    "query_type": "user_lookup"
  }
}
```

#### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `sql` | string | Yes | - | IRIS SQL query to translate (1-50,000 chars) |
| `session_id` | string | No | null | Optional session identifier for tracking |
| `enable_caching` | boolean | No | true | Enable translation result caching |
| `enable_validation` | boolean | No | true | Enable semantic validation |
| `enable_debug` | boolean | No | false | Enable detailed debug tracing |
| `validation_level` | string | No | "semantic" | Validation rigor: basic, semantic, strict, exhaustive |
| `parameters` | object | No | null | Optional query parameters |
| `metadata` | object | No | null | Additional metadata for tracking |

#### Response
```json
{
  "success": true,
  "original_sql": "SELECT %SQLUPPER(name) FROM users WHERE id = 123",
  "translated_sql": "SELECT UPPER(name) FROM users WHERE id = 123;",
  "construct_mappings": [
    {
      "construct_type": "FUNCTION",
      "original_syntax": "%SQLUPPER(name)",
      "translated_syntax": "UPPER(name)",
      "confidence": 0.95,
      "source_location": {
        "line": 1,
        "column": 8,
        "length": 15,
        "original_text": "%SQLUPPER(name)"
      },
      "metadata": {
        "function_name": "%SQLUPPER"
      }
    }
  ],
  "performance_stats": {
    "translation_time_ms": 2.45,
    "cache_hit": false,
    "constructs_detected": 1,
    "constructs_translated": 1,
    "parsing_time_ms": 0.8,
    "mapping_time_ms": 1.2,
    "validation_time_ms": 0.45,
    "is_sla_compliant": true,
    "translation_success_rate": 1.0
  },
  "warnings": [],
  "validation_result": {
    "success": true,
    "confidence": 0.9,
    "issues": [],
    "performance_impact": "minimal",
    "recommendations": []
  },
  "debug_trace": null,
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

#### Status Codes
- `200`: Translation successful
- `400`: Invalid request (malformed SQL, validation errors)
- `500`: Internal server error

### 3. Health Check
**GET** `/health`

Returns API health status and basic operational metrics.

#### Response
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:45.123Z",
  "uptime_seconds": 3600.5,
  "requests_processed": 1250,
  "error_rate": 0.02,
  "sla_compliance": "compliant"
}
```

#### Health Status Values
- `healthy`: All systems operational, SLA compliant
- `degraded`: High error rate or SLA violations detected

### 4. Cache Statistics
**GET** `/cache/stats`

Returns translation cache performance metrics.

#### Response
```json
{
  "total_entries": 1500,
  "hit_rate": 0.85,
  "average_lookup_ms": 0.15,
  "memory_usage_mb": 12.5,
  "oldest_entry_age_minutes": 45,
  "constitutional_compliance": {
    "cache_hit_sla_benefit": "4.8ms average speedup",
    "cache_effectiveness": "excellent",
    "memory_efficiency": "optimal"
  }
}
```

#### Status Codes
- `200`: Cache statistics retrieved
- `503`: Cache disabled or unavailable

### 5. Cache Invalidation
**POST** `/cache/invalidate`

Invalidates translation cache entries, optionally by pattern.

#### Request Body
```json
{
  "pattern": "SELECT%",
  "confirm": true
}
```

#### Request Parameters
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pattern` | string | No | SQL pattern for selective invalidation (supports wildcards) |
| `confirm` | boolean | Yes | Must be true to confirm invalidation |

#### Response
```json
{
  "invalidated_count": 245,
  "pattern": "SELECT%",
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

#### Status Codes
- `200`: Invalidation successful
- `400`: Missing confirmation or invalid pattern
- `503`: Cache disabled

### 6. API Statistics
**GET** `/stats`

Returns comprehensive API and translator performance statistics.

#### Response
```json
{
  "api_stats": {
    "total_requests": 5000,
    "total_errors": 25,
    "error_rate": 0.005,
    "uptime_seconds": 7200.0,
    "requests_per_second": 0.69,
    "sla_violations": 3,
    "sla_compliance_rate": 0.9994
  },
  "translator_stats": {
    "total_translations": 4950,
    "average_translation_time_ms": 2.1,
    "cache_hit_rate": 0.82,
    "sla_compliance_rate": 0.9996,
    "active_sessions": 15,
    "constitutional_compliance": {
      "sla_requirement_ms": 5.0,
      "violations": 2,
      "compliance_rate": 0.9996
    }
  },
  "constitutional_compliance": {
    "api_sla_requirement_ms": 5.0,
    "api_sla_violations": 3,
    "overall_compliance_status": "compliant"
  }
}
```

## Error Handling

All endpoints return standardized error responses:

```json
{
  "error": "Error message",
  "details": "Detailed error information",
  "error_code": "validation_error",
  "timestamp": "2024-01-15T10:30:45.123Z"
}
```

### Error Codes
- `validation_error`: Request validation failed
- `translation_error`: Translation process failed
- `cache_disabled`: Cache operations requested but cache disabled
- `cache_stats_error`: Cache statistics retrieval failed
- `cache_invalidation_error`: Cache invalidation failed
- `confirmation_required`: Cache invalidation requires confirmation

## Usage Examples

### Basic Translation

```bash
curl -X POST "http://localhost:8000/translate" \
     -H "Content-Type: application/json" \
     -d '{
       "sql": "SELECT %SQLUPPER(name), %SQLLOWER(email) FROM users",
       "enable_debug": false
     }'
```

### Translation with Validation

```bash
curl -X POST "http://localhost:8000/translate" \
     -H "Content-Type: application/json" \
     -d '{
       "sql": "CREATE TABLE test (id INTEGER, data LONGVARCHAR)",
       "validation_level": "strict",
       "enable_validation": true
     }'
```

### Complex Query with Debug

```bash
curl -X POST "http://localhost:8000/translate" \
     -H "Content-Type: application/json" \
     -d '{
       "sql": "SELECT TOP 10 %SQLUPPER(name), JSON_EXTRACT(profile, \"$.email\") FROM users WHERE JSON_EXISTS(profile, \"$.active\")",
       "enable_debug": true,
       "validation_level": "exhaustive"
     }'
```

### Cache Management

```bash
# Get cache statistics
curl "http://localhost:8000/cache/stats"

# Invalidate all SELECT queries
curl -X POST "http://localhost:8000/cache/invalidate" \
     -H "Content-Type: application/json" \
     -d '{
       "pattern": "SELECT%",
       "confirm": true
     }'

# Invalidate entire cache
curl -X POST "http://localhost:8000/cache/invalidate" \
     -H "Content-Type: application/json" \
     -d '{
       "confirm": true
     }'
```

### Health and Monitoring

```bash
# Health check
curl "http://localhost:8000/health"

# Detailed statistics
curl "http://localhost:8000/stats"
```

## Performance Characteristics

### Response Times
- **Simple Queries**: < 1ms average
- **Complex Queries**: < 3ms average
- **Cache Hits**: < 0.5ms average
- **Constitutional SLA**: < 5ms maximum

### Throughput
- **Sustained Load**: 1000+ requests/second
- **Peak Load**: 5000+ requests/second
- **Cache Hit Rate**: 80-90% typical

### Memory Usage
- **Base Memory**: ~50MB
- **Cache Memory**: ~10-20MB (configurable)
- **Per Request**: ~1-2KB

## Constitutional Compliance

The API implements constitutional governance ensuring:

1. **Sub-5ms SLA**: All responses within 5 milliseconds
2. **Performance Monitoring**: Real-time SLA violation tracking
3. **Graceful Degradation**: Maintains service under load
4. **Quality Assurance**: High-confidence translations only

### Compliance Monitoring

Constitutional compliance is monitored through:
- Real-time performance metrics
- SLA violation counting
- Automatic alerting (when configured)
- Detailed compliance reporting

### Compliance Endpoints

Use `/stats` and `/health` endpoints to monitor constitutional compliance:
- SLA violation counts
- Compliance rates
- Performance trends
- System health status

## Configuration

### Environment Variables
- `API_HOST`: API bind address (default: "0.0.0.0")
- `API_PORT`: API port (default: 8000)
- `ENABLE_CACHE`: Enable translation caching (default: true)
- `CACHE_SIZE`: Maximum cache entries (default: 10000)
- `LOG_LEVEL`: Logging level (default: "INFO")

### Production Deployment

For production deployment:

1. **Enable HTTPS**: Use TLS/SSL certificates
2. **Configure Caching**: Optimize cache size for your workload
3. **Set Monitoring**: Configure health check monitoring
4. **Performance Tuning**: Adjust worker processes and memory limits
5. **Security**: Implement authentication and rate limiting

## OpenAPI/Swagger Documentation

Interactive API documentation is available at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

These provide:
- Interactive endpoint testing
- Request/response schemas
- Parameter validation
- Code generation support

## Client Libraries

### Python

```python
import requests

class IRISTranslationClient:
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url

    def translate(self, sql, **options):
        response = requests.post(
            f"{self.base_url}/translate",
            json={"sql": sql, **options}
        )
        response.raise_for_status()
        return response.json()

    def health_check(self):
        response = requests.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()

# Usage
client = IRISTranslationClient()
result = client.translate("SELECT %SQLUPPER(name) FROM users")
print(result["translated_sql"])
```

### JavaScript/Node.js

```javascript
class IRISTranslationClient {
    constructor(baseUrl = 'http://localhost:8000') {
        this.baseUrl = baseUrl;
    }

    async translate(sql, options = {}) {
        const response = await fetch(`${this.baseUrl}/translate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sql, ...options })
        });

        if (!response.ok) {
            throw new Error(`Translation failed: ${response.statusText}`);
        }

        return await response.json();
    }

    async healthCheck() {
        const response = await fetch(`${this.baseUrl}/health`);
        return await response.json();
    }
}

// Usage
const client = new IRISTranslationClient();
const result = await client.translate("SELECT %SQLUPPER(name) FROM users");
console.log(result.translated_sql);
```

## Best Practices

### Performance Optimization
1. **Enable Caching**: Use caching for repeated queries
2. **Batch Requests**: Group multiple translations when possible
3. **Optimize Queries**: Simplify complex IRIS constructs when possible
4. **Monitor SLA**: Track response times and compliance

### Error Handling
1. **Retry Logic**: Implement exponential backoff for retries
2. **Validate Inputs**: Check SQL syntax before sending requests
3. **Handle Timeouts**: Set appropriate request timeouts
4. **Log Errors**: Maintain comprehensive error logs

### Security
1. **Input Validation**: Sanitize SQL inputs to prevent injection
2. **Rate Limiting**: Implement client-side rate limiting
3. **HTTPS Only**: Use encrypted connections in production
4. **Authentication**: Implement proper API authentication

### Monitoring
1. **Health Checks**: Regular health endpoint monitoring
2. **Performance Metrics**: Track response times and error rates
3. **Cache Efficiency**: Monitor cache hit rates
4. **Constitutional Compliance**: Track SLA violation trends