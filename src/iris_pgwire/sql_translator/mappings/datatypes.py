"""
IRIS Data Type Mappings

Comprehensive mappings between IRIS data types and PostgreSQL data types.
Handles size specifications, constraints, and type-specific conversions.

Constitutional Compliance: Accurate type mappings ensuring data integrity.
"""

import re

from ..models import TypeMapping


class IRISDataTypeRegistry:
    """Registry for IRIS to PostgreSQL data type mappings"""

    def __init__(self):
        self._mappings: dict[str, TypeMapping] = {}
        self._size_patterns: dict[str, str] = {}
        self._initialize_mappings()

    def _initialize_mappings(self):
        """Initialize all IRIS data type mappings"""
        # Core data types
        self._add_numeric_types()
        self._add_string_types()
        self._add_datetime_types()
        self._add_binary_types()
        self._add_boolean_types()
        self._add_iris_specific_types()
        self._add_collection_types()

    def _add_numeric_types(self):
        """Add numeric data type mappings"""

        # INTEGER types
        self.add_mapping(
            TypeMapping(
                iris_type="INTEGER",
                postgresql_type="INTEGER",
                confidence=1.0,
                notes="Direct mapping - 4 bytes signed integer",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="INT",
                postgresql_type="INTEGER",
                confidence=1.0,
                notes="Alias for INTEGER",
            )
        )

        # BIGINT
        self.add_mapping(
            TypeMapping(
                iris_type="BIGINT",
                postgresql_type="BIGINT",
                confidence=1.0,
                notes="Direct mapping - 8 bytes signed integer",
            )
        )

        # SMALLINT
        self.add_mapping(
            TypeMapping(
                iris_type="SMALLINT",
                postgresql_type="SMALLINT",
                confidence=1.0,
                notes="Direct mapping - 2 bytes signed integer",
            )
        )

        # TINYINT (IRIS specific)
        self.add_mapping(
            TypeMapping(
                iris_type="TINYINT",
                postgresql_type="SMALLINT",
                confidence=0.9,
                notes="Maps to SMALLINT - PostgreSQL doesn't have TINYINT",
            )
        )

        # DECIMAL/NUMERIC
        self.add_mapping(
            TypeMapping(
                iris_type="DECIMAL",
                postgresql_type="DECIMAL",
                size_mapping={"precision": "precision", "scale": "scale"},
                confidence=1.0,
                notes="Direct mapping with precision and scale",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="NUMERIC",
                postgresql_type="NUMERIC",
                size_mapping={"precision": "precision", "scale": "scale"},
                confidence=1.0,
                notes="Direct mapping with precision and scale",
            )
        )

        # MONEY
        self.add_mapping(
            TypeMapping(
                iris_type="MONEY",
                postgresql_type="MONEY",
                confidence=0.9,
                notes="PostgreSQL MONEY type - different precision than IRIS",
            )
        )

        # FLOAT/REAL
        self.add_mapping(
            TypeMapping(
                iris_type="FLOAT",
                postgresql_type="REAL",
                confidence=0.9,
                notes="Maps to REAL - single precision floating point",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="REAL",
                postgresql_type="REAL",
                confidence=1.0,
                notes="Direct mapping - single precision floating point",
            )
        )

        # DOUBLE
        self.add_mapping(
            TypeMapping(
                iris_type="DOUBLE",
                postgresql_type="DOUBLE PRECISION",
                confidence=1.0,
                notes="Direct mapping to double precision floating point",
            )
        )

    def _add_string_types(self):
        """Add string/character data type mappings"""

        # VARCHAR
        self.add_mapping(
            TypeMapping(
                iris_type="VARCHAR",
                postgresql_type="VARCHAR",
                size_mapping={"length": "length"},
                confidence=1.0,
                notes="Direct mapping with length specification",
            )
        )

        # CHAR
        self.add_mapping(
            TypeMapping(
                iris_type="CHAR",
                postgresql_type="CHAR",
                size_mapping={"length": "length"},
                confidence=1.0,
                notes="Direct mapping - fixed length character",
            )
        )

        # TEXT types
        self.add_mapping(
            TypeMapping(
                iris_type="LONGVARCHAR",
                postgresql_type="TEXT",
                confidence=1.0,
                notes="Maps to PostgreSQL TEXT for long strings",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="CLOB",
                postgresql_type="TEXT",
                confidence=0.9,
                notes="Character LOB maps to TEXT",
            )
        )

        # IRIS specific string types
        self.add_mapping(
            TypeMapping(
                iris_type="%String",
                postgresql_type="VARCHAR",
                size_mapping={"maxlen": "length"},
                confidence=0.8,
                notes="IRIS %String class maps to VARCHAR",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="%Text",
                postgresql_type="TEXT",
                confidence=0.8,
                notes="IRIS %Text class maps to TEXT",
            )
        )

    def _add_datetime_types(self):
        """Add date/time data type mappings"""

        # DATE
        self.add_mapping(
            TypeMapping(
                iris_type="DATE",
                postgresql_type="DATE",
                confidence=1.0,
                notes="Direct mapping - date without time",
            )
        )

        # TIME
        self.add_mapping(
            TypeMapping(
                iris_type="TIME",
                postgresql_type="TIME",
                size_mapping={"precision": "precision"},
                confidence=1.0,
                notes="Direct mapping with optional precision",
            )
        )

        # TIMESTAMP
        self.add_mapping(
            TypeMapping(
                iris_type="TIMESTAMP",
                postgresql_type="TIMESTAMP",
                size_mapping={"precision": "precision"},
                confidence=1.0,
                notes="Direct mapping with optional precision",
            )
        )

        # IRIS specific datetime types
        self.add_mapping(
            TypeMapping(
                iris_type="%Date",
                postgresql_type="DATE",
                confidence=0.8,
                notes="IRIS %Date class maps to DATE",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="%Time",
                postgresql_type="TIME",
                confidence=0.8,
                notes="IRIS %Time class maps to TIME",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="%TimeStamp",
                postgresql_type="TIMESTAMP",
                confidence=0.8,
                notes="IRIS %TimeStamp class maps to TIMESTAMP",
            )
        )

        # DATETIME (non-standard but common)
        self.add_mapping(
            TypeMapping(
                iris_type="DATETIME",
                postgresql_type="TIMESTAMP",
                confidence=0.9,
                notes="Maps to TIMESTAMP",
            )
        )

    def _add_binary_types(self):
        """Add binary data type mappings"""

        # BINARY/VARBINARY
        self.add_mapping(
            TypeMapping(
                iris_type="VARBINARY",
                postgresql_type="BYTEA",
                confidence=1.0,
                notes="Variable length binary data maps to BYTEA",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="BINARY",
                postgresql_type="BYTEA",
                confidence=0.9,
                notes="Fixed length binary maps to BYTEA",
            )
        )

        # BLOB
        self.add_mapping(
            TypeMapping(
                iris_type="BLOB",
                postgresql_type="BYTEA",
                confidence=0.9,
                notes="Binary LOB maps to BYTEA",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="LONGVARBINARY",
                postgresql_type="BYTEA",
                confidence=1.0,
                notes="Long variable binary maps to BYTEA",
            )
        )

        # IRIS specific binary types
        self.add_mapping(
            TypeMapping(
                iris_type="%Binary",
                postgresql_type="BYTEA",
                confidence=0.8,
                notes="IRIS %Binary class maps to BYTEA",
            )
        )

    def _add_boolean_types(self):
        """Add boolean data type mappings"""

        # BOOLEAN
        self.add_mapping(
            TypeMapping(
                iris_type="BOOLEAN",
                postgresql_type="BOOLEAN",
                confidence=1.0,
                notes="Direct mapping",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="BOOL",
                postgresql_type="BOOLEAN",
                confidence=1.0,
                notes="Alias for BOOLEAN",
            )
        )

        # BIT
        self.add_mapping(
            TypeMapping(
                iris_type="BIT",
                postgresql_type="BOOLEAN",
                confidence=0.9,
                notes="Single bit maps to BOOLEAN",
            )
        )

        # IRIS specific boolean
        self.add_mapping(
            TypeMapping(
                iris_type="%Boolean",
                postgresql_type="BOOLEAN",
                confidence=0.8,
                notes="IRIS %Boolean class maps to BOOLEAN",
            )
        )

    def _add_iris_specific_types(self):
        """Add IRIS-specific data types"""

        # List types
        self.add_mapping(
            TypeMapping(
                iris_type="%List",
                postgresql_type="JSONB",
                confidence=0.7,
                notes="IRIS %List maps to JSONB array",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="%ArrayOfDataTypes",
                postgresql_type="JSONB",
                confidence=0.7,
                notes="IRIS array types map to JSONB",
            )
        )

        # Stream types
        self.add_mapping(
            TypeMapping(
                iris_type="%Stream",
                postgresql_type="TEXT",
                confidence=0.6,
                notes="IRIS %Stream maps to TEXT - functionality differs",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="%GlobalCharacterStream",
                postgresql_type="TEXT",
                confidence=0.6,
                notes="Character stream maps to TEXT",
            )
        )

        self.add_mapping(
            TypeMapping(
                iris_type="%GlobalBinaryStream",
                postgresql_type="BYTEA",
                confidence=0.6,
                notes="Binary stream maps to BYTEA",
            )
        )

        # Status types
        self.add_mapping(
            TypeMapping(
                iris_type="%Status",
                postgresql_type="INTEGER",
                confidence=0.7,
                notes="IRIS %Status maps to INTEGER",
            )
        )

        # OID type
        self.add_mapping(
            TypeMapping(
                iris_type="%Oid",
                postgresql_type="BIGINT",
                confidence=0.7,
                notes="IRIS %Oid maps to BIGINT",
            )
        )

        # VECTOR type (for AI/ML workloads)
        self.add_mapping(
            TypeMapping(
                iris_type="VECTOR",
                postgresql_type="VECTOR",
                size_mapping={"dimensions": "dimensions"},
                confidence=0.8,
                notes="IRIS VECTOR maps to pgvector extension type",
            )
        )

    def _add_collection_types(self):
        """Add collection and structured data types"""

        # JSON types
        self.add_mapping(
            TypeMapping(
                iris_type="JSON",
                postgresql_type="JSONB",
                confidence=1.0,
                notes="JSON data maps to JSONB for better performance",
            )
        )

        # XML type
        self.add_mapping(
            TypeMapping(
                iris_type="XML",
                postgresql_type="XML",
                confidence=0.9,
                notes="Direct mapping to PostgreSQL XML type",
            )
        )

        # UUID type
        self.add_mapping(
            TypeMapping(
                iris_type="UUID",
                postgresql_type="UUID",
                confidence=1.0,
                notes="Direct mapping to PostgreSQL UUID type",
            )
        )

        # Interval types
        self.add_mapping(
            TypeMapping(
                iris_type="INTERVAL",
                postgresql_type="INTERVAL",
                confidence=0.9,
                notes="Maps to PostgreSQL INTERVAL - syntax may differ",
            )
        )

    def add_mapping(self, mapping: TypeMapping):
        """Add a data type mapping to the registry"""
        self._mappings[mapping.iris_type] = mapping

    def get_mapping(self, iris_type: str) -> TypeMapping | None:
        """Get mapping for an IRIS data type"""
        # Try exact match first
        if iris_type in self._mappings:
            return self._mappings[iris_type]

        # Try case-insensitive match
        iris_type_upper = iris_type.upper()
        for key, mapping in self._mappings.items():
            if key.upper() == iris_type_upper:
                return mapping

        return None

    def has_mapping(self, iris_type: str) -> bool:
        """Check if mapping exists for IRIS data type"""
        return self.get_mapping(iris_type) is not None

    def translate_type_with_size(self, iris_type_spec: str) -> tuple[str, float]:
        """
        Translate IRIS type specification with size/precision
        Returns (postgresql_type_spec, confidence)
        """
        # Parse type specification
        type_info = self._parse_type_specification(iris_type_spec)
        base_type = type_info["base_type"]
        parameters = type_info["parameters"]

        # Get base mapping
        mapping = self.get_mapping(base_type)
        if not mapping:
            return iris_type_spec, 0.0  # No translation available

        # Build PostgreSQL type specification
        pg_type = mapping.postgresql_type
        confidence = mapping.confidence

        # Apply size/precision mappings
        if parameters and mapping.size_mapping:
            pg_type = self._apply_size_mapping(pg_type, parameters, mapping.size_mapping)

        return pg_type, confidence

    def _parse_type_specification(self, type_spec: str) -> dict[str, any]:
        """Parse IRIS type specification like VARCHAR(50) or DECIMAL(10,2)"""
        # Pattern to match type with optional parameters
        pattern = (
            r"^([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*(?:\(\s*([^)]+)\s*\))?$"
        )
        match = re.match(pattern, type_spec.strip())

        if not match:
            return {"base_type": type_spec, "parameters": []}

        base_type = match.group(1)
        param_str = match.group(2)

        parameters = []
        if param_str:
            # Split parameters by comma
            param_parts = [p.strip() for p in param_str.split(",")]
            for part in param_parts:
                # Try to convert to int, fallback to string
                try:
                    parameters.append(int(part))
                except ValueError:
                    parameters.append(part)

        return {"base_type": base_type, "parameters": parameters}

    def _apply_size_mapping(
        self, pg_type: str, parameters: list, size_mapping: dict[str, str]
    ) -> str:
        """Apply size/precision parameters to PostgreSQL type"""
        if not parameters:
            return pg_type

        # For types with single parameter (like VARCHAR(50))
        if len(parameters) == 1:
            if "length" in size_mapping:
                return f"{pg_type}({parameters[0]})"
            elif "precision" in size_mapping:
                return f"{pg_type}({parameters[0]})"

        # For types with two parameters (like DECIMAL(10,2))
        elif len(parameters) == 2:
            if "precision" in size_mapping and "scale" in size_mapping:
                return f"{pg_type}({parameters[0]},{parameters[1]})"

        # Default: append all parameters
        param_str = ",".join(str(p) for p in parameters)
        return f"{pg_type}({param_str})"

    def get_all_iris_types(self) -> set[str]:
        """Get all supported IRIS data types"""
        return set(self._mappings.keys())

    def get_mappings_by_confidence(self, min_confidence: float = 0.0) -> list[TypeMapping]:
        """Get mappings filtered by minimum confidence level"""
        return [
            mapping for mapping in self._mappings.values() if mapping.confidence >= min_confidence
        ]

    def get_type_categories(self) -> dict[str, list[str]]:
        """Get data types organized by category"""
        categories = {
            "numeric": [],
            "string": [],
            "datetime": [],
            "binary": [],
            "boolean": [],
            "iris_specific": [],
            "collection": [],
        }

        for type_name in self._mappings.keys():
            type_upper = type_name.upper()

            if any(
                x in type_upper
                for x in ["INT", "DECIMAL", "NUMERIC", "FLOAT", "REAL", "DOUBLE", "MONEY"]
            ):
                categories["numeric"].append(type_name)
            elif any(x in type_upper for x in ["VARCHAR", "CHAR", "TEXT", "CLOB", "STRING"]):
                categories["string"].append(type_name)
            elif any(x in type_upper for x in ["DATE", "TIME", "TIMESTAMP", "DATETIME"]):
                categories["datetime"].append(type_name)
            elif any(x in type_upper for x in ["BINARY", "VARBINARY", "BLOB", "BYTEA"]):
                categories["binary"].append(type_name)
            elif any(x in type_upper for x in ["BOOLEAN", "BOOL", "BIT"]):
                categories["boolean"].append(type_name)
            elif type_name.startswith("%"):
                categories["iris_specific"].append(type_name)
            elif any(x in type_upper for x in ["JSON", "XML", "UUID", "INTERVAL", "VECTOR"]):
                categories["collection"].append(type_name)

        return categories

    def search_types(self, pattern: str) -> list[TypeMapping]:
        """Search for data types matching pattern"""
        pattern_lower = pattern.lower()
        matches = []

        for type_name, mapping in self._mappings.items():
            if (
                pattern_lower in type_name.lower()
                or pattern_lower in mapping.postgresql_type.lower()
                or pattern_lower in mapping.notes.lower()
            ):
                matches.append(mapping)

        return matches

    def validate_type_conversion(self, iris_type: str, postgresql_type: str) -> dict[str, any]:
        """Validate if type conversion is safe and provide warnings"""
        mapping = self.get_mapping(iris_type)
        if not mapping:
            return {
                "valid": False,
                "confidence": 0.0,
                "warnings": [f"No mapping found for IRIS type: {iris_type}"],
            }

        warnings = []
        confidence = mapping.confidence

        # Check for potential data loss
        if confidence < 0.8:
            warnings.append(f"Low confidence mapping: {iris_type} -> {postgresql_type}")

        # Specific conversion warnings
        if iris_type.upper() == "TINYINT" and postgresql_type.upper() == "SMALLINT":
            warnings.append("TINYINT range (0-255) fits within SMALLINT but uses more storage")

        if "MONEY" in iris_type.upper():
            warnings.append("MONEY type has different precision in PostgreSQL vs IRIS")

        if iris_type.startswith("%"):
            warnings.append(f"IRIS class type {iris_type} mapped to basic PostgreSQL type")

        return {
            "valid": True,
            "confidence": confidence,
            "warnings": warnings,
            "recommended_type": mapping.postgresql_type,
        }

    def get_mapping_stats(self) -> dict[str, any]:
        """Get statistics about data type mappings"""
        total_mappings = len(self._mappings)
        high_confidence = len([m for m in self._mappings.values() if m.confidence >= 0.9])
        medium_confidence = len([m for m in self._mappings.values() if 0.7 <= m.confidence < 0.9])
        low_confidence = len([m for m in self._mappings.values() if m.confidence < 0.7])

        categories = self.get_type_categories()
        category_counts = {cat: len(types) for cat, types in categories.items()}

        return {
            "total_mappings": total_mappings,
            "confidence_distribution": {
                "high": high_confidence,
                "medium": medium_confidence,
                "low": low_confidence,
            },
            "category_counts": category_counts,
            "average_confidence": sum(m.confidence for m in self._mappings.values())
            / total_mappings,
        }


# Global registry instance
_datatype_registry = IRISDataTypeRegistry()


def get_datatype_registry() -> IRISDataTypeRegistry:
    """Get the global data type registry instance"""
    return _datatype_registry


def get_type_mapping(iris_type: str) -> TypeMapping | None:
    """Get mapping for an IRIS data type (convenience function)"""
    return _datatype_registry.get_mapping(iris_type)


def has_type_mapping(iris_type: str) -> bool:
    """Check if mapping exists for IRIS data type (convenience function)"""
    return _datatype_registry.has_mapping(iris_type)


def translate_type_specification(iris_type_spec: str) -> tuple[str, float]:
    """Translate IRIS type specification to PostgreSQL (convenience function)"""
    return _datatype_registry.translate_type_with_size(iris_type_spec)


# Export main components
__all__ = [
    "IRISDataTypeRegistry",
    "get_datatype_registry",
    "get_type_mapping",
    "has_type_mapping",
    "translate_type_specification",
]
