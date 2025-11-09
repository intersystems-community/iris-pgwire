# Scenario C: Superset Configuration
# IRIS via PGWire for Both Metadata and Data
#
# This configuration demonstrates:
# - Metadata stored in IRIS SUPERSET_META namespace (via PGWire)
# - Data sources in IRIS USER namespace (via PGWire)
# - Single database system (IRIS for everything)
# - STRESS TEST for PGWire PostgreSQL compatibility

import os

# Flask App Config
SECRET_KEY = os.getenv('SUPERSET_SECRET_KEY', 'superset_secret_key_scenario_c')

# CRITICAL: Metadata stored in IRIS via PGWire
# This tests PGWire's ability to handle complex ORM operations
SQLALCHEMY_DATABASE_URI = 'postgresql://superset_user@iris:5432/SUPERSET_META'

# Redis Configuration
REDIS_HOST = os.getenv('REDIS_HOST', 'redis-scenario-c')
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
    'CACHE_KEY_PREFIX': 'superset_scenario_c_',
    'CACHE_REDIS_HOST': REDIS_HOST,
    'CACHE_REDIS_PORT': REDIS_PORT,
    'CACHE_REDIS_DB': 1,
}

DATA_CACHE_CONFIG = {
    'CACHE_TYPE': 'RedisCache',
    'CACHE_DEFAULT_TIMEOUT': 3600,
    'CACHE_KEY_PREFIX': 'superset_scenario_c_data_',
    'CACHE_REDIS_HOST': REDIS_HOST,
    'CACHE_REDIS_PORT': REDIS_PORT,
    'CACHE_REDIS_DB': 2,
}

# Logging - More verbose for PGWire compatibility debugging
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
# May need tuning for IRIS/PGWire compatibility
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

# Scenario C Specific Configuration
SCENARIO_NAME = "C"
SCENARIO_DESCRIPTION = "IRIS via PGWire for Metadata + Data (All-IRIS)"
METADATA_BACKEND = "IRIS SUPERSET_META (via PGWire)"
DATA_SOURCE_BACKEND = "IRIS USER (via PGWire)"

# Compatibility Notes
COMPATIBILITY_NOTES = """
Scenario C Tests PGWire Compatibility:
- Metadata operations use SQLAlchemy ORM (CREATE TABLE, ALTER, indexes)
- Requires full PostgreSQL DDL support through PGWire
- May expose IRIS/PostgreSQL compatibility gaps
- INFORMATION_SCHEMA queries must work correctly
- Transaction management critical for metadata integrity
"""
