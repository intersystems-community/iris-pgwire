"""
IPM (InterSystems Package Manager) module metadata model.

Represents metadata for ZPM package installation including lifecycle hooks,
Python dependencies, and version information.

Constitutional Requirements:
- Principle III (Phased Implementation): IPM packaging for deployment
- Principle V (Production Readiness): Proper versioning and dependencies

Feature: 018-add-dbapi-option
Data Model: Entity #5 - IPMModuleMetadata
"""

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class LifecyclePhase(str, Enum):
    """IPM module lifecycle phases."""

    SETUP = "Setup"  # Pre-installation setup
    COMPILE = "Compile"  # ObjectScript compilation
    ACTIVATE = "Activate"  # Post-installation activation
    RELOAD = "Reload"  # Module reload
    DEACTIVATE = "Deactivate"  # Pre-uninstall deactivation


class IPMModuleMetadata(BaseModel):
    """
    IPM module metadata for iris-pgwire package.

    Defines ZPM package structure including:
    - Module identification (name, version, description)
    - Python dependencies (requirements.txt)
    - ObjectScript lifecycle hooks (Installer.cls, Service.cls)
    - Installation phases (Setup, Activate, Deactivate)

    XML Structure:
    <Export>
      <Document name="iris-pgwire.ZPM">
        <Module>
          <Name>iris-pgwire</Name>
          <Version>1.0.0</Version>
          <Description>PostgreSQL wire protocol server for IRIS</Description>
          <Invoke Phase="Setup" Class="IrisPGWire.Installer" Method="InstallPythonDeps" />
          <Invoke Phase="Activate" Class="IrisPGWire.Service" Method="Start" />
          <Invoke Phase="Deactivate" Class="IrisPGWire.Service" Method="Stop" />
        </Module>
      </Document>
    </Export>
    """

    # Module Identification
    name: str = Field(default="iris-pgwire", description="ZPM package name")
    version: str = Field(description="Semantic version (e.g., 1.0.0)")
    description: str = Field(
        default="PostgreSQL wire protocol server for InterSystems IRIS with vector support",
        description="Package description",
    )

    # Python Dependencies
    python_requirements: list[str] = Field(
        default_factory=list, description="List of Python package requirements"
    )
    requirements_file: Path | None = Field(
        default=None, description="Path to requirements.txt file"
    )

    # ObjectScript Classes
    installer_class: str = Field(default="IrisPGWire.Installer", description="Installer class name")
    service_class: str = Field(default="IrisPGWire.Service", description="Service class name")

    # Lifecycle Hooks
    setup_method: str = Field(
        default="InstallPythonDeps",
        description="Method to call during Setup phase (Python dependency installation)",
    )
    activate_method: str = Field(
        default="Start", description="Method to call during Activate phase (start TCP server)"
    )
    deactivate_method: str = Field(
        default="Stop", description="Method to call during Deactivate phase (stop TCP server)"
    )

    # Package Metadata
    author: str = Field(default="InterSystems Community", description="Package author")
    keywords: list[str] = Field(
        default_factory=lambda: ["postgresql", "pgwire", "vector", "iris"],
        description="Package keywords",
    )

    # Sources Configuration
    sources_root: str = Field(default="ipm", description="Root directory for package sources")

    @field_validator("version")
    @classmethod
    def validate_semver(cls, v: str) -> str:
        """Validate version follows semantic versioning."""
        parts = v.split(".")
        if len(parts) != 3:
            raise ValueError(f"Version must be semantic version (e.g., 1.0.0), got: {v}")

        for part in parts:
            if not part.isdigit():
                raise ValueError(f"Version components must be numeric (e.g., 1.0.0), got: {v}")

        return v

    @field_validator("python_requirements")
    @classmethod
    def validate_requirements_format(cls, v: list[str]) -> list[str]:
        """Validate Python requirements use package>=version format."""
        for req in v:
            if ">" not in req and "=" not in req and "<" not in req:
                # Allow package names without version specifiers
                continue

            # Validate has version operator
            if not any(op in req for op in [">=", "<=", "==", ">", "<", "~="]):
                raise ValueError(
                    f"Requirement must include version operator (e.g., package>=1.0.0): {req}"
                )

        return v

    def to_module_xml(self) -> str:
        """
        Generate module.xml content for IPM package.

        Returns:
            XML string for ZPM module definition
        """
        requirements_xml = ""
        if self.python_requirements:
            req_list = "\n".join([f"    {req}" for req in self.python_requirements])
            requirements_xml = f"""
  <PythonRequirements>
{req_list}
  </PythonRequirements>"""

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<Export generator="Cache" version="25">
  <Document name="{self.name}.ZPM">
    <Module>
      <Name>{self.name}</Name>
      <Version>{self.version}</Version>
      <Description>{self.description}</Description>
      <Author>{self.author}</Author>
      <Keywords>{','.join(self.keywords)}</Keywords>
      <SourcesRoot>{self.sources_root}</SourcesRoot>
{requirements_xml}
      <Invoke Phase="Setup" Class="{self.installer_class}" Method="{self.setup_method}"/>
      <Invoke Phase="Activate" Class="{self.service_class}" Method="{self.activate_method}"/>
      <Invoke Phase="Deactivate" Class="{self.service_class}" Method="{self.deactivate_method}"/>
    </Module>
  </Document>
</Export>
"""

    def to_requirements_txt(self) -> str:
        """
        Generate requirements.txt content.

        Returns:
            requirements.txt formatted string
        """
        if not self.python_requirements:
            return ""

        return "\n".join(self.python_requirements) + "\n"

    def validate_package_structure(self, base_path: Path) -> dict:
        """
        Validate IPM package directory structure.

        Expected structure:
        ipm/
        ├── module.xml
        ├── requirements.txt
        └── IrisPGWire/
            ├── Installer.cls
            └── Service.cls

        Args:
            base_path: Root directory of project

        Returns:
            Dict with validation results
        """
        ipm_path = base_path / self.sources_root
        errors = []
        warnings = []

        # Check module.xml
        if not (ipm_path / "module.xml").exists():
            errors.append("module.xml not found in ipm/ directory")

        # Check requirements.txt
        if not (ipm_path / "requirements.txt").exists():
            warnings.append("requirements.txt not found - Python dependencies won't be installed")

        # Check ObjectScript classes
        cls_dir = ipm_path / "IrisPGWire"
        if not cls_dir.exists():
            errors.append("IrisPGWire/ directory not found")
        else:
            if not (cls_dir / "Installer.cls").exists():
                errors.append("Installer.cls not found")
            if not (cls_dir / "Service.cls").exists():
                errors.append("Service.cls not found")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "checked_path": str(ipm_path),
        }

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "name": "iris-pgwire",
                "version": "1.0.0",
                "description": "PostgreSQL wire protocol server for InterSystems IRIS",
                "python_requirements": [
                    "intersystems-irispython>=5.1.2",
                    "opentelemetry-api>=1.20.0",
                    "opentelemetry-sdk>=1.20.0",
                    "pydantic>=2.0.0",
                ],
                "requirements_file": "ipm/requirements.txt",
                "installer_class": "IrisPGWire.Installer",
                "service_class": "IrisPGWire.Service",
                "setup_method": "InstallPythonDeps",
                "activate_method": "Start",
                "deactivate_method": "Stop",
                "author": "InterSystems Community",
                "keywords": ["postgresql", "pgwire", "vector", "iris"],
                "sources_root": "ipm",
            }
        }
