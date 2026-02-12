#!/bin/bash
# Create persistent IRIS container for iris-pgwire-test
# This container will NOT be auto-removed and will persist across reboots

set -e

CONTAINER_NAME="iris-pgwire-test"
HOST_PORT=21972
IMAGE="intersystemsdc/iris-community:latest"
PROJECT_PATH="/Users/tdyar/ws/iris-pgwire-gh"

echo "Creating persistent IRIS container: $CONTAINER_NAME"
echo "  Port: $HOST_PORT -> 1972"
echo "  Image: $IMAGE"

# Remove existing container if any
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "Removing existing container..."
    docker rm -f "$CONTAINER_NAME" > /dev/null 2>&1 || true
fi

# Create container
docker run -d \
    --name "$CONTAINER_NAME" \
    -p "${HOST_PORT}:1972" \
    -p "$((HOST_PORT + 1000)):52773" \
    -e IRIS_PASSWORD=SYS \
    -e IRIS_USERNAME=_SYSTEM \
    --label "com.iris-devtester.project=iris-pgwire-gh" \
    --label "com.iris-devtester.port=${HOST_PORT}" \
    "$IMAGE"

echo "✅ Container created: $CONTAINER_NAME"

# Wait for health
echo "Waiting for IRIS to be ready..."
sleep 5

# Register with port registry
python3 - "$PROJECT_PATH" "$HOST_PORT" "$CONTAINER_NAME" <<'EOF'
import json
import sys
from pathlib import Path

project_path = sys.argv[1]
host_port = int(sys.argv[2])
container_name = sys.argv[3]

# Try to use PortRegistry if available
try:
    from iris_devtester.ports.registry import PortRegistry
    registry = PortRegistry()
    try:
        registry.release_port(project_path)
    except:
        pass
except:
    pass

# Manually register the port
registry_file = Path.home() / ".iris-devtester" / "port-registry.json"
registry_file.parent.mkdir(exist_ok=True)
if registry_file.exists():
    data = json.loads(registry_file.read_text())
else:
    data = {}
data[project_path] = {"port": host_port, "container": container_name}
registry_file.write_text(json.dumps(data, indent=2))
print(f"✅ Registered port {host_port} for project in registry")
EOF

# Show status
echo ""
echo "✅ Container Status:"
docker ps --filter "name=${CONTAINER_NAME}" --format "  Name: {{.Names}}\n  Status: {{.Status}}\n  Ports: {{.Ports}}"

echo ""
echo "✅ Connection Info:"
echo "  SuperServer: localhost:${HOST_PORT}"
echo "  Web Portal: http://localhost:$((HOST_PORT + 1000))"
echo "  Username: _SYSTEM"
echo "  Password: SYS"
echo ""
echo "✅ To use in tests:"
echo "  iris = IRISContainer.attach('${CONTAINER_NAME}')"
echo "  port = ${HOST_PORT}"
echo ""
echo "📝 To manage:"
echo "  Stop:   docker stop ${CONTAINER_NAME}"
echo "  Start:  docker start ${CONTAINER_NAME}"
echo "  Remove: docker rm -f ${CONTAINER_NAME}"
