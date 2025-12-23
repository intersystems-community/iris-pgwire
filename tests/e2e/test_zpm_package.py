"""
E2E tests for ZPM package installation and operation.

These tests verify that the iris-pgwire ZPM package:
1. Has valid module.xml manifest
2. Does NOT auto-start server after installation
3. Can be manually started via IrisPGWire.Service
4. Properly stops on deactivation

Feature: 027-open-exchange
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


class TestZPMPackageManifest:
    """Test the ZPM package manifest (module.xml) structure and configuration."""

    @pytest.fixture
    def module_xml_path(self):
        """Get path to module.xml."""
        repo_root = Path(__file__).parent.parent.parent
        return repo_root / "ipm" / "module.xml"

    @pytest.fixture
    def module_tree(self, module_xml_path):
        """Parse the module.xml file."""
        assert module_xml_path.exists(), f"module.xml not found at {module_xml_path}"
        return ET.parse(module_xml_path)

    def test_module_xml_exists(self, module_xml_path):
        """Verify module.xml exists in ipm/ directory."""
        assert module_xml_path.exists(), "module.xml should exist in ipm/ directory"

    def test_module_xml_valid_xml(self, module_xml_path):
        """Verify module.xml is valid XML."""
        try:
            ET.parse(module_xml_path)
        except ET.ParseError as e:
            pytest.fail(f"module.xml is not valid XML: {e}")

    def test_module_has_required_elements(self, module_tree):
        """Verify module.xml has all required elements."""
        root = module_tree.getroot()
        module = root.find(".//Module")
        assert module is not None, "Module element should exist"

        # Required elements
        name = module.find("Name")
        assert name is not None, "Name element required"
        assert (
            name.text == "iris-pgwire"
        ), f"Package name should be 'iris-pgwire', got '{name.text}'"

        version = module.find("Version")
        assert version is not None, "Version element required"

        description = module.find("Description")
        assert description is not None, "Description element required"
        assert len(description.text) >= 50, "Description should be at least 50 characters"

    def test_system_requirements_iris_2024(self, module_tree):
        """Verify IRIS 2024.1+ is required."""
        root = module_tree.getroot()
        sys_req = root.find(".//SystemRequirements/Version")
        assert sys_req is not None, "SystemRequirements/Version should exist"
        assert (
            "2024.1" in sys_req.text or "IRIS>=2024" in sys_req.text
        ), f"Should require IRIS 2024.1+, got '{sys_req.text}'"

    def test_no_activate_phase_auto_start(self, module_tree):
        """Verify server does NOT auto-start (no Activate phase with Start)."""
        root = module_tree.getroot()

        # Find all Invoke elements
        invokes = root.findall(".//Invoke")

        for invoke in invokes:
            phase = invoke.get("Phase", "")
            method = invoke.get("Method", "")

            # There should be NO Activate phase that calls Start
            if phase == "Activate" and method == "Start":
                pytest.fail(
                    "module.xml should NOT have Activate phase with Start method. "
                    "Server should be started manually by user."
                )

    def test_has_deactivate_phase_stop(self, module_tree):
        """Verify Deactivate phase exists for cleanup."""
        root = module_tree.getroot()
        invokes = root.findall(".//Invoke")

        has_deactivate_stop = False
        for invoke in invokes:
            phase = invoke.get("Phase", "")
            method = invoke.get("Method", "")
            if phase == "Deactivate" and method == "Stop":
                has_deactivate_stop = True
                break

        assert (
            has_deactivate_stop
        ), "module.xml should have Deactivate phase with Stop method for cleanup"

    def test_has_setup_phase_install_deps(self, module_tree):
        """Verify Setup phase installs Python dependencies."""
        root = module_tree.getroot()
        invokes = root.findall(".//Invoke")

        has_setup_install = False
        for invoke in invokes:
            phase = invoke.get("Phase", "")
            method = invoke.get("Method", "")
            if phase == "Setup" and "Install" in method:
                has_setup_install = True
                break

        assert (
            has_setup_install
        ), "module.xml should have Setup phase to install Python dependencies"


class TestZPMPackageFiles:
    """Test the ZPM package file structure."""

    @pytest.fixture
    def ipm_dir(self):
        """Get path to ipm/ directory."""
        repo_root = Path(__file__).parent.parent.parent
        return repo_root / "ipm"

    def test_requirements_txt_exists(self, ipm_dir):
        """Verify requirements.txt exists for Python dependencies."""
        req_file = ipm_dir / "requirements.txt"
        assert req_file.exists(), "requirements.txt should exist in ipm/ directory"

    def test_requirements_has_core_deps(self, ipm_dir):
        """Verify requirements.txt has core dependencies."""
        req_file = ipm_dir / "requirements.txt"
        content = req_file.read_text()

        # Check for core dependencies
        assert "structlog" in content, "structlog should be in requirements"
        assert "cryptography" in content, "cryptography should be in requirements"
        assert "pydantic" in content, "pydantic should be in requirements"

    def test_objectscript_classes_exist(self, ipm_dir):
        """Verify ObjectScript classes exist."""
        cls_dir = ipm_dir / "IrisPGWire"
        assert cls_dir.exists(), "IrisPGWire/ directory should exist"

        installer_cls = cls_dir / "Installer.cls"
        assert installer_cls.exists(), "Installer.cls should exist"

        service_cls = cls_dir / "Service.cls"
        assert service_cls.exists(), "Service.cls should exist"

    def test_service_cls_has_manual_start(self, ipm_dir):
        """Verify Service.cls has Start method for manual invocation."""
        service_cls = ipm_dir / "IrisPGWire" / "Service.cls"
        content = service_cls.read_text()

        assert "ClassMethod Start()" in content, "Service.cls should have Start() method"
        assert "ClassMethod Stop()" in content, "Service.cls should have Stop() method"
        assert "ClassMethod GetStatus()" in content, "Service.cls should have GetStatus() method"


class TestReadmeDocumentation:
    """Test README.md has required ZPM documentation."""

    @pytest.fixture
    def readme_path(self):
        """Get path to README.md."""
        repo_root = Path(__file__).parent.parent.parent
        return repo_root / "README.md"

    @pytest.fixture
    def readme_content(self, readme_path):
        """Read README.md content."""
        return readme_path.read_text()

    def test_readme_has_zpm_section(self, readme_content):
        """Verify README has ZPM installation section."""
        assert "ZPM Installation" in readme_content, "README should have 'ZPM Installation' section"

    def test_readme_has_zpm_install_command(self, readme_content):
        """Verify README shows ZPM install command."""
        assert (
            'zpm "install iris-pgwire"' in readme_content
        ), "README should show ZPM install command"

    def test_readme_has_manual_start_command(self, readme_content):
        """Verify README shows manual start command."""
        assert (
            "IrisPGWire.Service" in readme_content
        ), "README should reference IrisPGWire.Service for manual start"
        assert "Start()" in readme_content, "README should show Start() command"

    def test_readme_has_architecture_diagram(self, readme_content):
        """Verify README has architecture diagram."""
        # Check for ASCII art diagram markers
        assert (
            "PostgreSQL Clients" in readme_content
        ), "README should have architecture diagram with PostgreSQL Clients"
        assert (
            "IRIS PGWire Server" in readme_content
        ), "README should have architecture diagram with IRIS PGWire Server"
        assert (
            "Wire Proto" in readme_content or "Protocol" in readme_content
        ), "README should show wire protocol in architecture"


class TestDockerQuickStart:
    """Test Docker quick start configuration."""

    @pytest.fixture
    def docker_compose_path(self):
        """Get path to docker-compose.yml."""
        repo_root = Path(__file__).parent.parent.parent
        return repo_root / "docker-compose.yml"

    def test_docker_compose_exists(self, docker_compose_path):
        """Verify docker-compose.yml exists."""
        assert docker_compose_path.exists(), "docker-compose.yml should exist"

    def test_docker_compose_valid_yaml(self, docker_compose_path):
        """Verify docker-compose.yml is valid YAML."""
        try:
            import yaml

            with open(docker_compose_path) as f:
                yaml.safe_load(f)
        except ImportError:
            pytest.skip("PyYAML not installed")
        except yaml.YAMLError as e:
            pytest.fail(f"docker-compose.yml is not valid YAML: {e}")


class TestLicenseAndMetadata:
    """Test license and metadata files exist."""

    @pytest.fixture
    def repo_root(self):
        """Get repository root."""
        return Path(__file__).parent.parent.parent

    def test_license_file_exists(self, repo_root):
        """Verify LICENSE file exists."""
        license_file = repo_root / "LICENSE"
        assert license_file.exists(), "LICENSE file should exist"

    def test_license_is_mit(self, repo_root):
        """Verify LICENSE is MIT."""
        license_file = repo_root / "LICENSE"
        content = license_file.read_text()
        assert "MIT" in content, "LICENSE should be MIT"

    def test_known_limitations_exists(self, repo_root):
        """Verify KNOWN_LIMITATIONS.md exists."""
        limitations = repo_root / "KNOWN_LIMITATIONS.md"
        assert limitations.exists(), "KNOWN_LIMITATIONS.md should exist"

    def test_changelog_exists(self, repo_root):
        """Verify CHANGELOG.md exists."""
        changelog = repo_root / "CHANGELOG.md"
        assert changelog.exists(), "CHANGELOG.md should exist"
