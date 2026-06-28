"""
SnowDuck Agent: Orchestrates query routing between DuckDB and Snowflake.

Usage:
    python agent.py <query_name>

Where <query_name> corresponds to a SQL file in the queries/ directory
(e.g., q1 for queries/q1.sql).
"""
import sys
import logging
import os
import time
import duckdb
from pathlib import Path

# Ensure src is on path when executed as a script
ROOT = Path(__file__).resolve().parents[2]  # points to .claude
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from snowduck.config.settings import settings
from snowduck.skills.registry import SkillRegistry
from snowduck.utils.machine_utils import get_machine_specs
from snowduck.utils.cost_estimator import CostEstimator
from snowduck.utils.engine_selector import EngineSelector
from snowduck.utils.query_analyzer import init_query_analyzer, get_query_analyzer
from snowduck.utils.snowflake_factory import SnowflakeConnectionFactory
from snowduck.utils.query_helpers import get_query_sql, get_table_stats

logger = logging.getLogger(__name__)


def _estimate_table_size(sql: str) -> tuple[float, int]:
    """Estimate total data size in GB and row count from SQL.
    Simple heuristic: if references SNOWFLAKE_SAMPLE_DATA, assume huge.
    """
    if "SNOWFLAKE_SAMPLE_DATA" in sql.upper():
        # From the query comment in q1.sql:
        # STORE_SALES 11.4 TB + CATALOG_SALES 10.2 TB + WEB_SALES 5.2 TB = ~26.7 TB
        # We'll use 27000 GB and a large row count.
        return 27000.0, 200_000_000_000  # 27 TB, 200B rows
    # Otherwise, fallback to small defaults (could parse tables but skip)
    return 1.0, 100_000


def _select_warehouse_size(size_gb: float, row_count: int) -> str:
    """Select warehouse size based on data size heuristics from Skill 2."""
    if size_gb < 1 and row_count < 100_000:
        size = "XSMALL"
    elif size_gb < 10 and row_count < 1_000_000:
        size = "SMALL"
    elif size_gb < 100 and row_count < 10_000_000:
        size = "MEDIUM"
    elif size_gb < 1000 and row_count < 100_000_000:
        size = "LARGE"
    elif size_gb < 10000 and row_count < 1_000_000_000:   # 10TB, 1B rows
        size = "XLARGE"
    elif size_gb < 100000 and row_count < 10_000_000_000: # 100TB, 10B rows
        size = "XXLARGE"
    else:
        size = "XXXLARGE"
    # Optional complexity adjustment could be added here.
    return size
