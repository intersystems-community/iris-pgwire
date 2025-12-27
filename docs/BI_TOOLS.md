# BI Tools Integration: Connect Any BI Platform to IRIS

**Last Updated**: 2025-12-27
**Related**: [Client Recommendations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/CLIENT_RECOMMENDATIONS.md), [Performance](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PERFORMANCE.md)

---

## Overview

Connect **any PostgreSQL-compatible BI tool** to InterSystems IRIS without custom drivers or plugins. All tools use standard PostgreSQL connections - no IRIS-specific configuration required.

**Zero-Configuration Promise**: If it connects to PostgreSQL, it connects to IRIS via PGWire.

---

## Quick Start

### Standard PostgreSQL Connection

**All BI tools use these same connection parameters**:

```yaml
Host:     localhost          # PGWire server hostname
Port:     5432               # PostgreSQL wire protocol port
Database: USER               # IRIS namespace
Username: _SYSTEM            # IRIS username
Password: SYS                # IRIS password
Driver:   PostgreSQL (standard)  # Use built-in PostgreSQL driver
```

**That's it!** No IRIS-specific plugins, no custom drivers, no configuration files.

---

## Supported BI Tools

### Apache Superset

**Description**: Modern data exploration and visualization platform with Python integration.

**Quick Start**:
```bash
docker-compose --profile bi-tools up superset
# Access: http://localhost:8088
# Login: admin / admin
```

**Connection Setup**:
1. Click "+" → "Database Connections"
2. Select "PostgreSQL"
3. Enter connection details (see above)
4. Click "Test Connection"
5. Save

