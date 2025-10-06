# IRIS SQL Translation System - Developer Guide

## Overview

This guide provides comprehensive documentation for developers working with the IRIS SQL Translation System. The system translates InterSystems IRIS SQL constructs to PostgreSQL equivalents with constitutional compliance monitoring and high-performance caching.

## Architecture Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   API Layer    │    │  Translation     │    │   Registries    │
│   (FastAPI)    │◄──►│    Engine        │◄──►│   (Mappings)    │
│                │    │   (Translator)   │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│    Caching      │    │   Validation     │    │    Parser       │
│   (LRU/TTL)     │    │   (Semantic)     │    │   (Constructs)  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Performance    │    │   Confidence     │    │  Constitutional │
│   Monitoring    │    │    Analysis      │    │   Compliance    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

## Core Components

### 1. Translation Engine

The main orchestrator for all translation operations.

```python
from iris_pgwire.sql_translator.translator import IRISSQLTranslator, TranslationContext

# Initialize translator
translator = IRISSQLTranslator(
    enable_caching=True,
    enable_validation=True,
    enable_debug=False
)

# Create translation context
context = TranslationContext(
    original_sql="SELECT %SQLUPPER(name) FROM users",
    session_id="session_123",
    enable_caching=True,
    enable_validation=True,
    validation_level=ValidationLevel.SEMANTIC
)

# Perform translation
result = translator.translate(context)
```

### 2. Parser System

Identifies and categorizes IRIS constructs in SQL.

```python
from iris_pgwire.sql_translator.parser import get_parser
from iris_pgwire.sql_translator.models import ConstructType

parser = get_parser()
constructs, debug_info = parser.parse(
    "SELECT %SQLUPPER(name), JSON_EXTRACT(data, '$.field') FROM users",
    debug_mode=True
)

for construct in constructs:
    print(f"Type: {construct.construct_type}")
    print(f"Text: {construct.original_text}")
    print(f"Location: Line {construct.location.line}, Col {construct.location.column}")
```

### 3. Registry System

Manages mappings between IRIS and PostgreSQL constructs.

```python
from iris_pgwire.sql_translator.mappings import (
    get_function_registry,
    get_datatype_registry,
    get_construct_registry,
    get_document_filter_registry
)

# Function mappings
function_registry = get_function_registry()
mapping = function_registry.get_mapping("%SQLUPPER")
if mapping:
    print(f"PostgreSQL function: {mapping.postgresql_function}")
    print(f"Confidence: {mapping.confidence}")

# Data type mappings
datatype_registry = get_datatype_registry()
type_mapping = datatype_registry.get_mapping("LONGVARCHAR")
if type_mapping:
    print(f"PostgreSQL type: {type_mapping.postgresql_type}")
```

### 4. Validation System

Validates translation accuracy and semantic equivalence.

```python
from iris_pgwire.sql_translator.validator import get_validator, ValidationContext, ValidationLevel

validator = get_validator()
context = ValidationContext(
    original_sql="SELECT %SQLUPPER(name) FROM users",
    translated_sql="SELECT UPPER(name) FROM users",
    construct_mappings=[],
    validation_level=ValidationLevel.SEMANTIC
)

result = validator.validate_query_equivalence(context)
print(f"Validation success: {result.success}")
print(f"Confidence: {result.confidence}")
```

### 5. Cache System

High-performance LRU/TTL caching for translation results.

```python
from iris_pgwire.sql_translator.cache import get_cache, generate_cache_key

cache = get_cache()
cache_key = generate_cache_key(
    sql="SELECT * FROM users",
    parameters=None,
    metadata={"session_id": "123"}
)

# Check cache
entry = cache.get(cache_key)
if entry:
    print(f"Cache hit: {entry.translated_sql}")
else:
    # Perform translation and cache result
    cache.put(cache_key, translated_sql, mappings, performance_stats)
```

## Extension Points

### 1. Custom Function Mappings

Add new IRIS function mappings:

```python
from iris_pgwire.sql_translator.mappings.functions import get_function_registry
from iris_pgwire.sql_translator.models import FunctionMapping

# Get registry
registry = get_function_registry()

# Add custom mapping
custom_mapping = FunctionMapping(
    iris_function="%CUSTOM_FUNCTION",
    postgresql_function="custom_pg_function",
    confidence=0.9,
    notes="Custom function mapping for specialized use case"
)

registry.add_mapping(custom_mapping)
```

### 2. Custom Data Types

Add new data type mappings:

