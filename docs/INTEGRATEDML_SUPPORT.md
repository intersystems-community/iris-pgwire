"""
IntegratedML Support for PostgreSQL Wire Protocol

Enables IntegratedML commands (CREATE MODEL, TRAIN MODEL, PREDICT) to work
through the PostgreSQL wire protocol by parsing, translating, and executing
them via native IRIS capabilities.
"""

import re
import json
from typing import Dict, Any, List, Optional, Tuple
import structlog

logger = structlog.get_logger()


class IntegratedMLParser:
    """Parse and validate IntegratedML SQL commands"""

    # IntegratedML command patterns
    PATTERNS = {
        'CREATE_MODEL': re.compile(
            r'CREATE\s+(?:OR\s+REPLACE\s+)?MODEL\s+(\w+(?:\.\w+)?)\s+'
            r'PREDICTING\s*\(([^)]+)\)\s+'
            r'FROM\s+(\w+(?:\.\w+)?)'
            r'(?:\s+USING\s+({[^}]+}))?',
            re.IGNORECASE | re.DOTALL
        ),
        'TRAIN_MODEL': re.compile(
            r'TRAIN\s+MODEL\s+(\w+(?:\.\w+)?)'
            r'(?:\s+FROM\s+(\w+(?:\.\w+)?))?',
            re.IGNORECASE
        ),
        'VALIDATE_MODEL': re.compile(
            r'VALIDATE\s+MODEL\s+(\w+(?:\.\w+)?)'
            r'(?:\s+FROM\s+(\w+(?:\.\w+)?))?',
            re.IGNORECASE
        ),
        'DROP_MODEL': re.compile(
            r'DROP\s+MODEL\s+(\w+(?:\.\w+)?)',
            re.IGNORECASE
        ),
        'PREDICT_FUNCTION': re.compile(
            r'PREDICT\s*\(\s*(\w+(?:\.\w+)?)\s*(?:,\s*([^)]+))?\s*\)',
            re.IGNORECASE
        )
    }

    def is_integratedml_command(self, sql: str) -> bool:
        """Check if SQL contains IntegratedML commands"""
        sql_normalized = ' '.join(sql.split())

        # Check for IntegratedML keywords
        ml_keywords = ['CREATE MODEL', 'TRAIN MODEL', 'VALIDATE MODEL', 'DROP MODEL', 'PREDICT(']

        for keyword in ml_keywords:
            if keyword.upper() in sql_normalized.upper():
                return True

        return False

    def parse_create_model(self, sql: str) -> Optional[Dict[str, Any]]:
        """Parse CREATE MODEL command"""
        match = self.PATTERNS['CREATE_MODEL'].search(sql)
        if not match:
            return None

        model_name = match.group(1)
        target_columns = [col.strip() for col in match.group(2).split(',')]
        source_table = match.group(3)
        using_clause = match.group(4)

        result = {
            'command': 'CREATE_MODEL',
            'model_name': model_name,
            'target_columns': target_columns,
            'source_table': source_table,
            'using_params': None
        }

        # Parse USING clause if present
        if using_clause:
            try:
                # Clean up JSON string
                json_str = using_clause.strip()
                result['using_params'] = json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.warning("Failed to parse USING clause", error=str(e), using_clause=using_clause)

        return result

    def parse_train_model(self, sql: str) -> Optional[Dict[str, Any]]:
        """Parse TRAIN MODEL command"""
        match = self.PATTERNS['TRAIN_MODEL'].search(sql)
        if not match:
            return None

        return {
            'command': 'TRAIN_MODEL',
            'model_name': match.group(1),
            'source_table': match.group(2)  # Optional FROM clause
        }

    def parse_validate_model(self, sql: str) -> Optional[Dict[str, Any]]:
        """Parse VALIDATE MODEL command"""
        match = self.PATTERNS['VALIDATE_MODEL'].search(sql)
        if not match:
            return None

        return {
            'command': 'VALIDATE_MODEL',
            'model_name': match.group(1),
            'source_table': match.group(2)  # Optional FROM clause
        }

    def parse_drop_model(self, sql: str) -> Optional[Dict[str, Any]]:
        """Parse DROP MODEL command"""
        match = self.PATTERNS['DROP_MODEL'].search(sql)
        if not match:
            return None

        return {
            'command': 'DROP_MODEL',
            'model_name': match.group(1)
        }

    def parse_predict_function(self, sql: str) -> List[Dict[str, Any]]:
        """Find and parse PREDICT() function calls in SQL"""
        predictions = []

        for match in self.PATTERNS['PREDICT_FUNCTION'].finditer(sql):
            model_name = match.group(1)
            additional_params = match.group(2)

            predictions.append({
                'function': 'PREDICT',
                'model_name': model_name,
                'params': additional_params.strip() if additional_params else None,
                'match_span': match.span()
            })

        return predictions

    def parse_command(self, sql: str) -> Optional[Dict[str, Any]]:
        """Parse any IntegratedML command"""
        # Try each parser in order
        parsers = [
            self.parse_create_model,
            self.parse_train_model,
            self.parse_validate_model,
            self.parse_drop_model
        ]

        for parser in parsers:
            result = parser(sql)
            if result:
                return result

        # Check for PREDICT functions in SELECT statements
        predictions = self.parse_predict_function(sql)
        if predictions:
            return {
                'command': 'SELECT_WITH_PREDICT',
                'original_sql': sql,
                'predictions': predictions
            }

        return None