**Try the Healthcare Demo**: Complete working example with 250 patient records and 400 lab results - see [Superset Healthcare Example](https://github.com/intersystems-community/iris-pgwire/blob/main/examples/superset-iris-healthcare/README.md) for <10 minute setup.

**Features**:
- SQL Lab for ad-hoc queries
- Chart builder with 40+ visualization types
- Dashboard creation and sharing
- Row-level security
- **Vector Analytics**: Run IRIS VECTOR_COSINE queries directly in SQL Lab

**Example Query**:
```sql
-- Semantic search in Superset SQL Lab
SELECT id, title,
       VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3,...]', DOUBLE)) AS similarity
FROM documents
ORDER BY similarity DESC
LIMIT 10
```

### Metabase

**Description**: User-friendly business intelligence tool with visual query builder - no SQL required.

**Quick Start**:
```bash
docker-compose --profile bi-tools up metabase
# Access: http://localhost:3001
# First-run setup wizard will prompt for database connection
```

**Connection Setup**:
1. Select "PostgreSQL" during setup wizard
2. Enter connection details
3. Metabase will scan schema automatically
4. Start creating questions and dashboards

**Features**:
- Visual query builder (no SQL required)
- Automatic dashboard suggestions
- Email/Slack alerts
- Embedded analytics
- **Filters**: ORM-introspected schema enables smart filters

**Best For**: Non-technical users, quick dashboard creation, automated reports.

### Grafana

**Description**: Real-time monitoring and time-series visualization platform.

**Quick Start**:
```bash
docker-compose up grafana
# Access: http://localhost:3000
# Login: admin / admin
```

**Connection Setup**:
1. Configuration → Data Sources → Add data source
2. Select "PostgreSQL"
3. Enter connection details
4. Enable "TimescaleDB" feature (optional, for time-series functions)
5. Save & Test

**Features**:
- Time-series dashboards
- Alerting and notifications
- Variable templating
- Prometheus integration
- **IRIS IntegratedML**: Query ML predictions in real-time

**Example Query**:
```sql
-- Real-time metrics dashboard
SELECT
  $__timeGroup(timestamp, '5m') as time,
  AVG(value) as avg_value,
  MAX(value) as max_value
FROM metrics
WHERE $__timeFilter(timestamp)
GROUP BY time
ORDER BY time
```

### Tableau

**Description**: Enterprise analytics and data visualization platform.

**Connection Setup**:
1. Connect → To a Server → PostgreSQL
2. Enter connection details
3. Select database and tables
4. Drag and drop to create visualizations

**Features**:
- Drag-and-drop interface
- Advanced analytics (forecasting, clustering)
- Tableau Server for enterprise deployment
- Mobile apps
- **Live Connections**: Real-time IRIS data without extracts

**Best For**: Enterprise deployments, executive dashboards, advanced analytics.

### Power BI

**Description**: Microsoft business analytics service - part of Microsoft 365 ecosystem.

**Connection Setup**:
1. Get Data → Database → PostgreSQL database
2. Enter server: `localhost:5432`
3. Enter database: `USER`
4. Choose DirectQuery or Import mode
5. Enter credentials

**Features**:
- Microsoft 365 integration
- Natural language queries (Q&A)
- Power Query for data transformation
- Publish to Power BI Service
- **DirectQuery**: Query IRIS directly without data import

**Best For**: Microsoft shops, Office 365 integration, natural language queries.

### Looker (Google)

**Description**: Enterprise BI platform with LookML modeling language.

**Connection Setup**:
1. Admin → Connections → Add Connection
2. Dialect: PostgreSQL 9.5+
3. Enter connection details
4. Test and save

**Features**:
- LookML data modeling language
- Git-based version control
- Embedded analytics API
- Google Cloud integration
- **Explores**: Define reusable data models with relationships

**Best For**: Data teams, embedded analytics, Google Cloud customers.

### DBeaver

**Description**: Universal database tool - SQL IDE with ER diagrams and data export.

**Connection Setup**:
1. Database → New Database Connection
2. Select PostgreSQL
3. Enter connection details
4. Test Connection → Finish

**Features**:
- SQL editor with autocomplete
- ER diagrams from schema
- CSV/JSON/Excel export
- Data compare and sync
- **pg_catalog Browsing**: Inspect IRIS catalog emulation

**Best For**: Developers, database administrators, data export/import.

### DataGrip (JetBrains)

**Description**: Professional SQL IDE from JetBrains with code completion and refactoring.

**Connection Setup**:
1. Database → + → Data Source → PostgreSQL
2. Enter connection details
3. Download PostgreSQL JDBC driver (if prompted)
4. Test Connection → OK

**Features**:
- Intelligent SQL editor
- Database refactoring tools
- Version control integration
- Query execution plans
- **Foreign Key Detection**: Uses pg_constraint catalog

**Best For**: Professional developers, complex SQL workflows, JetBrains users.

---

## Common Connection Patterns

### Using psql Command Line

```bash
# Connect via psql
psql -h localhost -p 5432 -U _SYSTEM -d USER

# Run query
SELECT COUNT(*) FROM your_table;

# Export to CSV
\copy (SELECT * FROM your_table) TO 'export.csv' CSV HEADER

# Import from CSV (requires COPY protocol support)
\copy your_table FROM 'import.csv' CSV HEADER
```

### Using Python (for custom BI tools)

```python
import psycopg
import pandas as pd

# Connect
conn = psycopg.connect("host=localhost port=5432 dbname=USER user=_SYSTEM password=SYS")

# Query to DataFrame
df = pd.read_sql("SELECT * FROM your_table", conn)

# Use pandas for visualization
df.plot(x='date', y='value', kind='line')
```

### Using JDBC (for Java-based BI tools)

```java
// Maven dependency: org.postgresql:postgresql:42.7.0
String url = "jdbc:postgresql://localhost:5432/USER";
Properties props = new Properties();
props.setProperty("user", "_SYSTEM");
props.setProperty("password", "SYS");

Connection conn = DriverManager.getConnection(url, props);
ResultSet rs = conn.createStatement().executeQuery("SELECT * FROM your_table");
```

---

## Advanced Features

### Vector Analytics in BI Tools

**Use Case**: Semantic search, recommendation systems, RAG applications visualized in BI dashboards.

**Example (Superset SQL Lab)**:
```sql
-- Find similar documents with similarity score
SELECT
  id,
  title,
  VECTOR_COSINE(embedding, TO_VECTOR('[...]', DOUBLE)) AS similarity_score
FROM documents
WHERE VECTOR_COSINE(embedding, TO_VECTOR('[...]', DOUBLE)) > 0.7
ORDER BY similarity_score DESC
LIMIT 20;
```

**Visualization**: Create bar chart with `title` on X-axis, `similarity_score` on Y-axis.

### IRIS IntegratedML Predictions

**Use Case**: Visualize ML model predictions in real-time dashboards.

**Example (Grafana)**:
```sql
-- Real-time fraud detection scores
SELECT
  transaction_id,
  amount,
  PREDICT(FraudDetectionModel) AS fraud_probability
FROM transactions
WHERE timestamp > NOW() - INTERVAL '1 hour'
ORDER BY fraud_probability DESC;
```

### Cross-Database Joins (via Federation)

**Use Case**: Join IRIS data with other data sources in BI tool.

**Example (Tableau)**:
1. Connect to IRIS via PGWire (PostgreSQL connection)
2. Connect to another PostgreSQL database (native connection)
3. Create relationships between tables in Tableau data model
4. Build visualizations using joined data

---

## Performance Optimization

### Use Indexes

Ensure IRIS tables have appropriate indexes:

```sql
-- Create index for frequently filtered columns
CREATE INDEX idx_users_email ON users(email);

-- Create HNSW index for vector similarity (5× speedup)
CREATE INDEX idx_docs_embedding ON documents(embedding) USING HNSW;
```

### Limit Result Sets

Configure BI tool row limits:

| Tool | Setting | Recommended |
|------|---------|-------------|
| **Superset** | SQL Lab row limit | 10,000 |
| **Metabase** | Maximum table size | 10,000 |
| **Grafana** | Max data points | 5,000 |
| **Tableau** | Initial SQL limit | 10,000 |

### Use Materialized Views

Pre-aggregate data for dashboard queries:

```sql
-- Create materialized view for dashboard
CREATE MATERIALIZED VIEW daily_sales_summary AS
SELECT
  DATE(order_date) AS date,
  SUM(amount) AS total_sales,
  COUNT(*) AS order_count
FROM orders
GROUP BY DATE(order_date);

-- Refresh periodically
-- (Use IRIS scheduled tasks or external cron job)
REFRESH MATERIALIZED VIEW daily_sales_summary;
```

### DirectQuery vs Import Mode

| Mode | Latency | Freshness | Best For |
|------|---------|-----------|----------|
| **DirectQuery** | Query IRIS real-time | Always fresh | Real-time dashboards, small result sets |
| **Import** | Pre-loaded data | Stale until refresh | Large datasets, complex aggregations |

**Recommendation**: Use DirectQuery for operational dashboards, Import for analytical reports.

---

## Troubleshooting

### Issue: "Connection refused" error

**Cause**: PGWire server not running or firewall blocking port 5432.

**Solution**:
```bash
# Check if PGWire is running
docker-compose ps pgwire

# Check port is listening
lsof -i :5432

# Restart PGWire if needed
docker-compose restart pgwire
```

### Issue: "Authentication failed" error

**Cause**: Incorrect IRIS credentials.

**Solution**:
1. Verify IRIS username/password: `iris session IRIS -U USER 'write ##class(%SYSTEM.Process).UserName()'`
2. Check IRIS security settings allow external connections
3. Ensure user has SQL privileges: `GRANT SELECT ON * TO username`

### Issue: BI tool shows "No tables found"

**Cause**: Schema mapping issue - BI tool looking in wrong schema.

**Solution**:
```bash
# Check current schema mapping
export PGWIRE_IRIS_SCHEMA=SQLUser  # Default

# If using custom schema
export PGWIRE_IRIS_SCHEMA=YourSchemaName

# Restart PGWire after changing
docker-compose restart pgwire
```

### Issue: Slow query performance in BI tool

**Cause**: Missing indexes, large result sets, or inefficient SQL.

**Solution**:
1. Check query execution plan: `EXPLAIN <your_query>`
2. Add indexes on filtered/joined columns
3. Limit result set size in BI tool configuration
4. Use aggregated views for dashboard queries

### Issue: "SSL connection required" error

**Cause**: BI tool enforcing SSL, but PGWire doesn't support SSL directly.

**Solution**: Use reverse proxy (nginx/HAProxy) for TLS termination:

```nginx
# nginx.conf
stream {
    upstream pgwire {
        server localhost:5432;
    }

    server {
        listen 5433 ssl;
        ssl_certificate /path/to/cert.pem;
        ssl_certificate_key /path/to/key.pem;
        proxy_pass pgwire;
    }
}
```

Then connect BI tool to `localhost:5433` with SSL enabled.

---

## Healthcare Demo Walkthrough

**Complete Example**: 250 patient records + 400 lab results + pre-built Superset dashboards.

**Setup** (<10 minutes):
```bash
# Clone repository
git clone https://github.com/intersystems-community/iris-pgwire.git
cd iris-pgwire/examples/superset-iris-healthcare

# Start IRIS, PGWire, and Superset
docker-compose up -d

# Load healthcare demo data
docker-compose exec iris iris session IRIS < /data/load_healthcare_data.sql

# Import Superset dashboards
docker-compose exec superset superset import-dashboards -p /dashboards/
```

**Access Superset**: http://localhost:8088 (admin / admin)

**Pre-Built Dashboards**:
1. **Patient Overview** - Demographics, admission rates, length of stay
2. **Lab Results Analysis** - Test result distributions, abnormal values, trends
3. **Vector Search Demo** - Find similar patient records using embeddings

**Learn More**: [Superset Healthcare Example](https://github.com/intersystems-community/iris-pgwire/blob/main/examples/superset-iris-healthcare/README.md)

---

## See Also

- [Client Recommendations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/CLIENT_RECOMMENDATIONS.md) - Full compatibility matrix
- [Performance Benchmarks](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PERFORMANCE.md) - Query performance analysis
- [Vector Operations](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/VECTOR_PARAMETER_BINDING.md) - Vector similarity in BI tools
- [PG_CATALOG Documentation](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md) - How BI tools discover schema
