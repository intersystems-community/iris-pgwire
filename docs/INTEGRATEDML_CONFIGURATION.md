# IntegratedML Configuration and Provider Guide

## Executive Summary

This guide provides comprehensive configuration information for IntegratedML providers in IRIS 2025.2, enabling full machine learning capabilities through the PostgreSQL wire protocol. Based on official InterSystems documentation and verified testing.

## Installation Requirements

### Critical Package Installation
```bash
# Install AutoML provider (REQUIRED for IntegratedML to work)
docker exec iris-pgwire bash -c "python3 -m pip install --index-url https://registry.intersystems.com/pypi/simple --no-cache-dir --target /usr/irissys/mgr/python intersystems-iris-automl"

# Optional: TensorFlow-enhanced version
docker exec iris-pgwire bash -c "python3 -m pip install --index-url https://registry.intersystems.com/pypi/simple --no-cache-dir --target /usr/irissys/mgr/python intersystems-iris-automl-tf"

# Set proper permissions
docker exec iris-pgwire bash -c "chown -R irisowner:irisowner /usr/irissys/mgr/python/"
```

### Enable IntegratedML in IRIS
```objectscript
# In IRIS terminal
ZN "USER"
SET ^%SYS("SQLML") = 1
```

## AutoML Provider (Default)

AutoML is the system-default ML configuration (%AutoML) and provides automated machine learning developed by InterSystems.

### Key Features
- **Automated Model Selection**: Automatically chooses best algorithm
- **Feature Engineering**: Column type classification, feature elimination, one-hot encoding
- **Natural Language Processing**: Basic NLP for unstructured text features
- **Missing Value Handling**: Fills in missing or null values
- **Time Feature Creation**: Generates time-based insights (hours/days/months/years)

### Training Parameters

Use training parameters with the USING clause:

```sql
-- Basic training with seed for reproducibility
TRAIN MODEL my-model USING {"seed": 3}

-- Full parameter example
TRAIN MODEL SalesModel USING {
    "seed": 42,
    "verbosity": 2,
    "TrainMode": "BALANCE",
    "MaxTime": 60,
    "MinimumDesiredScore": 0.8,
    "IsRegression": 0
}
```

#### Available Parameters

| Parameter | Description | Default | Options |
|-----------|-------------|---------|---------|
| `seed` | Random number generator seed for reproducibility | None | Any integer |
| `verbosity` | Output verbosity level | 2 | 0 (minimal), 1 (moderate), 2 (full) |
| `TrainMode` | Model selection metric | "SCORE" | "TIME", "BALANCE", "SCORE" |
| `MaxTime` | Minutes allocated for training runs | 14400 | Any positive integer |
| `MinimumDesiredScore` | Minimum acceptable score (0-1) | 0 | 0.0 to 1.0 |
| `IsRegression` | Force regression (1) or classification (0) | Auto-detect | 0, 1, or omit |

### Model Selection Process

**For Classification Models:**
1. Dataset size evaluation (sampling if too large)
2. Binary vs multi-class detection
3. Monte Carlo cross-validation for best model selection
4. Training on full dataset

**For Regression Models:**
- Singular optimized process for regression model development

### Performance Modes

- **TIME Mode**: Prioritizes faster training time
- **BALANCE Mode**: Equal weighting of score and training time
- **SCORE Mode**: Optimizes purely for accuracy (default)

## H2O Provider

Alternative provider using H2O AutoML framework.

### Configuration
```sql
-- Set H2O as default provider
SET ML CONFIGURATION %H2O

-- Or create custom H2O configuration
CREATE ML CONFIGURATION my_h2o_config PROVIDER H2O
```

### Training Parameters
```sql
-- Force regression model
TRAIN MODEL h2o-model USING {"model_type": "regression"}

-- With additional H2O parameters
TRAIN MODEL h2o-model USING {
    "seed": 42,
    "max_models": 10,
    "max_runtime_secs": 3600
}
```

### Known Limitations
- Default `max_models` is set to 5
- Seed parameter may not guarantee reproducible results due to early stopping
- May require JVM argument adjustments for connectivity issues

