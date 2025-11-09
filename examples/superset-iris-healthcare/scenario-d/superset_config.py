# Scenario D: Superset Configuration
# Native IRIS Driver for Both Metadata and Data
#
# This configuration demonstrates:
# - Metadata stored in IRIS SUPERSET_META namespace (native driver)
# - Data sources in IRIS USER namespace (native driver)
# - Pure IRIS deployment (no PostgreSQL, no PGWire)
# - Optimal performance (zero protocol overhead)

import os

# Flask App Config
SECRET_KEY = os.getenv('SUPERSET_SECRET_KEY', 'superset_secret_key_scenario_d')

# CRITICAL: Metadata stored in IRIS via native driver
# This tests IRIS SQL compatibility with Superset metadata requirements
SQLALCHEMY_DATABASE_URI = 'iris://_SYSTEM:SYS@iris:1972/SUPERSET_META'

# Redis Configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'redis-scenario-d')
REDIS_PORT = os.getenv('REDIS_PORT', 6379)

class CeleryConfig:
    broker_url = f'redis://{REDIS_HOST}:{REDIS_PORT}/0'
    result_backend = f'redis://{REDIS_HOST}:{REDIS_PORT}/0'

CELERY_CONFIG = CeleryConfig

# Feature Flags
FEATURE_FLAGS = {
    'ENABLE_TEMPLATE_PROCESSING': True,
    'DASHBOARD_NATIVE_FILTERS': True,
    'DASHBOARD_CROSS_FILTERS': True,
    'VERSIONED_EXPORT': True,
}

# Security
WTF_CSRF_ENABLED = True
WTF_CSRF_EXEMPT_LIST = []
WTF_CSRF_TIME_LIMIT = None

# Cache Configuration
CACHE_CONFIG = {
    'CACHE_TYPE': 'RedisCache',
    'CACHE_DEFAULT_TIMEOUT': 3600,
    'CACHE_KEY_PREFIX': 'superset_scenario_d_',
    'CACHE_REDIS_HOST': REDIS_HOST,
    'CACHE_REDIS_PORT': REDIS_PORT,
    'CACHE_REDIS_DB': 1,
}

DATA_CACHE_CONFIG = {
    'CACHE_TYPE': 'RedisCache',
    'CACHE_DEFAULT_TIMEOUT': 3600,
    'CACHE_KEY_PREFIX': 'superset_scenario_d_data_',
    'CACHE_REDIS_HOST': REDIS_HOST,
    'CACHE_REDIS_PORT': REDIS_PORT,
    'CACHE_REDIS_DB': 2,
}

# Logging
LOG_LEVEL = 'INFO'
ENABLE_TIME_ROTATE = False

# SQL Lab Configuration
SQLLAB_TIMEOUT = 300
SQLLAB_DEFAULT_DBID = None
SQLALCHEMY_POOL_SIZE = 5
SQLALCHEMY_POOL_TIMEOUT = 300
SQLALCHEMY_MAX_OVERFLOW = 10
SQLALCHEMY_POOL_RECYCLE = 3600

# SQLAlchemy Engine Options
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_pre_ping': True,  # Verify connections before use
    'echo': False,  # Set to True for SQL debugging
}

# Row Limits
ROW_LIMIT = 50000
SQL_MAX_ROW = 100000

# Webserver Configuration
SUPERSET_WEBSERVER_PROTOCOL = 'http'
SUPERSET_WEBSERVER_ADDRESS = '0.0.0.0'
SUPERSET_WEBSERVER_PORT = 8088
SUPERSET_WEBSERVER_TIMEOUT = 120

# Enable CORS if needed
ENABLE_CORS = False

# Scenario D Specific Configuration
SCENARIO_NAME = "D"
SCENARIO_DESCRIPTION = "Native IRIS for Metadata + Data (Pure IRIS)"
METADATA_BACKEND = "IRIS SUPERSET_META (native driver)"
DATA_SOURCE_BACKEND = "IRIS USER (native driver)"

# Performance & Compatibility Notes
PERFORMANCE_NOTES = """
Scenario D Performance Characteristics:
- Zero PGWire translation overhead (~4ms saved vs Scenario A/C)
- Direct IRIS connection maximizes throughput
- Native IRIS features fully accessible (VECTOR, etc.)
- Optimal for IRIS-centric deployments
"""

COMPATIBILITY_NOTES = """
Scenario D Compatibility Requirements:
- IRIS SQL must support Superset metadata schema (complex DDL)
- sqlalchemy-intersystems-iris driver must be mature/complete
- May encounter IRIS/PostgreSQL SQL dialect differences
- No PostgreSQL compatibility layer (unlike PGWire scenarios)
- Higher risk than Scenarios A or B
"""
