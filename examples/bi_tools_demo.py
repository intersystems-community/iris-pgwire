#!/usr/bin/env python3
"""
Business Intelligence Tools Demonstration

Shows how IRIS data becomes accessible to BI tools through PostgreSQL wire protocol.
Simulates connections from Tableau, Power BI, QlikView, and other tools.
"""

import asyncio
import random
from datetime import datetime, timedelta

import asyncpg


class BIToolsDemo:
    """Simulate BI tool connections and queries"""

    def __init__(self):
        self.conn = None
        self.demo_data_created = False

    async def setup_connection(self):
        """Setup PostgreSQL connection"""
        self.conn = await asyncpg.connect(
            host='127.0.0.1',
            port=5432,
            user='test_user',
            database='USER'
        )
        print("✅ Connected to IRIS via PostgreSQL wire protocol")

    async def create_business_data(self):
        """Create realistic business data for BI demonstrations"""
        if self.demo_data_created:
            return

        print("\n📊 Creating business intelligence demo data...")

        # Sales data table
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS sales_data (
                id SERIAL PRIMARY KEY,
                sale_date DATE,
                region VARCHAR(50),
                product_category VARCHAR(50),
                product_name VARCHAR(100),
                customer_segment VARCHAR(50),
                sales_rep VARCHAR(100),
                quantity INTEGER,
                unit_price DECIMAL(10,2),
                total_amount DECIMAL(12,2),
                discount_percent DECIMAL(5,2),
                customer_satisfaction DECIMAL(3,2)
            )
        """)

        # Customer data table
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS customer_data (
                customer_id SERIAL PRIMARY KEY,
                customer_name VARCHAR(100),
                company VARCHAR(100),
                industry VARCHAR(50),
                country VARCHAR(50),
                annual_revenue DECIMAL(15,2),
                employee_count INTEGER,
                acquisition_date DATE,
                customer_lifetime_value DECIMAL(12,2)
            )
        """)

        # Product performance with vectors
        await self.conn.execute("""
            CREATE TABLE IF NOT EXISTS product_analytics (
                product_id SERIAL PRIMARY KEY,
                product_name VARCHAR(100),
                category VARCHAR(50),
                launch_date DATE,
                feature_vector TEXT,
                performance_score DECIMAL(5,3),
                market_position VARCHAR(20),
                competitor_similarity DECIMAL(5,3)
            )
        """)

        # Generate sample data
        regions = ['North America', 'Europe', 'Asia Pacific', 'Latin America', 'Middle East & Africa']
        categories = ['Software', 'Hardware', 'Services', 'Cloud Solutions', 'Analytics']
        segments = ['Enterprise', 'SMB', 'Startup', 'Government', 'Education']
        industries = ['Healthcare', 'Finance', 'Manufacturing', 'Retail', 'Technology']

        # Insert sales data
        sales_data = []
        for i in range(1000):
            sale_date = datetime.now() - timedelta(days=random.randint(0, 365))
            region = random.choice(regions)
            category = random.choice(categories)
            segment = random.choice(segments)

            quantity = random.randint(1, 100)
            unit_price = random.uniform(10, 1000)
            total_amount = quantity * unit_price
            discount = random.uniform(0, 25)
            satisfaction = random.uniform(3.0, 5.0)

            sales_data.append((
                sale_date.date(), region, category, f"{category} Product {i%50}",
                segment, f"Rep {i%20}", quantity, unit_price, total_amount,
                discount, satisfaction
            ))

        await self.conn.executemany("""
            INSERT INTO sales_data (sale_date, region, product_category, product_name,
                                  customer_segment, sales_rep, quantity, unit_price,
                                  total_amount, discount_percent, customer_satisfaction)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """, sales_data)

        # Insert customer data
        customer_data = []
        for i in range(200):
            acquisition = datetime.now() - timedelta(days=random.randint(30, 1095))
            revenue = random.uniform(100000, 50000000)
            employees = random.randint(10, 10000)
            clv = revenue * random.uniform(0.1, 0.5)

            customer_data.append((
                f"Customer {i}", f"Company {i}", random.choice(industries),
                random.choice(['USA', 'UK', 'Germany', 'Japan', 'Canada', 'Australia']),
                revenue, employees, acquisition.date(), clv
            ))

        await self.conn.executemany("""
            INSERT INTO customer_data (customer_name, company, industry, country,
                                     annual_revenue, employee_count, acquisition_date,
                                     customer_lifetime_value)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """, customer_data)

        # Insert product analytics with vectors
        product_data = []
        for i in range(50):
            # Create feature vectors for product similarity
            features = [random.uniform(0, 1) for _ in range(10)]
            feature_vector = "[" + ",".join([f"{f:.3f}" for f in features]) + "]"

            launch = datetime.now() - timedelta(days=random.randint(30, 1800))
            performance = random.uniform(0.1, 1.0)
            similarity = random.uniform(0.0, 1.0)

            product_data.append((
                f"Product {i}", random.choice(categories), launch.date(),
                feature_vector, performance,
                random.choice(['Leader', 'Challenger', 'Follower', 'Niche']),
                similarity
            ))

        await self.conn.executemany("""
            INSERT INTO product_analytics (product_name, category, launch_date,
                                         feature_vector, performance_score,
                                         market_position, competitor_similarity)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, product_data)

        print("✅ Business intelligence demo data created")
        self.demo_data_created = True

    async def tableau_style_queries(self):
        """Demonstrate queries typical of Tableau dashboards"""
        print("\n🔸 Tableau-Style Dashboard Queries")
        print("-" * 50)

        # Sales by region and time
        result = await self.conn.fetch("""
            SELECT
                region,
                DATE_PART('year', sale_date) as year,
                DATE_PART('month', sale_date) as month,
                SUM(total_amount) as total_sales,
                COUNT(*) as transaction_count,
                AVG(customer_satisfaction) as avg_satisfaction
            FROM sales_data
            GROUP BY region, year, month
            ORDER BY year, month, region
        """)
        print(f"✓ Sales by Region/Time: {len(result)} data points")

        # Top products performance
        result = await self.conn.fetch("""
            SELECT
                product_category,
                product_name,
                SUM(total_amount) as revenue,
                SUM(quantity) as units_sold,
                AVG(unit_price) as avg_price,
                COUNT(DISTINCT sales_rep) as rep_count
            FROM sales_data
            GROUP BY product_category, product_name
            ORDER BY revenue DESC
            LIMIT 20
        """)
        print(f"✓ Top Products Analysis: {len(result)} products")

        # Customer segment analysis
        result = await self.conn.fetch("""
            SELECT
                customer_segment,
                AVG(total_amount) as avg_deal_size,
                SUM(total_amount) as total_revenue,
                COUNT(*) as deal_count,
                AVG(discount_percent) as avg_discount,
                AVG(customer_satisfaction) as satisfaction
            FROM sales_data
            GROUP BY customer_segment
            ORDER BY total_revenue DESC
        """)
        print(f"✓ Customer Segment Analysis: {len(result)} segments")

    async def power_bi_style_queries(self):
        """Demonstrate queries typical of Power BI reports"""
        print("\n🔸 Power BI-Style Report Queries")
        print("-" * 50)

        # Year-over-year growth
        result = await self.conn.fetch("""
            WITH yearly_sales AS (
                SELECT
                    DATE_PART('year', sale_date) as year,
                    SUM(total_amount) as annual_sales
                FROM sales_data
                GROUP BY DATE_PART('year', sale_date)
            )
            SELECT
                year,
                annual_sales,
                LAG(annual_sales) OVER (ORDER BY year) as prev_year_sales,
                CASE
                    WHEN LAG(annual_sales) OVER (ORDER BY year) IS NOT NULL
                    THEN ((annual_sales - LAG(annual_sales) OVER (ORDER BY year)) /
                          LAG(annual_sales) OVER (ORDER BY year)) * 100
                    ELSE NULL
                END as growth_percentage
            FROM yearly_sales
            ORDER BY year
        """)
        print(f"✓ Year-over-Year Growth: {len(result)} years")

        # Sales rep performance ranking
        result = await self.conn.fetch("""
            SELECT
                sales_rep,
                COUNT(*) as deals_closed,
                SUM(total_amount) as total_revenue,
                AVG(total_amount) as avg_deal_size,
                AVG(customer_satisfaction) as avg_satisfaction,
                RANK() OVER (ORDER BY SUM(total_amount) DESC) as revenue_rank,
                RANK() OVER (ORDER BY AVG(customer_satisfaction) DESC) as satisfaction_rank
            FROM sales_data
            GROUP BY sales_rep
            ORDER BY total_revenue DESC
        """)
        print(f"✓ Sales Rep Performance: {len(result)} representatives")

        # Customer lifetime value analysis
        result = await self.conn.fetch("""
            SELECT
                c.industry,
                COUNT(*) as customer_count,
                AVG(c.customer_lifetime_value) as avg_clv,
                SUM(c.customer_lifetime_value) as total_clv,
                AVG(c.annual_revenue) as avg_annual_revenue,
                CORR(c.annual_revenue, c.customer_lifetime_value) as revenue_clv_correlation
            FROM customer_data c
            GROUP BY c.industry
            ORDER BY total_clv DESC
        """)
        print(f"✓ Customer LTV Analysis: {len(result)} industries")

    async def qlik_style_queries(self):
        """Demonstrate queries typical of QlikView/QlikSense"""
        print("\n🔸 QlikView/QlikSense-Style Analytics")
        print("-" * 50)

        # Dynamic filtering and associations
        result = await self.conn.fetch("""
            SELECT
                s.region,
                s.product_category,
                c.industry,
                COUNT(DISTINCT s.id) as sales_count,
                SUM(s.total_amount) as revenue,
                COUNT(DISTINCT c.customer_id) as unique_customers,
                AVG(s.customer_satisfaction) as satisfaction
            FROM sales_data s
            CROSS JOIN customer_data c
            WHERE c.industry IN ('Healthcare', 'Finance', 'Technology')
            GROUP BY s.region, s.product_category, c.industry
            HAVING SUM(s.total_amount) > 10000
            ORDER BY revenue DESC
        """)
        print(f"✓ Cross-dimensional Analysis: {len(result)} combinations")

        # Set analysis style queries
        result = await self.conn.fetch("""
            WITH high_performers AS (
                SELECT sales_rep, SUM(total_amount) as total_sales
                FROM sales_data
                GROUP BY sales_rep
                HAVING SUM(total_amount) > (
                    SELECT AVG(rep_sales) FROM (
                        SELECT SUM(total_amount) as rep_sales
                        FROM sales_data
                        GROUP BY sales_rep
                    ) avg_calc
                )
            )
            SELECT
                s.product_category,
                COUNT(*) as transactions,
                SUM(s.total_amount) as revenue_from_top_reps,
                AVG(s.customer_satisfaction) as satisfaction
            FROM sales_data s
            INNER JOIN high_performers hp ON s.sales_rep = hp.sales_rep
            GROUP BY s.product_category
            ORDER BY revenue_from_top_reps DESC
        """)
        print(f"✓ Set Analysis (Top Performers): {len(result)} categories")

    async def vector_analytics_queries(self):
        """Demonstrate vector-based analytics for BI tools"""
        print("\n🔸 Vector Analytics (IRIS Unique Capabilities)")
        print("-" * 50)

        try:
            # Product similarity analysis
            result = await self.conn.fetch("""
                SELECT
                    p1.product_name as product_a,
                    p2.product_name as product_b,
                    VECTOR_COSINE(
                        TO_VECTOR(p1.feature_vector),
                        TO_VECTOR(p2.feature_vector)
                    ) as similarity_score
                FROM product_analytics p1
                CROSS JOIN product_analytics p2
                WHERE p1.product_id < p2.product_id
                AND p1.category = p2.category
                ORDER BY similarity_score DESC
                LIMIT 10
            """)
            print(f"✓ Product Similarity Analysis: {len(result)} comparisons")

            # Market position clustering
            result = await self.conn.fetch("""
                SELECT
                    market_position,
                    COUNT(*) as product_count,
                    AVG(performance_score) as avg_performance,
                    AVG(VECTOR_COSINE(
                        TO_VECTOR(feature_vector),
                        TO_VECTOR('[0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5,0.5]')
                    )) as avg_baseline_similarity
                FROM product_analytics
                GROUP BY market_position
                ORDER BY avg_performance DESC
            """)
            print(f"✓ Market Position Clustering: {len(result)} positions")

        except Exception as e:
            print(f"⚠ Vector operations not available: {str(e)[:50]}")

    async def ml_enhanced_bi_queries(self):
        """Demonstrate ML-enhanced BI queries"""
        print("\n🔸 ML-Enhanced Business Intelligence")
        print("-" * 50)

        try:
            # Create a simple ML model for sales prediction
            await self.conn.execute("""
                CREATE OR REPLACE MODEL sales_predictor
                PREDICTING (total_amount)
                FROM sales_data
            """)

            await self.conn.execute("TRAIN MODEL sales_predictor")

            # Use ML predictions in BI queries
            result = await self.conn.fetch("""
                SELECT
                    region,
                    product_category,
                    AVG(total_amount) as actual_avg_sales,
                    AVG(PREDICT(sales_predictor)) as predicted_avg_sales,
                    COUNT(*) as sample_size
                FROM sales_data
                GROUP BY region, product_category
                HAVING COUNT(*) > 10
                ORDER BY actual_avg_sales DESC
            """)
            print(f"✓ ML-Enhanced Sales Analysis: {len(result)} segments")

            # Predictive customer segmentation
            result = await self.conn.fetch("""
                SELECT
                    customer_segment,
                    AVG(PREDICT(sales_predictor)) as predicted_future_value,
                    COUNT(*) as customer_count,
                    AVG(customer_satisfaction) as satisfaction
                FROM sales_data
                GROUP BY customer_segment
                ORDER BY predicted_future_value DESC
            """)
            print(f"✓ Predictive Customer Segmentation: {len(result)} segments")

        except Exception as e:
            print(f"⚠ ML capabilities not available: {str(e)[:50]}")

    async def performance_benchmarks(self):
        """Run performance benchmarks for BI workloads"""
        print("\n🔸 Performance Benchmarks for BI Workloads")
        print("-" * 50)

        import time

        # Large aggregation query
        start = time.time()
        result = await self.conn.fetch("""
            SELECT
                region,
                product_category,
                customer_segment,
                DATE_PART('year', sale_date) as year,
                DATE_PART('month', sale_date) as month,
                COUNT(*) as transaction_count,
                SUM(total_amount) as total_revenue,
                AVG(total_amount) as avg_deal_size,
                MIN(total_amount) as min_deal,
                MAX(total_amount) as max_deal,
                STDDEV(total_amount) as revenue_stddev,
                AVG(customer_satisfaction) as avg_satisfaction
            FROM sales_data
            GROUP BY region, product_category, customer_segment, year, month
        """)
        duration = time.time() - start
        print(f"✓ Large Aggregation Query: {len(result)} groups in {duration:.2f}s")

        # Complex join performance
        start = time.time()
        result = await self.conn.fetch("""
            SELECT
                s.region,
                c.industry,
                p.market_position,
                COUNT(*) as combinations,
                AVG(s.total_amount) as avg_revenue,
                AVG(c.customer_lifetime_value) as avg_clv,
                AVG(p.performance_score) as avg_product_performance
            FROM sales_data s
            CROSS JOIN customer_data c
            CROSS JOIN product_analytics p
            WHERE c.annual_revenue > 1000000
            AND p.performance_score > 0.5
            GROUP BY s.region, c.industry, p.market_position
            LIMIT 100
        """)
        duration = time.time() - start
        print(f"✓ Complex Multi-table Join: {len(result)} results in {duration:.2f}s")

    async def run_all_demos(self):
        """Run all BI tool demonstrations"""
        await self.setup_connection()
        await self.create_business_data()

        await self.tableau_style_queries()
        await self.power_bi_style_queries()
        await self.qlik_style_queries()
        await self.vector_analytics_queries()
        await self.ml_enhanced_bi_queries()
        await self.performance_benchmarks()

        await self.conn.close()

        print("\n🎉 BI TOOLS DEMONSTRATION COMPLETE!")
        print("\nKey Capabilities Demonstrated:")
        print("✅ Standard SQL analytics (Tableau, Power BI, QlikView compatible)")
        print("✅ Complex aggregations and window functions")
        print("✅ Advanced joins and set analysis")
        print("✅ Vector similarity analytics (IRIS unique)")
        print("✅ ML-enhanced business intelligence")
        print("✅ Enterprise-scale performance")
        print("\n🚀 IRIS data is now accessible to the entire BI ecosystem!")

async def start_demo_server():
    """Start server for demo"""
    try:
        import sys
        sys.path.append('src')
        from iris_pgwire.server import PGWireServer

        server = PGWireServer(
            host='127.0.0.1',
            port=5432,
            iris_host='127.0.0.1',
            iris_port=1975,
            iris_username='SuperUser',
            iris_password='SYS',
            iris_namespace='USER',
            enable_ssl=False
        )

        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(3)
        return server_task
    except Exception as e:
        print(f"Server start failed: {e}")
        return None

async def main():
    print("🔍 IRIS PostgreSQL Wire Protocol - BI Tools Demonstration")
    print("=" * 70)

    server_task = await start_demo_server()
    if not server_task:
        return

    try:
        demo = BIToolsDemo()
        await demo.run_all_demos()
    finally:
        if server_task:
            server_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