## DataRobot Provider

Enterprise provider requiring business relationship with DataRobot.

### Configuration
```sql
SET ML CONFIGURATION datarobot_configuration
```

### Training Parameters
- Uses DataRobot API for HTTP-based training
- Default `quickrun` parameter set to true
- Consult DataRobot documentation for parameter details

## PMML Provider

Import and execute pre-trained PMML models.

### Configuration
```sql
SET ML CONFIGURATION %PMML
```

### Import Methods
```sql
-- By file path
TRAIN MODEL HousePriceModel FROM HouseData USING {
    "file_name": "C:\\PMML\\pmml_house_model.xml"
}

-- By class name
TRAIN MODEL HousePriceModel FROM HouseData USING {
    "class_name": "IntegratedML.pmml.PMMLHouseModel"
}

-- Multiple models in file
TRAIN MODEL my_pmml_model FROM data USING {
    "class_name": "my_pmml_file",
    "model_name": "model_2_name"
}
```

## Complete IntegratedML Workflow

### 1. Basic Model Creation and Training
```sql
-- Create table with training data
CREATE TABLE SalesData (
    id INT,
    region VARCHAR(50),
    product_category VARCHAR(50),
    sales_amount DECIMAL(10,2),
    customer_age INT,
    season VARCHAR(20),
    target_revenue DECIMAL(10,2)
);

-- Create model
CREATE MODEL SalesPredictor
PREDICTING (target_revenue)
FROM SalesData;

-- Train with AutoML provider
TRAIN MODEL SalesPredictor USING {
    "seed": 42,
    "verbosity": 1,
    "TrainMode": "BALANCE"
};
```

### 2. Advanced Model with Custom Configuration
```sql
-- Create custom ML configuration
CREATE ML CONFIGURATION CustomAutoML
PROVIDER AutoML
USING {
    "default_seed": 123,
    "default_verbosity": 2
};

-- Set as default
SET ML CONFIGURATION CustomAutoML;

-- Create model with specific features
CREATE MODEL AdvancedPredictor
PREDICTING (target_revenue)
WITH (
    region VARCHAR(50),
    product_category VARCHAR(50),
    sales_amount DECIMAL(10,2),
    customer_age INT,
    season VARCHAR(20)
)
FROM SalesData;

-- Train with advanced parameters
TRAIN MODEL AdvancedPredictor USING {
    "TrainMode": "SCORE",
    "MinimumDesiredScore": 0.85,
    "MaxTime": 120
};
```

### 3. Predictions and Model Management
```sql
-- Make predictions
SELECT id, region, target_revenue,
       PREDICT(SalesPredictor) as predicted_revenue,
       PREDICT(SalesPredictor, 'probability') as confidence
FROM SalesData
WHERE id <= 10;

-- Validate model performance
VALIDATE MODEL SalesPredictor FROM SalesData;

-- Check model metadata
SELECT MODEL_NAME, MODEL_TYPE, TRAINING_DATE, ACCURACY
FROM INFORMATION_SCHEMA.ML_MODELS
WHERE MODEL_NAME = 'SalesPredictor';

-- View training runs
SELECT RUN_ID, STATUS, TRAINING_TIME, LOG
FROM INFORMATION_SCHEMA.ML_TRAINING_RUNS
WHERE MODEL_NAME = 'SalesPredictor';
```

## PostgreSQL Wire Protocol Integration

### Enhanced Command Routing
Our PostgreSQL wire protocol implementation automatically detects and routes IntegratedML commands:

```python
# Automatic detection of IntegratedML commands
INTEGRATEDML_PATTERNS = {
    'create_model': r'CREATE\s+(?:OR\s+REPLACE\s+)?MODEL\s+(\w+)',
    'train_model': r'TRAIN\s+MODEL\s+(\w+)',
    'predict_function': r'PREDICT\s*\(\s*([^)]+)\s*\)',
    'validate_model': r'VALIDATE\s+MODEL\s+(\w+)',
    'drop_model': r'DROP\s+MODEL\s+(\w+)'
}
```

