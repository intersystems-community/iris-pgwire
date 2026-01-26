"""
IntegratedML Support for PostgreSQL Wire Protocol

Enables IntegratedML commands (CREATE MODEL, TRAIN MODEL, PREDICT) to work
through the PostgreSQL wire protocol by parsing, translating, and executing
them via native IRIS capabilities.
"""

import json
import re
from typing import Any

import structlog

logger = structlog.get_logger()


class IntegratedMLParser:
    """Parse and validate IntegratedML SQL commands"""

    # IntegratedML command patterns
    PATTERNS = {
        "CREATE_MODEL": re.compile(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?MODEL\s+(\w+(?:\.\w+)?)\s+"
            r"PREDICTING\s*\(([^)]+)\)\s+"
            r"FROM\s+(\w+(?:\.\w+)?)"
            r"(?:\s+USING\s+({[^}]+}))?",
            re.IGNORECASE | re.DOTALL,
        ),
        "TRAIN_MODEL": re.compile(
            r"TRAIN\s+MODEL\s+(\w+(?:\.\w+)?)" r"(?:\s+FROM\s+(\w+(?:\.\w+)?))?", re.IGNORECASE
        ),
        "VALIDATE_MODEL": re.compile(
            r"VALIDATE\s+MODEL\s+(\w+(?:\.\w+)?)" r"(?:\s+FROM\s+(\w+(?:\.\w+)?))?", re.IGNORECASE
        ),
        "DROP_MODEL": re.compile(r"DROP\s+MODEL\s+(\w+(?:\.\w+)?)", re.IGNORECASE),
        "PREDICT_FUNCTION": re.compile(
            r"PREDICT\s*\(\s*(\w+(?:\.\w+)?)\s*(?:,\s*([^)]+))?\s*\)", re.IGNORECASE
        ),
    }

    def is_integratedml_command(self, sql: str) -> bool:
        """Check if SQL contains IntegratedML commands"""
        sql_normalized = " ".join(sql.split())

        # Check for IntegratedML keywords
        ml_keywords = ["CREATE MODEL", "TRAIN MODEL", "VALIDATE MODEL", "DROP MODEL", "PREDICT("]

        for keyword in ml_keywords:
            if keyword.upper() in sql_normalized.upper():
                return True

        return False

    def parse_create_model(self, sql: str) -> dict[str, Any] | None:
        """Parse CREATE MODEL command"""
        match = self.PATTERNS["CREATE_MODEL"].search(sql)
        if not match:
            return None

        model_name = match.group(1)
        target_columns = [col.strip() for col in match.group(2).split(",")]
        source_table = match.group(3)
        using_clause = match.group(4)

        result = {
            "command": "CREATE_MODEL",
            "model_name": model_name,
            "target_columns": target_columns,
            "source_table": source_table,
            "using_params": None,
        }

        # Parse USING clause if present
        if using_clause:
            try:
                # Clean up JSON string
                json_str = using_clause.strip()
                result["using_params"] = json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.warning(
                    "Failed to parse USING clause", error=str(e), using_clause=using_clause
                )

        return result

    def parse_train_model(self, sql: str) -> dict[str, Any] | None:
        """Parse TRAIN MODEL command"""
        match = self.PATTERNS["TRAIN_MODEL"].search(sql)
        if not match:
            return None

        return {
            "command": "TRAIN_MODEL",
            "model_name": match.group(1),
            "source_table": match.group(2),  # Optional FROM clause
        }

    def parse_validate_model(self, sql: str) -> dict[str, Any] | None:
        """Parse VALIDATE MODEL command"""
        match = self.PATTERNS["VALIDATE_MODEL"].search(sql)
        if not match:
            return None

        return {
            "command": "VALIDATE_MODEL",
            "model_name": match.group(1),
            "source_table": match.group(2),  # Optional FROM clause
        }

    def parse_drop_model(self, sql: str) -> dict[str, Any] | None:
        """Parse DROP MODEL command"""
        match = self.PATTERNS["DROP_MODEL"].search(sql)
        if not match:
            return None

        return {"command": "DROP_MODEL", "model_name": match.group(1)}

    def parse_predict_function(self, sql: str) -> list[dict[str, Any]]:
        """Find and parse PREDICT() function calls in SQL"""
        predictions = []

        for match in self.PATTERNS["PREDICT_FUNCTION"].finditer(sql):
            model_name = match.group(1)
            additional_params = match.group(2)

            predictions.append(
                {
                    "function": "PREDICT",
                    "model_name": model_name,
                    "params": additional_params.strip() if additional_params else None,
                    "match_span": match.span(),
                }
            )

        return predictions

    def parse_command(self, sql: str) -> dict[str, Any] | None:
        """Parse any IntegratedML command"""
        # Try each parser in order
        parsers = [
            self.parse_create_model,
            self.parse_train_model,
            self.parse_validate_model,
            self.parse_drop_model,
        ]

        for parser in parsers:
            result = parser(sql)
            if result:
                return result

        # Check for PREDICT functions in SELECT statements
        predictions = self.parse_predict_function(sql)
        if predictions:
            return {
                "command": "SELECT_WITH_PREDICT",
                "original_sql": sql,
                "predictions": predictions,
            }

        return None