def main():
    if len(sys.argv) < 2:
        print("Usage: python agent.py <query_name>")
        print("Example: python agent.py q1")
        sys.exit(1)

    query_name = sys.argv[1]

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    logger.info(f"Starting agent for query: {query_name}")

    try:
        # 1. Configuration already loaded via settings (from YAML + env)
        logger.debug(f"Settings: {settings._data}")

        # 2. Machine specs
        machine_specs = get_machine_specs()
        cpu_count = machine_specs.get("cpu_count", 1)
        mem_bytes = machine_specs.get("available_memory", 4 * 1024**3)
        mem_gb = mem_bytes // (1024**3)
        logger.info(
            f"Machine specs: {cpu_count} CPU(s), {mem_gb} GB RAM available"
        )

        # 3. DuckDB connection (in-memory) with memory limit from settings
        mem_limit_gb = int(mem_gb * settings.duckdb.memory_fraction)
        if mem_limit_gb < 1:
            mem_limit_gb = 1
        duckdb_conn = duckdb.connect(
            database=":memory:",
            config={"max_memory": f"{mem_limit_gb}GB"},
        )
        logger.info(
            f"DuckDB connection initialized with max_memory={mem_limit_gb}GB"
        )

        # 4. Snowflake connection factory with defaults from settings
        sf_defaults = settings.connection.snowflake_connection_params()
        sf_factory = SnowflakeConnectionFactory(defaults=sf_defaults)
        logger.debug(
            f"Snowflake factory defaults (secrets masked): { {k: ('***' if 'pass' in k.lower() or 'key' in k.lower() else v) for k, v in sf_defaults.items()} }"
        )

        # 5. Query analyzer (needs duckdb conn and sf factory)
        query_analyzer = init_query_analyzer(
            duckdb_conn, sf_factory.create_connection
        )
        logger.info("Query analyzer initialized")

        # 6. Cost estimator and engine selector
        cost_estimator = CostEstimator(machine_specs)
        engine_selector = EngineSelector(machine_specs, cost_estimator)
        # Provide the initialized query analyzer instance
        engine_selector.set_query_analyzer(query_analyzer)
        logger.info("Cost estimator and engine selector ready")

        # 7. Skill registry with hot-reload (watch the skills directory)
        skills_dir = ROOT / "src" / "snowduck" / "skills"
        skill_registry = SkillRegistry(skills_dir)
        skill_registry.start_watching()
        logger.info(f"Skill registry started, watching {skills_dir}")

        # 8. Retrieve the dialect check skill (example)
        dialect_skill = skill_registry.get("dialect_check")
        if dialect_skill is None:
            logger.error("Dialect check skill not found! Ensure it's loaded.")
            sys.exit(1)
        else:
            logger.debug("Dialect check skill loaded.")

        # 9. Load the SQL query
        sql = get_query_sql(query_name)
        table_stats = get_table_stats(query_name)  # placeholder, not used for sizing
        logger.info(f"Loaded query '{query_name}' ({len(sql)} chars)")
        logger.debug(f"Table stats (placeholder): {table_stats}")

        # 10. Estimate true table size for warehouse sizing
        size_gb, row_count = _estimate_table_size(sql)
        logger.info(
            f"Estimated data size: {size_gb:.1f} GB, {row_count:,} rows"
        )

        # 11. Run dialect check via skill
        dialect_result = dialect_skill.run({"sql": sql})
        compatible = dialect_result["compatible"]
        issues = dialect_result["issues"]
        recommendation = dialect_result["recommendation"]
        logger.info(
            f"Dialect check: compatible={compatible}, issues={issues}, recommendation={recommendation}"
        )

        # 12. Engine selection using selector (includes EXPLAIN-based cost estimation)
        engine, warehouse_size_from_selector, selector_metadata = engine_selector.select_engine(
            sql, table_stats
        )
        logger.info(
            f"Engine selection (pre-override): engine={engine}, warehouse={warehouse_size_from_selector}"
        )
        logger.debug(f"Selection metadata: {selector_metadata}")

        # 13. Override if query references Snowflake-specific dataset (as in original agent)
        logger.debug(f"Checking override: engine={engine}, 'SNOWFLAKE_SAMPLE_DATA' in sql.upper() = {'SNOWFLAKE_SAMPLE_DATA' in sql.upper()}")
        if "SNOWFLAKE_SAMPLE_DATA" in sql.upper() and engine == "duckdb":
            logger.info(
                "Overriding engine to snowflake due to SNOWFLAKE_SAMPLE_DATA reference"
            )
            engine = "snowflake"
            # For snowflake, we will compute warehouse size based on actual data size heuristics from Skill 2, but use the Snowflake runtime estimate
            # from the selector metadata if available

        # 14. Determine warehouse size to use
        if engine == "snowflake":
            # If we overridden to snowflake due to SNOWFLAKE_SAMPLE_DATA, still use the
            # warehouse size selected by the EXPLAIN-based engine selector for better accuracy
            if "SNOWFLAKE_SAMPLE_DATA" in sql.upper():
                # Extract parameters needed for warehouse selection from metadata and engine selector
                explain_analysis = selector_metadata.get('explain_analysis')
                duckdb_runtime = selector_metadata.get('duckdb_runtime_seconds', 0.1)
                snowflake_runtime_medium = selector_metadata.get('snowflake_runtime_seconds', 0.5)

                # Use the engine selector's EXPLAIN-based warehouse selection logic
                warehouse_size = engine_selector._select_warehouse_size_explain(
                    sql, duckdb_runtime, snowflake_runtime_medium, explain_analysis
                )
                # Map to actual warehouse name using settings mapping
                warehouse_name = settings.snowflake.warehouse.mapping.get(
                    warehouse_size, warehouse_size
                )
                logger.info(
                    f"Selected warehouse size: {warehouse_size} -> {warehouse_name} based on EXPLAIN analysis (SNOWFLAKE_SAMPLE_DATA override)"
                )
            else:
                # Use our size-based warehouse selection (Skill 2)
                warehouse_size = _select_warehouse_size(size_gb, row_count)
                # Map to actual warehouse name using settings mapping
                warehouse_name = settings.snowflake.warehouse.mapping.get(
                    warehouse_size, warehouse_size
                )
                logger.info(
                    f"Selected warehouse size: {warehouse_size} -> {warehouse_name} based on data size"
                )
        else:
            # For DuckDB, warehouse size is irrelevant; keep None
            warehouse_name = None

        # 15. Execute query
        start_time = time.time()
        success = False
        if engine == "duckdb":
            success = _execute_duckdb(query_name, duckdb_conn, sql)
        else:
            # Snowflake execution: use temporary env to set warehouse size
            with sf_factory.temporary_env(warehouse=warehouse_name):
                sf_conn = sf_factory.create_connection()
                try:
                    success = _execute_snowflake(query_name, sf_conn, sql)
                finally:
                    sf_conn.cleanup()
        elapsed = time.time() - start_time

        if success:
            logger.info(f"Query {query_name} succeeded in {elapsed:.2f}s")
            sys.exit(0)
        else:
            logger.error(f"Query {query_name} failed after {elapsed:.2f}s")
            sys.exit(1)

    except Exception as e:
        logger.exception(f"Agent failed with error: {e}")
        sys.exit(1)
    finally:
        # Cleanup
        try:
            duckdb_conn.close()
            logger.info("DuckDB connection closed")
        except Exception:
            pass
        try:
            skill_registry.stop_watching()
        except Exception:
            pass


def _execute_duckdb(query_name: str, conn, sql: str) -> bool:
    """Execute query using DuckDB and print results."""
    try:
        start = time.time()
        relation = conn.execute(sql)
        elapsed = time.time() - start
        logger.info(f"DuckDB execution time: {elapsed:.2f}s")
        if description := relation.description:
            cols = [desc[0] for desc in description]
            for row in relation.fetchall():
                print(dict(zip(cols, row)))
        else:
            print(f"Query executed successfully. Rows affected: {relation.rowcount}")
        return True
    except Exception as e:
        logger.error(f"DuckDB execution error: {e}", exc_info=True)
        return False


def _execute_snowflake(query_name: str, conn, sql: str) -> bool:
    """Execute query using Snowflake and print results."""
    try:
        start = time.time()
        results = conn.process_request(sql)
        elapsed = time.time() - start
        logger.info(f"Snowflake execution time: {elapsed:.2f}s")
        if results:
            for stmt_res in results:
                rows = stmt_res.get("rows", [])
                if rows:
                    for row in rows:
                        print(row)
                else:
                    print(f"Statement executed: {stmt_res.get('statement')}")
        else:
            print("Query executed.")
        return True
    except Exception as e:
        logger.error(f"Snowflake execution error: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    main()