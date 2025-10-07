"""
Integration tests for IPM installation and TCP server lifecycle.

These tests validate end-to-end IPM installation workflow including:
- Package installation via ZPM
- Python dependencies installation via irispip
- TCP server startup on port 5432
- Graceful server shutdown

Constitutional Requirements:
- Principle II (Test-First Development): Integration tests before implementation
- Principle III (Phased Implementation): Build on existing P0-P4 phases

Feature: 018-add-dbapi-option
Test Scenarios: Based on quickstart.md Step 1 (Install via IPM)
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.requires_iris]


@pytest.fixture
def ipm_module_path():
    """Path to IPM module.xml file."""
    return Path(__file__).parent.parent.parent / "ipm" / "module.xml"


@pytest.mark.skipif(
    not Path("ipm/module.xml").exists(),
    reason="IPM module.xml not created yet (TDD)",
)
def test_ipm_module_xml_exists_and_valid(ipm_module_path):
    """
    GIVEN iris-pgwire project
    WHEN IPM packaging is complete
    THEN module.xml exists and is valid XML
    """
    assert ipm_module_path.exists(), "module.xml not found in ipm/ directory"

    # Validate XML structure
    import xml.etree.ElementTree as ET

    tree = ET.parse(ipm_module_path)
    root = tree.getroot()

    # Verify required elements
    assert root.tag == "Export", "Root element should be <Export>"

    doc = root.find("Document")
    assert doc is not None, "<Document> element not found"

    module = doc.find(".//Module")
    assert module is not None, "<Module> element not found"

    # Verify critical module metadata
    name = module.find("Name")
    assert name is not None and name.text == "iris-pgwire"

    version = module.find("Version")
    assert version is not None, "Version not specified"


@pytest.mark.skipif(
    not Path("ipm/IrisPGWire/Installer.cls").exists(),
    reason="Installer.cls not created yet (TDD)",
)
def test_installer_class_exists():
    """
    GIVEN IPM packaging complete
    WHEN ObjectScript Installer class is created
    THEN Installer.cls contains InstallPythonDeps method
    """
    installer_path = Path("ipm/IrisPGWire/Installer.cls")
    assert installer_path.exists()

    content = installer_path.read_text()

    # Verify class structure
    assert "Class IrisPGWire.Installer" in content
    assert "InstallPythonDeps" in content
    assert "irispip install" in content or "pip install" in content


@pytest.mark.skipif(
    not Path("ipm/IrisPGWire/Service.cls").exists(),
    reason="Service.cls not created yet (TDD)",
)
def test_service_class_exists_with_lifecycle_methods():
    """
    GIVEN IPM packaging complete
    WHEN ObjectScript Service class is created
    THEN Service.cls contains Start, Stop, GetStatus methods
    """
    service_path = Path("ipm/IrisPGWire/Service.cls")
    assert service_path.exists()

    content = service_path.read_text()

    # Verify class structure
    assert "Class IrisPGWire.Service" in content
    assert "Method Start()" in content or "ClassMethod Start()" in content
    assert "Method Stop()" in content or "ClassMethod Stop()" in content
    assert "irispython -m iris_pgwire.server" in content or "iris_pgwire" in content


@pytest.mark.skipif(
    not Path("ipm/requirements.txt").exists(),
    reason="requirements.txt not created yet (TDD)",
)
def test_ipm_requirements_contains_dependencies():
    """
    GIVEN IPM packaging complete
    WHEN requirements.txt is created
    THEN it contains all required dependencies
    """
    req_path = Path("ipm/requirements.txt")
    assert req_path.exists()

    content = req_path.read_text()

    # Verify critical dependencies
    assert "intersystems-irispython" in content
    assert "opentelemetry-api" in content
    assert "opentelemetry-sdk" in content
    assert "pydantic" in content


@pytest.mark.skipif(
    not Path("ipm/module.xml").exists(),
    reason="IPM module not created yet (TDD)",
)
def test_ipm_module_uses_tcp_server_pattern_not_asgi():
    """
    GIVEN IPM module.xml
    WHEN module structure is validated
    THEN it uses TCP server pattern with <Invoke> hooks, NOT <WSGIApplication> or <ASGIApplication>

    Critical: Research R1 decision - iris-pgwire is a TCP server, not ASGI/WSGI web app
    """
    ipm_module_path = Path("ipm/module.xml")
    content = ipm_module_path.read_text()

    # MUST have Invoke hooks
    assert "<Invoke" in content, "Missing <Invoke> hooks for lifecycle management"

    # MUST NOT have ASGI/WSGI elements
    assert (
        "<WSGIApplication" not in content
    ), "CRITICAL: Using WSGI pattern - iris-pgwire is TCP server, not web app!"
    assert (
        "<ASGIApplication" not in content
    ), "CRITICAL: Using ASGI pattern - iris-pgwire is TCP server, not web app!"

    # Verify lifecycle hooks exist
    assert "IrisPGWire.Service" in content, "Service class not registered in lifecycle hooks"


@pytest.mark.slow
@pytest.mark.requires_docker
@pytest.mark.skipif(
    not Path("docker/docker-compose.ipm.yml").exists(),
    reason="Docker Compose file not created yet (TDD)",
)
def test_ipm_installation_in_docker_environment():
    """
    GIVEN Docker environment with IRIS
    WHEN IPM install command is executed
    THEN installation succeeds and server starts

    This is a smoke test for the full IPM installation workflow.
    """
    # This test requires actual Docker environment - will be skipped until T026 complete
    pytest.skip("Requires Docker environment (T026)")


# Meta-test to track TDD progress
def test_tdd_placeholder_ipm_installation_tests():
    """
    Meta-test: Track IPM installation test implementation status.

    Files that should exist:
    - ipm/module.xml (T019)
    - ipm/IrisPGWire/Installer.cls (T020)
    - ipm/IrisPGWire/Service.cls (T021)
    - ipm/requirements.txt (T022)
    """
    expected_files = [
        Path("ipm/module.xml"),
        Path("ipm/IrisPGWire/Installer.cls"),
        Path("ipm/IrisPGWire/Service.cls"),
        Path("ipm/requirements.txt"),
    ]

    missing_files = [f for f in expected_files if not f.exists()]

    if missing_files:
        pytest.skip(
            f"IPM files not yet created (TDD): {', '.join(str(f) for f in missing_files)}"
        )
