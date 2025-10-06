# IRIS Enterprise Build 127 EHAT Setup Guide

## Quick Reference for Enterprise IRIS Docker Setup

### Working Configuration (kg-ticket-resolver proven)

```yaml
# docker-compose.yml
services:
  iris:
    image: containers.intersystems.com/intersystems/iris-arm64:2025.1
    platform: linux/arm64
    container_name: iris-enterprise
    environment:
      - IRIS_USERNAME=SuperUser
      - IRIS_PASSWORD=SYS
      - ISC_PASSWORD=SYS
      - IRIS_NAMESPACE=USER
    volumes:
      - ./iris.key:/usr/irissys/mgr/iris.key:ro
    ports:
      - "1972:1972"     # SuperServer
      - "52773:52773"   # Management Portal
```

### Essential Files Required

1. **License Key**: Copy from kg-ticket-resolver
   ```bash
   cp /Users/tdyar/ws/kg-ticket-resolver/deployment/prod/iris.key .
   ```

2. **Password Secret** (for production):
   ```bash
   echo "SYS" > secrets/iris_password
   chmod 600 secrets/iris_password
   ```

### Connection Details

- **Host**: 127.0.0.1 or localhost
- **Port**: 1972 (SuperServer)
- **Username**: SuperUser (NOT _SYSTEM)
- **Password**: SYS
- **Namespace**: USER

### Password Reset (if needed)

```bash
# Access container
docker exec -it <container_name> bash

# Reset passwords non-interactively
docker exec <container_name> bash -c 'echo -e "ZN \"%SYS\"\nDO ##class(Security.Users).UnExpireUserPasswords(\"*\")\nSET user = \"SuperUser\"\nSET password = \"SYS\"\nDO ##class(Security.Users).Modify(user,,password)\nHALT" | iris terminal IRIS'
```

### Important Notes

1. **Enterprise vs Community**: Build 127 EHAT requires license key and uses SuperUser
2. **Authentication**: `iris sql` command may show "Access Denied" even when working
3. **Connection Test**: Use SuperServer port 1972, not terminal commands
4. **Working Example**: kg-ticket-resolver deployment/prod/docker-compose.graphrag.yml
5. **Environment Variables**: ISC_PASSWORD and IRIS_PASSWORD both needed

### Python Connection String

```python
# For embedded Python or external connections
iris://SuperUser:SYS@localhost:1972/USER
```

### Troubleshooting

- **License Error**: Ensure iris.key is mounted and readable
- **Access Denied**: Normal for terminal, test via SuperServer port 1972
- **Container Won't Start**: Check license key path and permissions
- **Connection Refused**: Wait 30-40 seconds for full IRIS startup

### Proven Working Command

```bash
# From kg-ticket-resolver directory
docker compose --env-file deployment/prod/graphrag.env \
  -f deployment/prod/docker-compose.graphrag.yml up -d iris
```

This setup has been validated with PostgreSQL wire protocol development and GraphRAG integration.