class IRISSystemFunctionTranslator:
    """Translate IRIS system functions to PostgreSQL equivalents"""

    SYSTEM_FUNCTION_MAP = {
        "%SYSTEM.ML.%ModelExists": "iris_ml_model_exists",
        "%SYSTEM.ML.%GetModelList": "iris_ml_list_models",
        "%SYSTEM.ML.%GetModelMetrics": "iris_ml_model_metrics",
        "%SYSTEM.ML.%GetModelInfo": "iris_ml_model_info",
    }

    def translate_system_functions(self, sql: str) -> str:
        """Replace IRIS system functions with PostgreSQL equivalents"""
        translated_sql = sql

        for iris_func, pg_func in self.SYSTEM_FUNCTION_MAP.items():
            # Case-insensitive replacement
            pattern = re.compile(re.escape(iris_func), re.IGNORECASE)
            translated_sql = pattern.sub(pg_func, translated_sql)

        return translated_sql

    def create_function_implementations(self) -> dict[str, str]:
        """Generate SQL for implementing system function equivalents"""
        return {
            "iris_ml_model_exists": """
                CREATE OR REPLACE FUNCTION iris_ml_model_exists(model_name VARCHAR)
                RETURNS BOOLEAN AS $$
                BEGIN
                    -- Implementation queries IRIS ML metadata
                    RETURN CASE
                        WHEN EXISTS (
                            SELECT 1 FROM INFORMATION_SCHEMA.ML_MODELS
                            WHERE MODEL_NAME = UPPER(model_name)
                        ) THEN TRUE
                        ELSE FALSE
                    END;
                END;
                $$ LANGUAGE plpgsql;
            """,
            "iris_ml_list_models": """
                CREATE OR REPLACE FUNCTION iris_ml_list_models()
                RETURNS TABLE(
                    model_name VARCHAR,
                    model_type VARCHAR,
                    created_date TIMESTAMP
                ) AS $$
                BEGIN
                    RETURN QUERY
                    SELECT m.MODEL_NAME, m.MODEL_TYPE, m.CREATED_DATE
                    FROM INFORMATION_SCHEMA.ML_MODELS m;
                END;
                $$ LANGUAGE plpgsql;
            """,
        }


