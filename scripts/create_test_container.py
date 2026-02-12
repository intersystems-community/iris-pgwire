#!/usr/bin/env python3
"""Create the iris-pgwire-test container with proper port mapping."""

import sys
from pathlib import Path
from iris_devtester import IRISContainer
from iris_devtester.ports.registry import PortRegistry


def main():
    project_path = Path(__file__).parent.parent

    # Use a high port to avoid conflicts with other IRIS containers
    # Ports 1972-1980 are commonly taken by other test containers
    preferred_port = 21972

    # Create port registry with expanded range to include 21972
    # Default range is (1972, 1981), we need to expand it
    registry = PortRegistry(port_range=(21972, 21982))

    # Release any stale allocation for this project
    try:
        registry.release_port(str(project_path))
        print(f"Released any existing port allocation for {project_path.name}")
    except Exception:
        pass

    try:
        # Create container with specific port
        # Must pass project_path so port can be tracked per-project
        container = IRISContainer.community(
            project_path=str(project_path),
            port_registry=registry,
            preferred_port=preferred_port,
            username="_SYSTEM",
            password="SYS",
        )

        # Set explicit container name
        container = container.with_name("iris-pgwire-test")

        # Start the container
        container.__enter__()

        # Get the assigned port
        port = container.get_exposed_port(1972)
        name = container.get_container_name()

        print(f"✅ Container created: {name}")
        print(f"✅ IRIS SuperServer port: {port}")
        print(f"✅ Use in tests: IRISContainer.attach('{name}')")
        print(f"\nTo use this container, tests will attach via:")
        print(f"  iris = IRISContainer.attach('{name}')")
        print(f"  port = iris.get_exposed_port(1972)")
        print(f"\nContainer will remain running until explicitly stopped.")
        print(f"To stop: idt container stop {name}")
        print(f"To remove: idt container remove {name}")

        # NOTE: We don't call __exit__ so container stays running
        # The container is managed by Docker and will persist

        return 0

    except Exception as e:
        print(f"❌ Failed to create container: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