### System Function Translation
```python
IRIS_SYSTEM_FUNCTIONS = {
    '%SYSTEM.ML.%ModelExists': 'iris_ml_model_exists',
    '%SYSTEM.ML.%GetModelList': 'iris_ml_get_model_list',
    '%SYSTEM.ML.%GetModelMetrics': 'iris_ml_get_model_metrics'
}
```

## Platform Support and Requirements

### Supported Platforms
- ✅ Linux x86_64
- ✅ Windows x86_64
- ✅ macOS x86_64
- ❌ IBM AIX
- ❌ Red Hat Enterprise Linux 8 for ARM
- ❌ Ubuntu 20.04/24.04 for ARM

### Requirements
- **Python Version**: 3.11 or later (3.11 required on Windows)
- **pip Version**: 20.3 or later
- **IRIS Version**: 2025.2 with IntegratedML enabled

### Python Path Configuration
If experiencing package isolation issues:
```python
# In IRIS Python shell
import sys
sys.path.append("<path to instance>\\lib\\automl")
```

## Troubleshooting

### Common Issues

1. **"ML Provider 'AutoML' is not available"**
   - Solution: Install `intersystems-iris-automl` package
   - Verify: `python3 -c "import iris_automl; print('AutoML installed')"`

2. **"Model's Provider is unavailable"**
   - Solution: Enable IntegratedML with `SET ^%SYS("SQLML") = 1`
   - Restart IRIS instance after enabling

3. **H2O Connectivity Issues**
   - Add JVM arguments: `-Djava.net.preferIPv6Addresses=true -Djava.net.preferIPv4Addresses=false`
   - Configure in Management Portal → System Administration → External Language Servers

4. **pip Version Issues**
   - Update pip: `pip install --upgrade pip`
   - Verify version: `pip --version` (should be 20.3+)

### Verification Commands
```sql
-- Test AutoML provider availability
CREATE MODEL TestModel PREDICTING (target) FROM test_table;
TRAIN MODEL TestModel;
SELECT PREDICT(TestModel) FROM test_table LIMIT 1;

-- Check system configuration
SELECT %SYSTEM.Version.%GetNumber() as iris_version;
SELECT %SYSTEM.ML.%ModelExists('TestModel') as model_exists;
```

## Performance Optimization

### Training Performance Tips
1. **Use appropriate TrainMode** for your use case
2. **Set reasonable MaxTime** limits
3. **Enable verbosity=1** for monitoring without excessive logging
4. **Use seed parameter** for reproducible results during development

### Memory Considerations
- Large datasets are automatically sampled during model selection
- Full dataset used for final training
- Monitor memory usage with complex feature engineering

## Integration with PostgreSQL Ecosystem

### Through Our Wire Protocol
```python
# Standard PostgreSQL tools now work with IntegratedML
import asyncpg

async def train_model_via_pgwire():
    conn = await asyncpg.connect(
        host='127.0.0.1',
        port=5432,
        user='test_user',
        database='USER'
    )

    # IntegratedML commands work seamlessly
    await conn.execute("""
        CREATE MODEL PGWireModel
        PREDICTING (target)
        FROM training_data
    """)

    await conn.execute("TRAIN MODEL PGWireModel")

    result = await conn.fetch("""
        SELECT id, PREDICT(PGWireModel) as prediction
        FROM test_data
    """)

    await conn.close()
    return result
```

## Conclusion

IntegratedML in IRIS 2025.2 provides enterprise-grade machine learning capabilities with multiple provider options. The AutoML provider offers the best balance of ease-of-use and performance for most applications, while H2O, DataRobot, and PMML providers enable specialized workflows.

Our PostgreSQL wire protocol implementation makes these capabilities accessible to the entire PostgreSQL ecosystem, enabling:
- **BI Tools**: Tableau, Power BI, QlikView with ML predictions
- **Data Science**: Jupyter notebooks, pandas, scikit-learn integration
- **ETL Platforms**: Apache Airflow, dbt with ML-enhanced data pipelines
- **Applications**: FastAPI, Django, Rails with native async ML queries

**Result**: IRIS becomes the most capable AI/ML database with PostgreSQL ecosystem compatibility.