```python
from iris_pgwire.sql_translator.mappings.datatypes import get_datatype_registry
from iris_pgwire.sql_translator.models import TypeMapping

registry = get_datatype_registry()

# Add custom type mapping
custom_type = TypeMapping(
    iris_type="CUSTOM_TYPE",
    postgresql_type="jsonb",
    confidence=0.8,
    notes="Custom type for specialized data structures"
)

registry.add_mapping(custom_type)
```

### 3. Custom Validators

Implement custom validation logic:

```python
from iris_pgwire.sql_translator.validator import SemanticValidator
from iris_pgwire.sql_translator.models import ValidationResult, ValidationIssue

class CustomValidator(SemanticValidator):
    def validate_custom_construct(self, original_sql, translated_sql):
        """Custom validation for specific constructs"""
        issues = []

        # Custom validation logic
        if "CUSTOM_PATTERN" in original_sql:
            if "expected_translation" not in translated_sql:
                issues.append(ValidationIssue(
                    severity="error",
                    message="Custom pattern not properly translated"
                ))

        return ValidationResult(
            success=len(issues) == 0,
            confidence=0.9 if len(issues) == 0 else 0.3,
            issues=issues
        )
```

### 4. Custom Cache Strategies

Implement custom caching strategies:

```python
from iris_pgwire.sql_translator.cache import TranslationCache
from iris_pgwire.sql_translator.models import CacheEntry

class CustomCache(TranslationCache):
    def __init__(self, custom_ttl_rules=None):
        super().__init__()
        self.custom_ttl_rules = custom_ttl_rules or {}

    def _get_ttl_for_query(self, sql):
        """Custom TTL based on query patterns"""
        if "SELECT" in sql.upper():
            return 3600  # 1 hour for SELECT queries
        elif "CREATE" in sql.upper():
            return 86400  # 24 hours for DDL
        else:
            return 1800   # 30 minutes default
```

## Configuration

### Environment Variables

```bash
# Translation settings
IRIS_TRANSLATION_CACHE_SIZE=10000
IRIS_TRANSLATION_CACHE_TTL=3600
IRIS_TRANSLATION_DEBUG=false
IRIS_TRANSLATION_VALIDATION=true

# Performance settings
IRIS_TRANSLATION_SLA_MS=5
IRIS_TRANSLATION_TIMEOUT_MS=30000
IRIS_TRANSLATION_MAX_WORKERS=4

# API settings
IRIS_API_HOST=0.0.0.0
IRIS_API_PORT=8000
IRIS_API_WORKERS=1

# Logging
IRIS_LOG_LEVEL=INFO
IRIS_LOG_FORMAT=structured
```

### Configuration File

```python
# config.py
from iris_pgwire.sql_translator.config import TranslationConfig

config = TranslationConfig(
    enable_caching=True,
    cache_size=10000,
    cache_ttl_seconds=3600,
    enable_validation=True,
    validation_level="semantic",
    enable_debug=False,
    sla_requirement_ms=5.0,
    constitutional_compliance=True
)
```

## Package Management

### Local Development: Use `uv`

For local development, use `uv` for fast dependency management:

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project dependencies
uv sync

# Run tests locally
uv run pytest tests/

# Add a new dependency
uv add package-name

# Add a development dependency
uv add --dev package-name
```

**Why `uv`?**
- 10-100× faster than `pip` for dependency resolution
- Automatic lockfile management (`uv.lock`)
- Better developer experience for local iteration

### Docker/CI: Use `pip`

Docker containers and CI pipelines use standard `pip`:

```dockerfile
# Dockerfile example
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install -e ".[dev,test]"
```

**Why `pip` in Docker?**
- Simpler, more portable (no extra binary needed)
- Standard across Python ecosystem for CI/CD
- Containers are ephemeral - reproducibility comes from `pyproject.toml` and `uv.lock`

### Dependency Sources

All dependencies are defined in `pyproject.toml`:

```toml
[project]
dependencies = [
    "structlog>=23.0.0",
    "intersystems-irispython>=5.1.2",
    # ... core dependencies
]

[project.optional-dependencies]
test = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    # ... test dependencies
]
dev = [
    "black>=23.0.0",
    "ruff>=0.1.0",
    # ... development tools
]
```

**NEVER hardcode dependencies** in shell scripts or Docker commands. Always reference `pyproject.toml`:

```bash
# ✅ CORRECT
pip install -e ".[test]"

# ❌ WRONG - duplicates pyproject.toml
pip install pytest>=7.0.0 pytest-asyncio>=0.21.0
```

### Integration Test Dependencies

The `docker-compose.yml` pytest-integration service automatically installs test dependencies:

```yaml
# Automatically uses pyproject.toml [project.optional-dependencies.test]
command: pip install --quiet -e '.[test]'
```

This ensures Docker tests use the same dependency versions as local development.

## Testing Framework

### Unit Tests

```python
import pytest
from iris_pgwire.sql_translator.translator import IRISSQLTranslator, TranslationContext

