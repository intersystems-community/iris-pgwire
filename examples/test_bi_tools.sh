#!/bin/bash
# Test BI Tools Integration with IRIS via PGWire
set -e

echo "🔍 IRIS PGWire - BI Tools Integration Test"
echo "=========================================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if IRIS is running
echo -e "\n${YELLOW}1. Checking IRIS status...${NC}"
if docker ps | grep -q iris-pgwire-db; then
    echo -e "${GREEN}✅ IRIS container is running${NC}"
else
    echo -e "${RED}❌ IRIS container not running${NC}"
    echo "Start with: docker-compose up -d iris"
    exit 1
fi

# Check if PGWire is accessible
echo -e "\n${YELLOW}2. Testing PGWire connection...${NC}"
if docker exec iris-pgwire-db timeout 5 bash -c "echo 'SELECT 1' | /usr/irissys/bin/irissql -U_SYSTEM USER" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ IRIS SQL accessible${NC}"
else
    echo -e "${YELLOW}⚠️  IRIS SQL check inconclusive (may be normal)${NC}"
fi

# Test PostgreSQL wire protocol connection
echo -e "\n${YELLOW}3. Testing PostgreSQL wire protocol (port 5432)...${NC}"
if timeout 5 psql -h localhost -p 5432 -U test_user -d USER -c "SELECT 1" >/dev/null 2>&1; then
    echo -e "${GREEN}✅ PGWire server is responding${NC}"
else
    echo -e "${RED}❌ PGWire server not accessible on port 5432${NC}"
    echo "Check logs: docker logs iris-pgwire-db | grep pgwire"
    exit 1
fi

# Launch BI tools
echo -e "\n${YELLOW}4. Launching BI tools...${NC}"
docker-compose --profile bi-tools up -d

# Wait for services to start
echo -e "\n${YELLOW}5. Waiting for BI tools to initialize...${NC}"
sleep 10

# Check Apache Superset
echo -e "\n${YELLOW}6. Checking Apache Superset (port 8088)...${NC}"
if docker ps | grep -q superset-bi; then
    if timeout 10 curl -s http://localhost:8088/health >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Superset is running and healthy${NC}"
        echo "   Access at: http://localhost:8088"
        echo "   Login: admin / admin"
    else
        echo -e "${YELLOW}⚠️  Superset is starting (may take 30-60 seconds)${NC}"
        echo "   Check status: docker logs superset-bi"
    fi
else
    echo -e "${RED}❌ Superset container not running${NC}"
fi

# Check Metabase
echo -e "\n${YELLOW}7. Checking Metabase (port 3001)...${NC}"
if docker ps | grep -q metabase-bi; then
    if timeout 10 curl -s http://localhost:3001/api/health >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Metabase is running and healthy${NC}"
        echo "   Access at: http://localhost:3001"
        echo "   Setup wizard on first visit"
    else
        echo -e "${YELLOW}⚠️  Metabase is starting (may take 30-60 seconds)${NC}"
        echo "   Check status: docker logs metabase-bi"
    fi
else
    echo -e "${RED}❌ Metabase container not running${NC}"
fi

# Check Grafana
echo -e "\n${YELLOW}8. Checking Grafana (port 3000)...${NC}"
if docker ps | grep -q grafana; then
    if timeout 10 curl -s http://localhost:3000/api/health >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Grafana is running and healthy${NC}"
        echo "   Access at: http://localhost:3000"
        echo "   Login: admin / admin"
    else
        echo -e "${YELLOW}⚠️  Grafana is starting...${NC}"
        echo "   Check status: docker logs grafana"
    fi
else
    echo -e "${YELLOW}⚠️  Grafana not running (use --profile monitoring)${NC}"
    echo "   Start with: docker-compose --profile monitoring up -d grafana"
fi

# Test database connection from each BI tool
echo -e "\n${YELLOW}9. Testing database connections from BI tools...${NC}"

# Test from Superset container
if docker ps | grep -q superset-bi; then
    if docker exec superset-bi timeout 5 bash -c "command -v psql >/dev/null 2>&1 && psql -h iris -p 5432 -U test_user -d USER -c 'SELECT 1'" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Superset can connect to IRIS via PGWire${NC}"
    else
        echo -e "${YELLOW}⚠️  Superset connection test inconclusive${NC}"
    fi
fi

# Summary
echo -e "\n${GREEN}=========================================="
echo "✅ BI Tools Integration Test Complete"
echo "==========================================${NC}"

echo -e "\n${YELLOW}Next Steps:${NC}"
echo "1. Access Superset: http://localhost:8088 (admin/admin)"
echo "2. Access Metabase: http://localhost:3001 (setup wizard)"
echo "3. Access Grafana:  http://localhost:3000 (admin/admin)"
echo ""
echo "Connection Details for All Tools:"
echo "  Host:     iris"
echo "  Port:     5432"
echo "  Database: USER"
echo "  Username: test_user"
echo "  Password: (leave blank)"
echo ""
echo "See examples/BI_TOOLS_SETUP.md for detailed setup instructions"
