"""
Identifier Normalizer for PostgreSQL-Compatible SQL (Feature 021)

Normalizes SQL identifiers for IRIS case sensitivity compatibility:
- Unquoted identifiers → UPPERCASE (IRIS standard)
- Quoted identifiers → Preserve exact case (SQL standard)

Constitutional Requirements:
- Part of < 5ms normalization overhead requirement
- Preserve PostgreSQL semantic compatibility
"""

import re
from typing import Tuple


class IdentifierNormalizer:
    """
    Normalizes SQL identifier case for IRIS compatibility.
    
    Implements the contract defined in:
    specs/021-postgresql-compatible-sql/contracts/sql_translator_interface.py
    """
    
    def __init__(self):
        """Initialize the identifier normalizer with compiled regex patterns"""
        # Pattern to match identifiers (both quoted and unquoted)
        # Matches: table names, column names, aliases, schema-qualified identifiers
        # Handles: "QuotedIdentifier", UnquotedIdentifier, schema.table, schema.table.column
        
        # Pattern explanation:
        # 1. Quoted identifier: "([^"]+)" - anything between double quotes
        # 2. Unquoted identifier: \b[a-zA-Z_][a-zA-Z0-9_]*\b - valid SQL identifier
        # This pattern captures identifiers but needs context awareness to avoid keywords
        
        self._identifier_pattern = re.compile(
            r'"([^"]+)"|(\b[a-zA-Z_][a-zA-Z0-9_]*\b)'
        )
        
        # SQL keywords that should NOT be uppercased in context
        # (They're already uppercase in normalized form, but this helps with selective normalization)
        self._sql_keywords = {
            'SELECT', 'FROM', 'WHERE', 'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP',
            'TABLE', 'INDEX', 'VIEW', 'INTO', 'VALUES', 'SET', 'JOIN', 'LEFT', 'RIGHT',
            'INNER', 'OUTER', 'ON', 'AND', 'OR', 'NOT', 'NULL', 'AS', 'ORDER', 'BY',
            'GROUP', 'HAVING', 'LIMIT', 'OFFSET', 'UNION', 'INTERSECT', 'EXCEPT',
            'PRIMARY', 'KEY', 'FOREIGN', 'REFERENCES', 'CONSTRAINT', 'UNIQUE',
            'CHECK', 'DEFAULT', 'AUTO_INCREMENT', 'SERIAL', 'VARCHAR', 'INT',
            'INTEGER', 'BIGINT', 'SMALLINT', 'DECIMAL', 'NUMERIC', 'FLOAT', 'DOUBLE',
            'DATE', 'TIME', 'TIMESTAMP', 'BOOLEAN', 'BOOL', 'TEXT', 'CHAR',
            'CASCADE', 'RESTRICT', 'NO', 'ACTION', 'BEGIN', 'COMMIT', 'ROLLBACK',
            'TRANSACTION', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'IF', 'EXISTS',
            'IN', 'BETWEEN', 'LIKE', 'IS', 'DISTINCT', 'ALL', 'ANY', 'SOME',
            'TRUE', 'FALSE', 'UNKNOWN', 'CAST', 'EXTRACT', 'SUBSTRING', 'POSITION',
            'TRIM', 'UPPER', 'LOWER', 'COALESCE', 'NULLIF', 'GREATEST', 'LEAST'
        }
    
    def normalize(self, sql: str) -> Tuple[str, int]:
        """
        Normalize identifiers in SQL.
        
        Args:
            sql: Original SQL statement
        
        Returns:
            Tuple of (normalized_sql, identifier_count)
            
        Rules:
            - Unquoted identifiers → UPPERCASE
            - Quoted identifiers → Preserve exact case
            - Schema-qualified (schema.table.column) → Normalize each part
        """
        identifier_count = 0
        normalized_sql = sql
        
        def replace_identifier(match):
            nonlocal identifier_count
            
            # Check if it's a quoted identifier (group 1) or unquoted (group 2)
            quoted = match.group(1)
            unquoted = match.group(2)
            
            if quoted is not None:
                # Quoted identifier - preserve exact case
                identifier_count += 1
                return f'"{quoted}"'  # Return as-is
            elif unquoted is not None:
                # Unquoted identifier - check if it's a keyword
                if unquoted.upper() in self._sql_keywords:
                    # SQL keyword - uppercase but don't count as user identifier
                    return unquoted.upper()
                else:
                    # User identifier - uppercase and count
                    identifier_count += 1
                    return unquoted.upper()
            
            return match.group(0)  # Shouldn't reach here
        
        normalized_sql = self._identifier_pattern.sub(replace_identifier, normalized_sql)
        
        return normalized_sql, identifier_count
    
    def is_quoted(self, identifier: str) -> bool:
        """
        Check if an identifier is delimited with double quotes.
        
        Args:
            identifier: SQL identifier (may include quotes)
        
        Returns:
            True if identifier is quoted (e.g., '"FirstName"')
        """
        return identifier.startswith('"') and identifier.endswith('"')
