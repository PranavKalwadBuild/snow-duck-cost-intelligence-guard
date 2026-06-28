# Skill 4: Dialect Resolver

## Purpose
Determines whether a dbt model's SQL is compatible with DuckDB dialect, and if not, routes to Snowflake to avoid runtime errors due to Snowflake-specific syntax. All Snowflake operations (when routing to Snowflake) are performed via an MCP (Model Context Protocol) server.

## Inputs
- Compiled dbt SQL string
- MCP client instance for Snowflake communication (used after routing decision)

## Process
1. **SQL Parsing with SQLGlot**:
   - Attempts to parse the SQL using both Snowflake and DuckDB dialects.
   - If the DuckDB dialect fails to parse, the SQL is deemed incompatible.
2. **Snowflake-Specific Syntax Detection**:
   - Walks the parsed AST (Snowflake dialect) to identify Snowflake-exclusive constructs:
     - System functions (e.g., `SYSTEM$*`)
     - Table functions like `FLATTEN`
     - Semi-structured data types (`VARIANT`, `OBJECT`, `ARRAY`)
     - Specific functions (`GET`, `GET_PATH`, `ARRAY_AGG`, `OBJECT_AGG`, `SEQ*`, etc.)
   - Uses regex patterns as a fallback to catch common Snowflake-specific syntax.
3. **Decision**:
   - If any Snowflake-specific syntax is detected, recommends Snowflake engine.
   - Otherwise, confirms DuckDB compatibility.

## Outputs
- Boolean: `True` if incompatible (recommend Snowflake), `False` if compatible (recommend DuckDB)
- List of issues found (e.g., ["Snowflake system function: SYSTEM$GET_COLUMN_NAMES"])

## Configuration
- The set of Snowflake-specific functions and patterns can be extended in `skills/dialect_check.py`.

## Notes
- This skill is implemented in `skills/dialect_check.py` and used by the `EngineSelector` in `agent.py`.
- It prevents the agent from attempting to run Snowflake-specific SQL in DuckDB, which would cause fatal errors.
- When the resolver recommends Snowflake, the actual execution is handled via the MCP server in `mcp_client.py`.
- For advanced use cases, the skill could be extended to transpile Snowflake SQL to DuckDB SQL using SQLGlot's transpilation capabilities (though this is not implemented in the current version).

## Example
Input SQL: `SELECT SYSTEM$GET_COLUMN_NAMES('mytable') FROM dual`
Output: Incompatible, issue: ["Snowflake system function: SYSTEM$GET_COLUMN_NAMES"]