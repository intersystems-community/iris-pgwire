# Scenario B: Superset Configuration
# PostgreSQL Metadata + Native IRIS Data Source
#
# This configuration demonstrates:
# - Metadata stored in PostgreSQL (proven stability)
# - Data sources using native IRIS driver (iris:// URI)
# - Direct IRIS connection on port 1972 (no PGWire)

import os

# Flask App Config
SECRET_KEY = os.getenv('SUPERSET_SECRET_KEY', 'superset_secret_key_scenario_b')
SQLALCHEMY_DATABASE_URI = 'postgresql://superset:superset@postgres-scenario-b:5432/superset'

# Redis Configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'redis-scenario-b')
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
    'CACHE_KEY_PREFIX': 'superset_scenario_b_',
    'CACHE_REDIS_HOST': REDIS_HOST,
    'CACHE_REDIS_PORT': REDIS_PORT,
    'CACHE_REDIS_DB': 1,
}

DATA_CACHE_CONFIG = {
    'CACHE_TYPE': 'RedisCache',
    'CACHE_DEFAULT_TIMEOUT': 3600,
    'CACHE_KEY_PREFIX': 'superset_scenario_b_data_',
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

# Scenario B Specific Configuration
SCENARIO_NAME = "B"
SCENARIO_DESCRIPTION = "PostgreSQL Metadata + Native IRIS Data Source (iris://)"
METADATA_BACKEND = "PostgreSQL"
DATA_SOURCE_BACKEND = "IRIS Native Driver"