class IRISSystemFunctionTranslator:
    """Translate IRIS system functions to PostgreSQL equivalents"""

    SYSTEM_FUNCTION_MAP = {
        '%SYSTEM.ML.%ModelExists': 'iris_ml_model_exists',
        '%SYSTEM.ML.%GetModelList': 'iris_ml_list_models',
        '%SYSTEM.ML.%GetModelMetrics': 'iris_ml_model_metrics',
        '%SYSTEM.ML.%GetModelInfo': 'iris_ml_model_info'
    }

    def translate_system_functions(self, sql: str) -> str:
        """Replace IRIS system functions with PostgreSQL equivalents"""
        translated_sql = sql

        for iris_func, pg_func in self.SYSTEM_FUNCTION_MAP.items():
            # Case-insensitive replacement
            pattern = re.compile(re.escape(iris_func), re.IGNORECASE)
            translated_sql = pattern.sub(pg_func, translated_sql)

        return translated_sql

    def create_function_implementations(self) -> Dict[str, str]:
        """Generate SQL for implementing system function equivalents"""
        return {
            'iris_ml_model_exists': """
                CREATE OR REPLACE FUNCTION iris_ml_model_exists(model_name VARCHAR)
                RETURNS BOOLEAN AS $$
                BEGIN
                    -- Implementation would query IRIS ML metadata
                    RETURN EXISTS (
                        SELECT 1 FROM information_schema.ml_models
                        WHERE model_name = $1
                    );
                END;
                $$ LANGUAGE plpgsql;
            """,

            'iris_ml_list_models': """
                CREATE OR REPLACE FUNCTION iris_ml_list_models()
                RETURNS TABLE(
                    model_name VARCHAR,
                    model_type VARCHAR,
                    created_date TIMESTAMP
                ) AS $$
                BEGIN
                    RETURN QUERY
                    SELECT m.model_name, m.model_type, m.created_date
                    FROM information_schema.ml_models m;
                END;
                $$ LANGUAGE plpgsql;
            """
        }


