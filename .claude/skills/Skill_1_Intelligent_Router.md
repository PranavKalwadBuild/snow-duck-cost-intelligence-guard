# Skill 1: Intelligent Router

## Purpose
Decides whether to execute an analytical SQL query using DuckDB (local) or Snowflake warehouse based on estimated cost, performance, SQL dialect compatibility, and underlying machine specifications. All Snowflake operations are performed via an MCP (Model Context Protocol) server.

## Inputs
- SQL query string (analytical query)
- Table statistics (size in GB, row count, complexity metrics)
- Underlying machine specifications (CPU cores, RAM, disk space)
- MCP client instance for Snowflake communication

## Process
1. **Machine Specs Check**: Agent checks underlying machine specifications:
   - CPU core count (adjusts parallelism estimates)
   - Available RAM (sets DuckDB memory limit)
   - Free disk space (verifies sufficient space for potential spill)
2. **Dialect Compatibility Check**: Uses SQLGlot to parse the SQL in both Snowflake and DuckDB dialects. If Snowflake-specific syntax is detected (e.g., FLATTEN, VARIANT, SYSTEM$* functions), the query is routed to Snowflake regardless of cost.
3. **Cost Estimation**: 
   - Uses EXPLAIN queries to analyze the query plan and estimate resource usage for both DuckDB and Snowflake
   - Estimates runtime in DuckDB based on EXPLAIN analysis, data size, and machine capabilities (CPU core count for parallelism)
   - Estimates Snowflake cost using EXPLAIN analysis to determine appropriate warehouse size and expected runtime
   - Compares estimated cost of DuckDB (near zero) vs Snowflake based on EXPLAIN-driven estimates
4. **Decision Logic**:
   - If SQL is incompatible with DuckDB → Snowflake
   - If estimated DuckDB runtime exceeds a threshold (e.g., 5 minutes) → Snowflake (to avoid excessive local resource usage)
   - If insufficient disk space for potential DuckDB spill → Snowflake
   - Otherwise, choose the engine with lower estimated cost
5. **Output**: 
   - Selected engine (`duckdb` or `snowflake`)
   - Recommended warehouse size (if Snowflake selected)
   - Metadata: estimated costs, runtime, reasoning, machine specs used

## Outputs
- Engine decision
- Warehouse size (if applicable)
- Reasoning for decision
- Estimated cost and runtime for both engines
- Machine specs considered in decision

## Configuration
- DuckDB memory limit: Set to 70% of available RAM (machine-aware)
- Runtime threshold for DuckDB (default: 300 seconds)
- Cost thresholds can be adjusted in the `EngineSelector` class

## Notes
- This skill is implemented in `scripts/agent.py` (EngineSelector class) and uses `skills/dialect_check.py` for dialect compatibility
- All Snowflake operations (query execution, file uploads, etc.) are performed via the MCP client in `mcp_client.py`
- Machine spec detection works best on Linux (reads /proc/meminfo); falls back to conservative estimates on other OS
- For large-scale datasets (up to 100TB), the skill relies on table statistics from metadata or query analysis to avoid scanning entire tables
- The agent ensures DuckDB won't exceed memory limits or disk space for spill operations
- Enhanced with EXPLAIN-based query analysis for more accurate cost and performance estimation