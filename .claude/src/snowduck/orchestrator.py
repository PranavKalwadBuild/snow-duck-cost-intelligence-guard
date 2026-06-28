"""
Orchestrator that coordinates the agent's workflow using DI.
"""
import logging
import time
from typing import Callable, Dict, Any, Optional

import duckdb

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    Orchestrates query routing and execution.
    """

    def __init__(
        self,
        settings,
        skill_registry,
        duckdb_conn: duckdb.DuckDBPyConnection,
        snowflake_factory,
        query_analyzer,
        cost_estimator,
        engine_selector,
        get_query_sql: Callable[[str], str],
        get_table_stats: Callable[[str], dict[str, Any]],
    ):
        self.settings = settings
        self.skill_registry = skill_registry
        self.duckdb_conn = duckdb_conn
        self.snowflake_factory = snowflake_factory
        self.query_analyzer = query_analyzer
        self.cost_estimator = cost_estimator
        self.engine_selector = engine_selector
        self.get_query_sql = get_query_sql
        self.get_table_stats = get_table_stats

    def run(self, query_name: str) -> bool:
        """Execute the full pipeline for a single query."""
        start_time = time.time()
        try:
            sql = self.get_query_sql(query_name)
            table_stats = self.get_table_stats(query_name)

            logger.info(f"Processing query '{query_name}' ({len(sql)} chars)")

            # Machine specs are already embedded in cost_estimator etc.

            # 1. Dialect check skill
            dialect_skill = self.skill_registry.get("dialect_check")
            if dialect_skill is None:
                raise RuntimeError("Dialect check skill not loaded")
            dialect_result = dialect_skill.run({"sql": sql})
            compatible = dialect_result["compatible"]
            issues = dialect_result["issues"]
            engine_recommendation = dialect_result["recommendation"]
            logger.info(
                f"Dialect check: compatible={compatible}, issues={issues}, recommendation={engine_recommendation}"
            )

            # 2. Engine selection using EXPLAIN
            engine, warehouse_size, metadata = self.engine_selector.select_engine(
                sql, table_stats
            )
            logger.info(f"Engine selected: {engine} (warehouse={warehouse_size})")
            logger.debug(f"Selection metadata: {metadata}")

            # Override for SNOWFLAKE_SAMPLE_DATA
            if "SNOWFLAKE_SAMPLE_DATA" in sql.upper() and engine == "duckdb":
                logger.info(
                    "Overriding engine to snowflake due to SNOWFLAKE_SAMPLE_DATA reference"
                )
                engine = "snowflake"
                if warehouse_size is None:
                    # Use environment or default
                    import os

                    warehouse_size = os.environ.get("SNOWFLAKE_WAREHOUSE")

            # 3. Execute query
            success = self._execute_query(
                query_name,
                engine,
                warehouse_size,
                self.duckdb_conn,
                sql,
            )

            elapsed = time.time() - start_time
            if success:
                logger.info(f"Query {query_name} succeeded in {elapsed:.2f}s")
            else:
                logger.error(f"Query {query_name} failed after {elapsed:.2f}s")
            return success

        except Exception as e:
            logger.exception(f"Orchestration failed for query {query_name}: {e}")
            return False

    def _execute_query(
        self,
        query_name: str,
        engine: str,
        warehouse_size: Optional[str],
        conn,
        sql: str,
    ) -> bool:
        """Run query on selected engine."""
        if engine == "duckdb":
            return self._run_duckdb(query_name, conn, sql)
        else:
            return self._run_snowflake(query_name, warehouse_size, sql)

    def _run_duckdb(self, query_name: str, conn, sql: str) -> bool:
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
                print(f"Query executed. Rows affected: {relation.rowcount}")
            return True
        except Exception as e:
            logger.error(f"DuckDB execution error: {e}", exc_info=True)
            return False

    def _run_snowflake(self, query_name: str, warehouse_size: Optional[str], sql: str) -> bool:
        try:
            # Use context manager to set env vars temporarily
            with self.snowflake_factory.temporary_env(warehouse=warehouse_size):
                sf_conn = self.snowflake_factory.create_connection()
                try:
                    start = time.time()
                    results = sf_conn.process_request(sql)
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
                finally:
                    sf_conn.cleanup()
        except Exception as e:
            logger.error(f"Failed to create Snowflake connection: {e}", exc_info=True)
            return False


