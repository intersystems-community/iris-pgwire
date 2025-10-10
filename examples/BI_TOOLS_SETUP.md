# Open Source BI Tools with IRIS via PGWire

This guide shows how to connect popular open-source BI tools to InterSystems IRIS through the PostgreSQL wire protocol.

---

## Available BI Tools

### 1. Apache Superset - Modern Data Exploration Platform
**Port**: 8088
**URL**: http://localhost:8088
**Credentials**: admin / admin

**Features**:
- Modern, feature-rich BI platform
- SQL Lab for interactive queries
- Rich visualizations and dashboards
- Built-in caching and query optimization
- Role-based access control

### 2. Metabase - Simple, User-Friendly BI
**Port**: 3001
**URL**: http://localhost:3001
**Credentials**: Setup on first launch

**Features**:
- Extremely user-friendly interface
- Visual query builder (no SQL required)
- Automated insights and X-ray analysis
- Email reports and alerts
- Embedding capabilities

### 3. Grafana - Monitoring and Analytics
**Port**: 3000
**URL**: http://localhost:3000
**Credentials**: admin / admin

**Features**:
- Time-series data visualization
- Real-time monitoring dashboards
- Alerting and notifications
- Plugin ecosystem
- Multi-tenant support

---

## Quick Start

### Launch BI Tools

```bash
# Start IRIS and PGWire server
docker-compose up -d iris

# Wait for IRIS to be healthy
docker-compose ps iris

# Launch all BI tools
docker-compose --profile bi-tools up -d

# Or launch individually:
docker-compose --profile bi-tools up -d superset
docker-compose --profile bi-tools up -d metabase
docker-compose --profile monitoring up -d grafana
```

### Check Status

```bash
# Verify all services are running
docker-compose ps

# Expected output:
# superset-bi      - healthy - 8088:8088
# metabase-bi      - healthy - 3001:3000
# grafana          - healthy - 3000:3000
# iris-pgwire-db   - healthy - 5432:5432
```

---

## Connection Configuration

All BI tools connect to IRIS via the same PostgreSQL connection:

```
Host:     iris (or localhost if outside Docker)
Port:     5432
Database: USER
Username: test_user (or _SYSTEM for admin)
Password: (leave blank for test_user)
```

---

## Apache Superset Setup

### 1. Access Superset

```bash
# Open browser
open http://localhost:8088

# Login
Username: admin
Password: admin
```

### 2. Add IRIS Database Connection

1. Click **Settings** → **Database Connections**
2. Click **+ Database**
3. Select **PostgreSQL**
4. Configure connection:

```yaml
Display Name: IRIS via PGWire
SQLAlchemy URI: postgresql://test_user@iris:5432/USER
```

5. Click **Test Connection** → Should see "Connection looks good!"
6. Click **Connect**

### 3. Create Sample Dashboard

**SQL Lab → New Query**:

```sql
-- Sales performance query
SELECT
    DATE_TRUNC('month', sale_date) as month,
    region,
    SUM(total_amount) as revenue,
    COUNT(*) as transactions,
    AVG(customer_satisfaction) as satisfaction
FROM sales_data
WHERE sale_date >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY month, region
ORDER BY month, region
```

**Create Visualization**:
1. Click **Explore** on query results
2. Choose **Line Chart**
3. Configure:
   - X-axis: month
   - Y-axis: revenue
   - Group by: region
4. Save to dashboard

---

## Metabase Setup

### 1. Access Metabase

```bash
# Open browser
open http://localhost:3001

# First-time setup wizard will appear
```

### 2. Complete Setup Wizard

1. **Language**: English
2. **Create account**:
   - Email: admin@example.com
   - First name: Admin
   - Last name: User
   - Password: admin123
3. Click **Next**

### 3. Add IRIS Database

1. **Add your data**:
   - Database type: PostgreSQL
   - Display name: IRIS via PGWire
   - Host: iris
   - Port: 5432
   - Database name: USER
   - Username: test_user
   - Password: (leave blank)
2. Click **Connect database**

### 4. Auto-Generated Insights

Metabase will automatically:
- Scan IRIS tables
- Generate X-ray insights
- Suggest visualizations
- Create sample questions

### 5. Visual Query Builder

**Create Question** (no SQL required):

1. Click **+ New** → **Question**
2. Select **IRIS via PGWire** → **sales_data**
3. Use visual builder:
   - Summarize: Sum of total_amount
   - Group by: region
   - Filter: sale_date is in the last 6 months
4. Click **Visualize**
5. Choose chart type (bar, line, pie, etc.)
6. Save to dashboard

---

## Grafana Setup

### 1. Access Grafana

```bash
# Open browser
open http://localhost:3000

# Login
Username: admin
Password: admin
```

### 2. Add IRIS Data Source

1. Click **Configuration** (gear icon) → **Data sources**
2. Click **Add data source**
3. Select **PostgreSQL**
4. Configure:

```yaml
Name: IRIS via PGWire
Host: iris:5432
Database: USER
User: test_user
Password: (leave blank)
TLS/SSL Mode: disable
Version: 14+ (select latest)
```

5. Click **Save & Test** → Should see "Database Connection OK"

### 3. Create Time-Series Dashboard

**New Dashboard → Add Panel**:

```sql
-- Time-series revenue query
SELECT
  EXTRACT(EPOCH FROM sale_date) * 1000 as time,
  region as metric,
  total_amount as value
FROM sales_data
WHERE sale_date >= NOW() - INTERVAL '30 days'
ORDER BY time
```

**Panel Settings**:
- Visualization: Time series
- Transform: Group by region
- Y-axis: Revenue
- X-axis: Time

### 4. Real-Time Monitoring

Grafana excels at real-time monitoring:

```sql
-- Active connections
SELECT
  COUNT(*) as active_connections,
  NOW() * 1000 as time
FROM pg_stat_activity
WHERE datname = 'USER'

-- Query performance
SELECT
  EXTRACT(EPOCH FROM NOW()) * 1000 as time,
  'avg_query_time' as metric,
  AVG(total_time) as value
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat%'
```

---

## Advanced Features

### Apache Superset - IRIS Vector Similarity

```sql
-- Product similarity dashboard
SELECT
    p1.product_name,
    p2.product_name as similar_product,
    VECTOR_COSINE(
        TO_VECTOR(p1.feature_vector),
        TO_VECTOR(p2.feature_vector)
    ) as similarity
FROM product_analytics p1
CROSS JOIN product_analytics p2
WHERE p1.product_id != p2.product_id
AND p1.category = p2.category
ORDER BY similarity DESC
LIMIT 20
```

### Metabase - Embedded Analytics

```bash
# Enable public sharing
# Settings → Admin → Settings → Public Sharing → Enable

# Create shareable link for any dashboard
# Dashboard → Sharing icon → Public link
```

### Grafana - Alerting on IRIS Data

```sql
-- Alert when sales drop below threshold
SELECT
  EXTRACT(EPOCH FROM NOW()) * 1000 as time,
  SUM(total_amount) as daily_revenue
FROM sales_data
WHERE sale_date = CURRENT_DATE
```

**Alert Rule**:
- Condition: daily_revenue < 50000
- Notification: Email, Slack, PagerDuty

---

## Performance Tips

### 1. Enable Query Caching (Superset)

```yaml
# superset_config.py
CACHE_CONFIG = {
    'CACHE_TYPE': 'redis',
    'CACHE_REDIS_URL': 'redis://redis:6379/0'
}
```

### 2. Connection Pooling (All Tools)

IRIS PGWire server already provides connection pooling (50 base + 20 overflow). BI tools will automatically benefit.

### 3. Materialized Views (IRIS)

For expensive queries, create materialized views in IRIS:

```sql
CREATE MATERIALIZED VIEW daily_sales_summary AS
SELECT
    DATE(sale_date) as day,
    region,
    SUM(total_amount) as revenue,
    COUNT(*) as transactions
FROM sales_data
GROUP BY DATE(sale_date), region;

-- Refresh on schedule (IRIS cron job or external scheduler)
REFRESH MATERIALIZED VIEW daily_sales_summary;
```

---

## Sample Dashboards

### Sales Performance Dashboard (All Tools)

**Metrics to Include**:
1. Revenue trend (line chart)
2. Top products (bar chart)
3. Regional breakdown (map or pie chart)
4. Customer satisfaction (gauge)
5. Sales rep leaderboard (table)
6. YoY growth (KPI cards)

### Vector Analytics Dashboard (Superset)

**IRIS-Specific Capabilities**:
1. Product similarity heatmap
2. Customer clustering visualization
3. Recommendation engine results
4. Anomaly detection alerts

### Real-Time Operations Dashboard (Grafana)

**Monitoring Metrics**:
1. Active database connections
2. Query latency (P50, P95, P99)
3. Transaction throughput
4. Cache hit rates
5. Error rates

---

## Troubleshooting

### Connection Issues

```bash
# Test PostgreSQL connection from Docker
docker exec -it superset-bi psql -h iris -p 5432 -U test_user -d USER

# Check PGWire server logs
docker logs iris-pgwire-db | grep -i pgwire

# Verify network connectivity
docker exec -it superset-bi ping iris
```

### Superset Database Migration Errors

```bash
# Reset Superset database
docker-compose --profile bi-tools down -v
docker volume rm iris-pgwire_superset_home
docker-compose --profile bi-tools up -d superset
```

### Metabase Startup Issues

```bash
# Check Metabase logs
docker logs metabase-bi

# Verify Metabase database is healthy
docker exec -it metabase-postgres psql -U metabase -d metabase -c "SELECT version();"
```

### Grafana Data Source Errors

```bash
# Test from Grafana container
docker exec -it grafana psql -h iris -p 5432 -U test_user -d USER -c "SELECT 1"

# Check Grafana logs
docker logs grafana | grep -i postgres
```

---

## Next Steps

1. **Load Sample Data**: Run `examples/bi_tools_demo.py` to populate IRIS with business data
2. **Create Dashboards**: Use the SQL examples above in each BI tool
3. **Share Results**: Export dashboards or create public links
4. **Explore IRIS Features**: Leverage IRIS VECTOR operations in your analytics

---

## Summary

✅ **3 Open-Source BI Tools** connected to IRIS via PostgreSQL wire protocol
✅ **Zero code changes** required in BI tools
✅ **Full feature compatibility** (SQL Lab, visual builders, dashboards)
✅ **IRIS unique features** accessible (VECTOR operations, HNSW indexes)
✅ **Production-ready** with connection pooling and caching

**IRIS is now part of the modern BI ecosystem!** 🚀