class IntegratedMLExecutor:
    """Execute IntegratedML commands via IRIS backend"""

    def __init__(self, iris_executor):
        self.iris_executor = iris_executor
        self.parser = IntegratedMLParser()
        self.translator = IRISSystemFunctionTranslator()

    async def execute_integratedml_command(self, sql: str) -> tuple[list[dict], list[str]]:
        """Execute IntegratedML command and return results"""

        # Parse the command
        parsed = self.parser.parse_command(sql)
        if not parsed:
            raise ValueError("Invalid IntegratedML command")

        command_type = parsed["command"]

        try:
            if command_type == "CREATE_MODEL":
                return await self._execute_create_model(parsed)
            elif command_type == "TRAIN_MODEL":
                return await self._execute_train_model(parsed)
            elif command_type == "VALIDATE_MODEL":
                return await self._execute_validate_model(parsed)
            elif command_type == "DROP_MODEL":
                return await self._execute_drop_model(parsed)
            elif command_type == "SELECT_WITH_PREDICT":
                return await self._execute_select_with_predict(parsed)
            else:
                raise ValueError(f"Unsupported IntegratedML command: {command_type}")

        except Exception as e:
            logger.error(
                "IntegratedML command execution failed", command=command_type, error=str(e)
            )
            raise

    async def _execute_create_model(self, parsed: dict[str, Any]) -> tuple[list[dict], list[str]]:
        """Execute CREATE MODEL command"""
        model_name = parsed["model_name"]
        target_columns = parsed["target_columns"]
        source_table = parsed["source_table"]
        using_params = parsed.get("using_params")

        # Build IRIS CREATE MODEL SQL
        iris_sql = f"CREATE MODEL {model_name} PREDICTING ({', '.join(target_columns)}) FROM {source_table}"

        if using_params:
            # Convert Python dict back to JSON string for IRIS
            iris_sql += f" USING {json.dumps(using_params)}"

        logger.info(
            "Executing CREATE MODEL via PostgreSQL wire protocol",
            model_name=model_name,
            source_table=source_table,
        )

        # Execute via IRIS
        results, columns = await self.iris_executor.execute_query(iris_sql)

        # Return success message
        return [{"result": f"Model {model_name} created successfully"}], ["result"]

    async def _execute_train_model(self, parsed: dict[str, Any]) -> tuple[list[dict], list[str]]:
        """Execute TRAIN MODEL command"""
        model_name = parsed["model_name"]
        source_table = parsed.get("source_table")

        iris_sql = f"TRAIN MODEL {model_name}"
        if source_table:
            iris_sql += f" FROM {source_table}"

        logger.info("Executing TRAIN MODEL via PostgreSQL wire protocol", model_name=model_name)

        results, columns = await self.iris_executor.execute_query(iris_sql)

        # Return training completion message
        return [{"result": f"Model {model_name} training completed"}], ["result"]

    async def _execute_validate_model(self, parsed: dict[str, Any]) -> tuple[list[dict], list[str]]:
        """Execute VALIDATE MODEL command"""
        model_name = parsed["model_name"]
        source_table = parsed.get("source_table")

        iris_sql = f"VALIDATE MODEL {model_name}"
        if source_table:
            iris_sql += f" FROM {source_table}"

        logger.info("Executing VALIDATE MODEL via PostgreSQL wire protocol", model_name=model_name)

        results, columns = await self.iris_executor.execute_query(iris_sql)

        # Return validation results
        return [{"result": f"Model {model_name} validation completed"}], ["result"]

    async def _execute_drop_model(self, parsed: dict[str, Any]) -> tuple[list[dict], list[str]]:
        """Execute DROP MODEL command"""
        model_name = parsed["model_name"]

        iris_sql = f"DROP MODEL {model_name}"

        logger.info("Executing DROP MODEL via PostgreSQL wire protocol", model_name=model_name)

        results, columns = await self.iris_executor.execute_query(iris_sql)

        # Return deletion confirmation
        return [{"result": f"Model {model_name} dropped successfully"}], ["result"]

    async def _execute_select_with_predict(
        self, parsed: dict[str, Any]
    ) -> tuple[list[dict], list[str]]:
        """Execute SELECT statement containing PREDICT() functions"""
        original_sql = parsed["original_sql"]
        predictions = parsed["predictions"]

        logger.info(
            "Executing SELECT with PREDICT via PostgreSQL wire protocol",
            predict_count=len(predictions),
        )

        # Pass through the original SQL to IRIS
        # IRIS should handle PREDICT() function natively
        results, columns = await self.iris_executor.execute_query(original_sql)
        return results, columns

    async def handle_system_function_query(self, sql: str) -> tuple[list[dict], list[str]]:
        """Handle queries with IRIS system functions"""
        # Check if this is a simple system function call we can handle
        if "%SYSTEM.ML.%ModelExists" in sql.upper():
            # Extract model name and check existence
            # For now, return mock data - in production this would query IRIS metadata
            return [{"model_exists": True}], ["model_exists"]

        # Translate system functions
        translated_sql = self.translator.translate_system_functions(sql)

        if translated_sql != sql:
            logger.info("Translated IRIS system functions", original=sql, translated=translated_sql)

        # For now, return mock data for system functions
        # In production, this would implement the actual system function logic
        return [{"function_result": "System function executed"}], ["function_result"]


def enhance_iris_executor_with_integratedml(iris_executor):
    """Enhance IRISExecutor with IntegratedML support"""
    ml_executor = IntegratedMLExecutor(iris_executor)
    parser = IntegratedMLParser()

    # Store original execute_query method
    original_execute_query = iris_executor.execute_query

    async def execute_query_with_ml_support(sql: str, params=None, session_id=None):
        """Enhanced execute_query with IntegratedML support"""
        # Feature 036 tactical fix: capture closure variables locally
        c_sql = sql
        c_params = params
        c_session_id = session_id

        # Check if this is an IntegratedML command
        if parser.is_integratedml_command(c_sql):
            logger.info("Detected IntegratedML command, routing to ML executor")
            try:
                return await ml_executor.execute_integratedml_command(c_sql)
            except Exception as e:
                logger.warning("IntegratedML execution failed, trying fallback", error=str(e))
                # Try to pass through to IRIS directly as fallback
                return await original_execute_query(c_sql, params=c_params, session_id=c_session_id)

        # Check for IRIS system functions
        if any(func in c_sql.upper() for func in ["%SYSTEM.ML."]):
            logger.info("Detected IRIS system functions")
            try:
                return await ml_executor.handle_system_function_query(c_sql)
            except Exception as e:
                logger.warning("System function handling failed, trying fallback", error=str(e))
                # Try to pass through to IRIS directly as fallback
                return await original_execute_query(c_sql, params=c_params, session_id=c_session_id)

        # Fall back to original execution (with vector optimizer support)
        return await original_execute_query(c_sql, params=c_params, session_id=c_session_id)

    # Replace the methods
    iris_executor.execute_query = execute_query_with_ml_support

    if hasattr(iris_executor, "execute_many"):
        original_execute_many = iris_executor.execute_many

        async def execute_many_with_ml_support(sql: str, params_list: Any, session_id=None):
            """Enhanced execute_many with potential ML support (currently pass-through)"""
            # IntegratedML doesn't currently support batch execution via this interface
            # so we always pass through to the original executor
            return await original_execute_many(sql, params_list, session_id=session_id)

        iris_executor.execute_many = execute_many_with_ml_support

    return iris_executor