class TestCustomTranslations:
    def setup_method(self):
        self.translator = IRISSQLTranslator()

    def test_function_translation(self):
        sql = "SELECT %SQLUPPER(name) FROM users"
        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)

        assert "UPPER(name)" in result.translated_sql
        assert result.performance_stats.is_sla_compliant
        assert len(result.construct_mappings) == 1

    def test_complex_translation(self):
        sql = """
        SELECT TOP 10 %SQLUPPER(name), JSON_EXTRACT(data, '$.field')
        FROM users
        WHERE JSON_EXISTS(data, '$.active')
        """
        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)

        assert result.translated_sql is not None
        assert result.performance_stats.constructs_translated > 0
```

### Integration Tests

```python
import pytest
from iris_pgwire.sql_translator.api import create_translation_api
from fastapi.testclient import TestClient

class TestTranslationAPI:
    def setup_method(self):
        app = create_translation_api()
        self.client = TestClient(app)

    def test_translation_endpoint(self):
        response = self.client.post("/translate", json={
            "sql": "SELECT %SQLUPPER(name) FROM users"
        })

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "UPPER" in data["translated_sql"]

    def test_health_endpoint(self):
        response = self.client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] in ["healthy", "degraded"]
```

### Performance Tests

```python
import time
import pytest
from iris_pgwire.sql_translator.translator import IRISSQLTranslator, TranslationContext

class TestPerformance:
    def setup_method(self):
        self.translator = IRISSQLTranslator()

    def test_sla_compliance(self):
        """Test constitutional 5ms SLA compliance"""
        sql = "SELECT %SQLUPPER(name) FROM users"
        context = TranslationContext(original_sql=sql)

        start_time = time.perf_counter()
        result = self.translator.translate(context)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert elapsed_ms < 5.0  # Constitutional SLA
        assert result.performance_stats.is_sla_compliant

    def test_bulk_performance(self):
        """Test performance under load"""
        queries = [f"SELECT * FROM table_{i}" for i in range(100)]

        start_time = time.perf_counter()
        for sql in queries:
            context = TranslationContext(original_sql=sql)
            self.translator.translate(context)
        total_time = (time.perf_counter() - start_time) * 1000

        avg_time = total_time / len(queries)
        assert avg_time < 2.0  # Average should be well under SLA
```

## Monitoring and Observability

### Metrics Collection

```python
from iris_pgwire.sql_translator.metrics import get_metrics_collector

collector = get_metrics_collector()

# Custom metrics
collector.increment_counter("custom.translations", labels={"type": "function"})
collector.record_histogram("custom.confidence", 0.95, labels={"construct": "function"})
collector.set_gauge("custom.cache_size", 1500)
```

### Logging

```python
import logging
from iris_pgwire.sql_translator.logging_config import setup_logging

# Setup structured logging
setup_logging(level="INFO", format="structured")

logger = logging.getLogger("custom.component")
logger.info("Translation completed", extra={
    "sql_length": 150,
    "constructs_found": 3,
    "translation_time_ms": 2.3,
    "confidence": 0.95
})
```

### Health Checks

```python
from iris_pgwire.sql_translator.api import create_translation_api

app = create_translation_api()

@app.get("/custom/health")
async def custom_health_check():
    """Custom health check with business logic"""
    translator_stats = get_translator().get_translation_stats()

    # Custom health criteria
    health_score = 100
    if translator_stats['sla_compliance_rate'] < 0.95:
        health_score -= 30
    if translator_stats['cache_hit_rate'] < 0.7:
        health_score -= 20

    status = "healthy" if health_score >= 80 else "degraded"

    return {
        "status": status,
        "health_score": health_score,
        "translator_stats": translator_stats
    }
```

## Deployment

### Docker Container

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/
COPY docs/ ./docs/

# Set environment
ENV PYTHONPATH=/app/src
ENV IRIS_TRANSLATION_CACHE_SIZE=10000
ENV IRIS_API_PORT=8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start API
CMD ["python", "-m", "uvicorn", "iris_pgwire.sql_translator.api:create_translation_api", "--host", "0.0.0.0", "--port", "8000"]
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: iris-sql-translator
spec:
  replicas: 3
  selector:
    matchLabels:
      app: iris-sql-translator
  template:
    metadata:
      labels:
        app: iris-sql-translator
    spec:
      containers:
      - name: translator
        image: iris-sql-translator:latest
        ports:
        - containerPort: 8000
        env:
        - name: IRIS_TRANSLATION_CACHE_SIZE
          value: "10000"
        - name: IRIS_API_WORKERS
          value: "1"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
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
  name: iris-sql-translator-service
spec:
  selector:
    app: iris-sql-translator
  ports:
  - protocol: TCP
    port: 80
    targetPort: 8000
  type: ClusterIP
```

