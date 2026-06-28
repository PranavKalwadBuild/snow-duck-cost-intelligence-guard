# Skill 2: Warehouse Sizer

## Purpose
Determines the appropriate Snowflake warehouse size when a model is routed to Snowflake, based on data size and query complexity to balance performance and cost. The selected warehouse size is used when executing Snowflake operations via the MCP server.

## Inputs
- Table statistics: size in GB, row count
- Query complexity (optional, derived from SQL structure: number of joins, aggregations, window functions)

## Process
1. **Data Size Heuristics**: 
   - < 1 GB and < 100K rows → XSMALL
   - < 10 GB and < 1M rows → SMALL
   - < 100 GB and < 10M rows → MEDIUM
   - < 1000 GB and < 100M rows → LARGE
   - Otherwise → XLARGE
2. **Complexity Adjustment** (optional): 
   - If query has high complexity (e.g., many joins, nested subqueries), may increase warehouse size by one step.
3. **Warehouse Mapping**: 
   - The determined size (XSMALL, SMALL, MEDIUM, LARGE, XLARGE) maps to specific warehouse names:
     - XSMALL → COMPUTE_WH
     - SMALL → LOAD_TEST_WH_S
     - MEDIUM → LOAD_TEST_WH_M
     - LARGE → LOAD_TEST_WH_L
     - XLARGE → LOAD_TEST_WH_XL
   - For XXLARGE needs (if ever required), use LOAD_TEST_WH_2XL
4. **Output**: Warehouse name string compatible with Snowflake (from the approved list above).

## Outputs
- Recommended Snowflake warehouse name from the approved list.

## Configuration
- The size thresholds can be adjusted in the `_estimate_warehouse_size` method of `EngineSelector` in `agent.py`.
- Warehouse mappings can be adjusted in the warehouse selection logic.

## Notes
- This skill is part of the `EngineSelector` in `agent.py`.
- The goal is to avoid over-provisioning (using a larger warehouse than needed) while ensuring the query completes in a reasonable time.
- For write-back operations (when using DuckDB), a small warehouse (XSMALL -> COMPUTE_WH) is used briefly for the COPY INTO operation via MCP.
- All warehouse operations are executed through the MCP server for security and abstraction.
- **Important**: Only use the following approved warehouses: COMPUTE_WH, LOAD_TEST_WH_S, LOAD_TEST_WH_M, LOAD_TEST_WH_L, LOAD_TEST_WH_XL, LOAD_TEST_WH_2XL