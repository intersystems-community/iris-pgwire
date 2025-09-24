# IRIS IntegratedML Compatibility Analysis

## Executive Summary

Testing reveals that **IRIS IntegratedML features have limited compatibility** through the PostgreSQL wire protocol due to their reliance on IRIS-specific SQL extensions and system functions that are not part of standard PostgreSQL.

## Test Results

### ✅ **Working: Standard SQL Operations**
- Table creation and data insertion
- Standard vector operations (`TO_VECTOR`, `VECTOR_COSINE`)
- Basic IRIS SQL queries
- Transaction support (BEGIN/COMMIT)

### ❌ **Not Working: IntegratedML Specific Features**
- `%SYSTEM.ML.*` system functions
- `CREATE MODEL` with IRIS-specific syntax
- `TRAIN MODEL` commands
- `SELECT PREDICT()` function calls
- IntegratedML metadata access

## Detailed Analysis

### Why IntegratedML Doesn't Work via PostgreSQL Wire Protocol

1. **IRIS-Specific SQL Extensions**
   ```sql
   -- These are IRIS extensions, not PostgreSQL standard
   CREATE MODEL MyModel PREDICTING (target) FROM MyTable
   TRAIN MODEL MyModel FROM MyTable
   SELECT PREDICT(MyModel) FROM MyTable
   ```

2. **System Function Dependencies**
   ```sql
   -- IRIS system functions not available via PGWire
   SELECT %SYSTEM.ML.%ModelExists('ModelName')
   SELECT %SYSTEM.ML.%GetModelList()
   ```

3. **ObjectScript Integration**
   - IntegratedML relies on ObjectScript classes and methods
   - These are not accessible through SQL-only interfaces
   - Requires native IRIS drivers for full functionality

## IRIS 2025.2 Custom Models Capability

Based on the `/Users/tdyar/ws/pluggable_iml` project, **IRIS 2025.2 introduces powerful custom model capabilities**:

### New Features in IRIS 2025.2
```sql
-- Advanced custom model syntax
CREATE OR REPLACE MODEL SalesForecast.HybridForecasting
PREDICTING (SalesAmount)
FROM SalesForecast.ForecastingView
USING {
    "path_to_regressors": "/opt/iris/mgr/python/custom_models/regressors",
    "model_name": "HybridForecastingModel",
    "isc_models_disabled": 1,
    "user_params": {
        "prophet_config": {
            "seasonality_mode": "multiplicative",
            "yearly_seasonality": true,
            "weekly_seasonality": true
        },
        "lightgbm_config": {
            "objective": "regression",
            "num_leaves": 31,
            "learning_rate": 0.05
        }
    }
}
```

### Production ML Workflows
- **Custom Python Models**: Deploy scikit-learn compatible models
- **Hybrid Architectures**: Combine Prophet + LightGBM
- **Real-time Scoring**: Sub-50ms prediction latency
- **Batch Processing**: Automated forecasting pipelines
- **Performance Monitoring**: Automated retraining triggers

## Recommendations

### For IntegratedML Usage

#### ✅ **Use Native IRIS Drivers**
```python
# For IntegratedML, use native IRIS Python driver
import iris

conn = iris.connect(hostname='127.0.0.1', port=1972,
                   namespace='USER', username='SuperUser', password='SYS')

cursor = conn.cursor()
cursor.execute("CREATE MODEL MyModel PREDICTING (target) FROM MyTable")
cursor.execute("TRAIN MODEL MyModel")
cursor.execute("SELECT PREDICT(MyModel) as prediction FROM TestData")
```

#### ⚠️ **Limited PostgreSQL Wire Protocol Support**
```python
# Via PGWire: Only standard SQL + vectors work
import psycopg

conn = psycopg.connect(host='127.0.0.1', port=5432, user='test_user', dbname='USER')
cursor = conn.cursor()
cursor.execute("SELECT TO_VECTOR('[1,2,3]') as vector")  # ✅ Works
cursor.execute("SELECT VECTOR_COSINE(v1, v2) FROM vectors")  # ✅ Works
cursor.execute("CREATE MODEL MyModel PREDICTING (target) FROM MyTable")  # ❌ Fails
```

### Hybrid Architecture Strategy

#### **Best Practice: Dual-Protocol Approach**

1. **PostgreSQL Wire Protocol**: For data access, vectors, standard SQL
   - BI tools, ETL platforms, data science frameworks
   - pandas, SQLAlchemy, asyncpg, psycopg
   - Vector similarity search, bulk data operations

2. **Native IRIS Drivers**: For IntegratedML, advanced features
   - Model training and deployment
   - IRIS-specific functionality
   - ObjectScript integration

#### **Example Hybrid Implementation**
```python
import psycopg  # For data access via PostgreSQL wire protocol
import iris     # For IntegratedML via native drivers

# Data access via PostgreSQL (ecosystem compatibility)
pg_conn = psycopg.connect(host='127.0.0.1', port=5432, user='test_user', dbname='USER')
df = pd.read_sql("SELECT * FROM vectors WHERE similarity > 0.8", pg_conn)

# ML operations via native IRIS
iris_conn = iris.connect(hostname='127.0.0.1', port=1972, namespace='USER')
iris_cursor = iris_conn.cursor()
iris_cursor.execute("TRAIN MODEL MyModel FROM training_data")
iris_cursor.execute("SELECT PREDICT(MyModel) FROM new_data")
```

## Future Opportunities

### Potential Enhancements

1. **SQL Function Mapping**
   - Map IRIS ML functions to PostgreSQL equivalents
   - Translate `PREDICT()` calls to native IRIS execution
   - Implement ML metadata functions

2. **Custom PostgreSQL Extensions**
   - Create pgvector-style extension for IRIS ML
   - Implement `predict()` function in PostgreSQL syntax
   - Bridge to native IRIS ML capabilities

3. **IRIS 2025.2 Integration**
   - Test custom model compatibility via PGWire
   - Explore Python model deployment patterns
   - Investigate JSON configuration support

## Conclusion

**IntegratedML requires native IRIS drivers** for full functionality. The PostgreSQL wire protocol is excellent for:

✅ **Data Access & Analytics**
- Standard SQL queries
- Vector operations
- BI tool connectivity
- ETL pipeline integration
- Async Python frameworks

❌ **Machine Learning Operations**
- Model training/deployment
- IRIS-specific ML functions
- ObjectScript integration

**Recommendation**: Use **hybrid architecture** - PostgreSQL wire protocol for data access and ecosystem compatibility, native IRIS drivers for IntegratedML capabilities.

---

## IRIS 2025.2 Custom Models Potential

The **pluggable_iml** project shows exciting possibilities for IRIS 2025.2:

- **Production ML Workflows** with custom Python models
- **Hybrid Forecasting** (Prophet + LightGBM)
- **Real-time Scoring** with sub-50ms latency
- **Automated Retraining** and performance monitoring

These capabilities represent a **major advancement** in IRIS ML capabilities, though they will likely remain accessible primarily through native drivers rather than PostgreSQL wire protocol.