class IntegratedMLExecutor:
    """Execute IntegratedML commands via IRIS backend"""

    def __init__(self, iris_executor):
        self.iris_executor = iris_executor
        self.parser = IntegratedMLParser()
        self.translator = IRISSystemFunctionTranslator()

    async def execute_integratedml_command(self, sql: str) -> Tuple[List[Dict], List[str]]:
        """Execute IntegratedML command and return results"""

        # Parse the command
        parsed = self.parser.parse_command(sql)
        if not parsed:
            raise ValueError("Invalid IntegratedML command")

        command_type = parsed['command']

        try:
            if command_type == 'CREATE_MODEL':
                return await self._execute_create_model(parsed)
            elif command_type == 'TRAIN_MODEL':
                return await self._execute_train_model(parsed)
            elif command_type == 'VALIDATE_MODEL':
                return await self._execute_validate_model(parsed)
            elif command_type == 'DROP_MODEL':
                return await self._execute_drop_model(parsed)
            elif command_type == 'SELECT_WITH_PREDICT':
                return await self._execute_select_with_predict(parsed)
            else:
                raise ValueError(f"Unsupported IntegratedML command: {command_type}")

        except Exception as e:
            logger.error("IntegratedML command execution failed",
                        command=command_type, error=str(e))
            raise

    async def _execute_create_model(self, parsed: Dict[str, Any]) -> Tuple[List[Dict], List[str]]:
        """Execute CREATE MODEL command"""
        model_name = parsed['model_name']
        target_columns = parsed['target_columns']
        source_table = parsed['source_table']
        using_params = parsed.get('using_params')

        # Build IRIS CREATE MODEL SQL
        iris_sql = f"CREATE MODEL {model_name} PREDICTING ({', '.join(target_columns)}) FROM {source_table}"

        if using_params:
            # Convert Python dict back to JSON string for IRIS
            iris_sql += f" USING {json.dumps(using_params)}"

        logger.info("Executing CREATE MODEL", model_name=model_name, source_table=source_table)

        # Execute via IRIS
        results, columns = await self.iris_executor.execute_query(iris_sql)

        return results, columns or ['result']

    async def _execute_train_model(self, parsed: Dict[str, Any]) -> Tuple[List[Dict], List[str]]:
        """Execute TRAIN MODEL command"""
        model_name = parsed['model_name']
        source_table = parsed.get('source_table')

        iris_sql = f"TRAIN MODEL {model_name}"
        if source_table:
            iris_sql += f" FROM {source_table}"

        logger.info("Executing TRAIN MODEL", model_name=model_name)

        results, columns = await self.iris_executor.execute_query(iris_sql)
        return results, columns or ['result']

    async def _execute_validate_model(self, parsed: Dict[str, Any]) -> Tuple[List[Dict], List[str]]:
        """Execute VALIDATE MODEL command"""
        model_name = parsed['model_name']
        source_table = parsed.get('source_table')

        iris_sql = f"VALIDATE MODEL {model_name}"
        if source_table:
            iris_sql += f" FROM {source_table}"

        logger.info("Executing VALIDATE MODEL", model_name=model_name)

        results, columns = await self.iris_executor.execute_query(iris_sql)
        return results, columns or ['result']

    async def _execute_drop_model(self, parsed: Dict[str, Any]) -> Tuple[List[Dict], List[str]]:
        """Execute DROP MODEL command"""
        model_name = parsed['model_name']

        iris_sql = f"DROP MODEL {model_name}"

        logger.info("Executing DROP MODEL", model_name=model_name)

        results, columns = await self.iris_executor.execute_query(iris_sql)
        return results, columns or ['result']

    async def _execute_select_with_predict(self, parsed: Dict[str, Any]) -> Tuple[List[Dict], List[str]]:
        """Execute SELECT statement containing PREDICT() functions"""
        original_sql = parsed['original_sql']
        predictions = parsed['predictions']

        logger.info("Executing SELECT with PREDICT",
                   predict_count=len(predictions))

        # For now, pass through the original SQL to IRIS
        # IRIS should handle PREDICT() function natively
        results, columns = await self.iris_executor.execute_query(original_sql)
        return results, columns

    async def handle_system_function_query(self, sql: str) -> Tuple[List[Dict], List[str]]:
        """Handle queries with IRIS system functions"""
        # Translate system functions
        translated_sql = self.translator.translate_system_functions(sql)

        if translated_sql != sql:
            logger.info("Translated IRIS system functions",
                       original=sql, translated=translated_sql)

        # Execute translated query
        results, columns = await self.iris_executor.execute_query(translated_sql)
        return results, columns


# Integration with main protocol handler
def enhance_iris_executor_with_integratedml(iris_executor):
    """Enhance IRISExecutor with IntegratedML support"""
    ml_executor = IntegratedMLExecutor(iris_executor)
    parser = IntegratedMLParser()

    # Store original execute_query method
    original_execute_query = iris_executor.execute_query

    async def execute_query_with_ml_support(sql: str, parameters=None):
        """Enhanced execute_query with IntegratedML support"""

        # Check if this is an IntegratedML command
        if parser.is_integratedml_command(sql):
            logger.info("Detected IntegratedML command, routing to ML executor")
            return await ml_executor.execute_integratedml_command(sql)

        # Check for IRIS system functions
        if any(func in sql.upper() for func in ['%SYSTEM.ML.', 'PREDICT(']):
            logger.info("Detected IRIS system functions")
            return await ml_executor.handle_system_function_query(sql)

        # Fall back to original execution
        return await original_execute_query(sql, parameters)

    # Replace the method
    iris_executor.execute_query = execute_query_with_ml_support

    return iris_executor