## Performance Optimization

### 1. Caching Strategies

```python
# Optimize cache for your workload
translator = IRISSQLTranslator(
    enable_caching=True,
    max_cache_size=50000,  # Larger cache for high-volume workloads
)

# Custom cache warmup
def warmup_cache(common_queries):
    """Warm up cache with common queries"""
    for sql in common_queries:
        context = TranslationContext(original_sql=sql)
        translator.translate(context)
```

### 2. Connection Pooling

```python
from concurrent.futures import ThreadPoolExecutor

class PooledTranslator:
    def __init__(self, pool_size=10):
        self.pool = ThreadPoolExecutor(max_workers=pool_size)
        self.translator = IRISSQLTranslator()

    async def translate_async(self, sql):
        """Async translation using thread pool"""
        import asyncio
        loop = asyncio.get_event_loop()
        context = TranslationContext(original_sql=sql)
        return await loop.run_in_executor(
            self.pool,
            self.translator.translate,
            context
        )
```

### 3. Memory Optimization

```python
# Configure for memory-constrained environments
translator = IRISSQLTranslator(
    enable_caching=True,
    max_cache_size=1000,  # Smaller cache
    enable_validation=False,  # Disable validation if not needed
    enable_debug=False  # Disable debug tracing
)
```

## Troubleshooting

### Common Issues

1. **SLA Violations**: Check query complexity and cache hit rates
2. **Low Confidence**: Review construct mappings and validation rules
3. **Memory Issues**: Adjust cache size and monitor memory usage
4. **API Timeouts**: Increase timeout values and check system load

### Debug Mode

```python
# Enable comprehensive debugging
translator = IRISSQLTranslator(enable_debug=True)
context = TranslationContext(
    original_sql="SELECT %CUSTOM_FUNCTION(data) FROM table",
    enable_debug=True
)

result = translator.translate(context)

# Examine debug trace
if result.debug_trace:
    for step in result.debug_trace.parsing_steps:
        print(f"Step: {step.step_name}, Duration: {step.duration_ms}ms")

    for decision in result.debug_trace.mapping_decisions:
        print(f"Construct: {decision.construct}")
        print(f"Chosen: {decision.chosen_mapping}")
        print(f"Confidence: {decision.confidence}")
```

### Performance Profiling

```python
import cProfile
import pstats

def profile_translation(sql):
    """Profile translation performance"""
    translator = IRISSQLTranslator()

    def translate():
        context = TranslationContext(original_sql=sql)
        return translator.translate(context)

    # Profile execution
    profiler = cProfile.Profile()
    profiler.enable()
    result = translate()
    profiler.disable()

    # Analyze results
    stats = pstats.Stats(profiler)
    stats.sort_stats('cumulative')
    stats.print_stats(10)  # Top 10 functions

    return result
```

## Best Practices

### 1. Error Handling

```python
from iris_pgwire.sql_translator.models import TranslationError, UnsupportedConstructError

try:
    context = TranslationContext(original_sql=sql)
    result = translator.translate(context)
except UnsupportedConstructError as e:
    logger.warning(f"Unsupported construct: {e.construct}")
    # Handle gracefully - perhaps use original SQL
except TranslationError as e:
    logger.error(f"Translation failed: {e.message}")
    # Handle error appropriately
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    # Handle unexpected errors
```

### 2. Resource Management

```python
# Use context managers for resource cleanup
with translator.translation_session("session_123") as session_id:
    for sql in batch_queries:
        context = TranslationContext(
            original_sql=sql,
            session_id=session_id
        )
        result = translator.translate(context)
        process_result(result)
```

### 3. Configuration Management

```python
# Use configuration classes for better organization
from dataclasses import dataclass

@dataclass
class TranslationSettings:
    cache_enabled: bool = True
    cache_size: int = 10000
    validation_enabled: bool = True
    debug_enabled: bool = False
    sla_requirement_ms: float = 5.0

def create_configured_translator(settings: TranslationSettings):
    return IRISSQLTranslator(
        enable_caching=settings.cache_enabled,
        max_cache_size=settings.cache_size,
        enable_validation=settings.validation_enabled,
        enable_debug=settings.debug_enabled
    )
```

This developer guide provides comprehensive information for working with the IRIS SQL Translation System. For specific implementation details, refer to the individual component documentation and API references.