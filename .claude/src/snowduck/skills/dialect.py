"""
Dialect Compatibility Skill
Checks if dbt compiled SQL is compatible with DuckDB dialect.
Uses sqlglot to parse and detect Snowflake-specific constructs.
"""
import sqlglot
import logging
import re
from typing import List, Tuple, Dict, Any

from .base import Skill

logger = logging.getLogger(__name__)

# Snowflake-specific functions/properties that may not exist in DuckDB
SNOWFLAKE_SPECIFIC = {
    'FLATTEN',  # Table function for JSON
    'ARRAY_AGG',  # Though exists in DuckDB, behavior might differ
    'OBJECT_AGG',
    'SPLIT',  # Snowflake SPLIT vs DuckDB split
    'TRY_CAST',
    'NULLIFZERO',
    'ZEROIFNULL',
    'SEQ1', 'SEQ2', 'SEQ4', 'SEQ8',  # Sequence generators
    'UUID_STRING',
    'SYSTEM$',  # All system functions
    'GET_DDL',
    'RESULT_SCAN',
    'TABLESAMPLE',  # Snowflake-specific sampling
    # Variants and semi-structured data
    'VARIANT',
    'OBJECT',
    'ARRAY',
    # JSON functions
    'GET',  # : notation
    'GET_PATH',
}


class DialectCheckSkill(Skill):
    """Skill to check SQL dialect compatibility."""

    @property
    def name(self) -> str:
        return "dialect_check"

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check dialect compatibility and recommend engine.

        Expected context keys:
            - sql: str, the SQL query to check

        Returns:
            dict with keys:
                compatible: bool
                issues: list[str]
                recommendation: str ('snowflake' or 'duckdb')
        """
        sql: str = context.get("sql")
        if sql is None:
            raise ValueError("DialectCheckSkill requires 'sql' in context")

        incompatible, issues = self._is_snowflake_dialect(sql)
        recommendation = 'snowflake' if incompatible else 'duckdb'

        logger.debug(
            f"Dialect check: compatible={not incompatible}, issues={issues}, recommendation={recommendation}"
        )

        return {
            "compatible": not incompatible,
            "issues": issues,
            "recommendation": recommendation,
        }

    def _is_snowflake_dialect(self, sql: str) -> tuple[bool, list[str]]:
        """
        Check if SQL contains Snowflake-specific syntax.

        Returns:
            Tuple of (is_incompatible, list_of_issues)
        """
        issues = []
        try:
            # Parse with Snowflake dialect first to see if it parses
            parsed_sf = sqlglot.parse(sql, dialect='snowflake')
            # Now try to parse with DuckDB dialect
            try:
                sqlglot.parse(sql, dialect='duckdb')
            except sqlglot.errors.ParseError as e:
                # If DuckDB dialect fails to parse, likely incompatible
                issues.append(f"DuckDB parse error: {str(e)}")
                logger.debug(f"Snowflake SQL parse error in DuckDB dialect: {e}")
                return True, issues

            # Additional heuristic: check for Snowflake-specific syntax via regex or string search
            snowflake_patterns = [
                r'::\s*VARIANT',  # Casting to VARIANT
                r'\$\([^)]+\)',   # Snowflake variable substitution
                r'SYSTEM\$',      # System functions
                r'FLATTEN\s*\(',
                r'ARRAY_AGG\s*\(',
                r'OBJECT_AGG\s*\(',
                r'SEQ\d+\s*\(',
            ]
            for pattern in snowflake_patterns:
                if re.search(pattern, sql, re.IGNORECASE):
                    issues.append(f"Snowflake-specific pattern matched: {pattern}")

            return len(issues) > 0, issues
        except Exception as e:
            # If we can't even parse with Snowflake dialect, assume it's incompatible
            logger.debug(f"Snowflake SQL parse error: {e}")
            issues.append(f"Snowflake parse error: {str(e)}")
            return True, issues


# Convenice function for backward compatibility (optional)
def is_snowflake_dialect(sql: str) -> tuple[bool, list[str]]:
    skill = DialectCheckSkill()
    result = skill.run({"sql": sql})
    return not result["compatible"], result["issues"]


def recommend_engine(sql: str) -> str:
    skill = DialectCheckSkill()
    result = skill.run({"sql": sql})
    return result["recommendation"]


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    test_sql = "SELECT SYSTEM$GET_COLUMN_NAMES('mytable') FROM dual"
    engine = recommend_engine(test_sql)
    print(f"Recommended engine: {engine}")
