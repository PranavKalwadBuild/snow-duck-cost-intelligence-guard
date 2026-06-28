# Smart DuckDB/Snowflake Agent - Skill Invocation Flow

## Overview
This document describes how the skills are invoked by the main agent for intelligent routing of analytical SQL queries between DuckDB and Snowflake with cost optimization.

## Skill Invocation Sequence

### 1. Initialization
```python
# Get machine specs for informed decision making (local function)
machine_specs = get_machine_specs()

# Initialize DuckDB connection with memory limit based on machine specs
duckdb_conn = duckdb.connect(
    database=':memory:', 
    config={'max_memory': f"{int(machine_specs.get('available_memory', 4 * 1024**3) * 0.7 // (1024**3))}GB"}
)
```

### 2. Per-Query Processing Loop
For each analytical SQL query:

#### a. Extract Query Information
```python
# Get SQL query and stats
query_sql = get_query_sql(query_name)  # Extracts SQL query
table_stats = get_table_stats(query_name)  # Extracts size, row count, etc.
```

#### b. Skill Invocation: Dialect Compatibility Check
```python
# Invoke dialect_check.py skill
from skills.dialect_check import is_snowflake_dialect, recommend_engine

compatible, issues = is_snowflake_dialect(query_sql)
# Returns: (Boolean compatibility, List of issues if incompatible)
# Uses sqlglot for local SQL parsing - NO MCP needed (local operation)

engine_recommendation = recommend_engine(query_sql)
# Returns: 'snowflake' if incompatible, 'duckdb' if compatible
```

#### c. Skill Invocation: Engine Selection & Cost Optimization
```python
# Initialize engine selector (uses local functions/classes in agent.py)
selector = EngineSelector(machine_specs)

# Select engine and warehouse size
# Invokes internal logic that considers:
#   - EXPLAIN-based query analysis for resource estimation
#   - Dialect compatibility (from skill above)
#   - Machine specs (CPU, RAM, disk)
#   - Cost modeling (Snowflake vs DuckDB) using EXPLAIN estimates
#   - Performance thresholds
#   - Approved warehouse list (see Skill_2_Warehouse_Sizer.md for details: 
#     COMPUTE_WH, LOAD_TEST_WH_S, LOAD_TEST_WH_M, LOAD_TEST_WH_L, 
#     LOAD_TEST_WH_XL, LOAD_TEST_WH_2XL)
engine, warehouse_size, metadata = selector.select_engine(query_sql, table_stats)
```

#### d. Skill Invocation: Write-Back Preparation (if needed)
```python
# Note: write_back skill is invoked during execution, not selection
```

#### e. Query Execution
```python
# Execute query with selected engine
success = execute_query_with_engine(
    query_name, 
    engine, 
    warehouse_size, 
    duckdb_conn
)
```

## MCP Tool Usage Verification

### Skills Using MCP Server's SnowflakeConnection:
1. **write_back.py** ✅
   - Imports: `from snowflake_mcp.connection import SnowflakeConnection`
   - Uses: `snowflake_conn.put_file()` → MCP put_file tool
   - Uses: `snowflake_conn.process_request()` → MCP process_req tool

2. **agent.py (execution functions)** ✅
   - Imports: `from snowflake_mcp.connection import SnowflakeConnection`
   - Uses: `snowflake_conn.process_request()` → MCP process_req tool
   - Manages SnowflakeConnection lifecycle directly (creation, usage, cleanup)

### Skills Using Local Operations Only (No MCP Needed):
1. **dialect_check.py** ✅
   - Local SQL parsing with sqlglot
   - No Snowflake interaction needed for syntax compatibility check
   - Appropriate design: stateless, local operation

2. **agent.py (helper functions)** ✅
   - `get_machine_specs()`: Local OS/system calls
   - `get_query_sql()`, `get_table_stats()`: Local metadata retrieval
   - `CostEstimator`, `EngineSelector`: Local calculation/logic
   - `_estimate_warehouse_size()`: Local heuristics

## Summary
All skills that require Snowflake interaction properly invoke MCP-exposed tools via the SnowflakeConnection class from the MCP server codebase. Skills that perform local operations (machine specs, cost modeling, dialect checking, metadata parsing) appropriately do not use MCP, maintaining separation of concerns and efficiency.

Enhanced with EXPLAIN-based query analysis for more accurate cost and performance estimation in the intelligent router.