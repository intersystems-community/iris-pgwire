"""
Package quality validation framework for iris-pgwire.

This module provides validators for package metadata, code quality,
security, and documentation completeness following Production Readiness
standards (Constitutional Principle V).
"""

# Import validators as they are implemented
try:
    from iris_pgwire.quality.package_metadata_validator import PackageMetadataValidator
except ImportError:
    PackageMetadataValidator = None  # type: ignore

try:
    from iris_pgwire.quality.code_quality_validator import CodeQualityValidator
except ImportError:
    CodeQualityValidator = None  # type: ignore

try:
    from iris_pgwire.quality.security_validator import SecurityValidator
except ImportError:
    SecurityValidator = None  # type: ignore

try:
    from iris_pgwire.quality.documentation_validator import DocumentationValidator
except ImportError:
    DocumentationValidator = None  # type: ignore

try:
    from iris_pgwire.quality.validator import PackageQualityValidator
except ImportError:
    PackageQualityValidator = None  # type: ignore

__all__ = [
    "PackageMetadataValidator",
    "CodeQualityValidator",
    "SecurityValidator",
    "DocumentationValidator",
    "PackageQualityValidator",
]
