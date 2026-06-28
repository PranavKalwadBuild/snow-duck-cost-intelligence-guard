"""
Engine selection utility for the DuckDB/Snowflake agent.
"""
import math
import logging
from typing import Dict, Any, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class EngineSelector:
    def __init__(self, machine_specs: Dict[str, Any], cost_estimator):
        """
        Initialize engine selector.

        Args:
            machine_specs: Dictionary containing system specifications
            cost_estimator: CostEstimator instance
        """
        self.machine_specs = machine_specs
        self.cost_estimator = cost_estimator
        self.query_analyzer = None  # Will be set later

    def set_query_analyzer(self, query_analyzer):
        """Set the query analyzer instance."""
        self.query_analyzer = query_analyzer

    def select_engine(self, sql: str, table_stats: Dict[str, Any] = None) -> Tuple[str, Optional[str], Dict[str, Any]]:
        """
        Select the optimal engine for executing a SQL query using EXPLAIN when possible.

        Args:
            sql: SQL query string
            table_stats: Optional table statistics (not used in this version)

        Returns:
            Tuple of (engine_name, warehouse_size, metadata_dict)
        """
        if table_stats is None:
            table_stats = {}

        # Get machine specs for reference
        cpu_count = self.machine_specs.get('cpu_count', 1)
        available_memory_gb = self.machine_specs.get('available_memory', 2 * 1024**3) / (1024**3)

        # Analyze query using EXPLAIN when possible
        explain_analysis = None
        if self.query_analyzer:
            try:
                explain_analysis = self.query_analyzer.analyze_query(sql)
                logger.debug(f"EXPLAIN analysis completed: {explain_analysis}")
            except Exception as e:
                logger.warning(f"EXPLAIN analysis failed, falling back to heuristics: {e}")
                explain_analysis = None

        # Estimate runtime and cost for both engines using EXPLAIN when available
        duckdb_runtime, snowflake_runtime = self._estimate_runtimes_explain(sql, explain_analysis)
        duckdb_cost = self.cost_estimator.estimate_duckdb_cost(duckdb_runtime)
        snowflake_cost_medium = self.cost_estimator.estimate_snowflake_cost(snowflake_runtime, 'MEDIUM')

        # Determine if we should consider DuckDB based on resource availability
        can_use_duckdb = self._is_duckdb_viable(sql, explain_analysis)

        # Make decision
        if can_use_duckdb and duckdb_cost <= snowflake_cost_medium * 1.1:  # Allow 10% tolerance for DuckDB
            # Choose DuckDB if it's viable and cost-effective
            engine = 'duckdb'
            warehouse_size = None
            reason = f"DuckDB selected: ${duckdb_cost:.6f} vs Snowflake ${snowflake_cost_medium:.6f} (runtime: {duckdb_runtime:.1f}s)"
        else:
            # Choose Snowflake
            engine = 'snowflake'
            # Select appropriate warehouse size based on EXPLAIN analysis and performance needs
            warehouse_size = self._select_warehouse_size_explain(sql, duckdb_runtime, snowflake_runtime, explain_analysis)
            # Recalculate Snowflake cost with selected warehouse
            snowflake_cost = self.cost_estimator.estimate_snowflake_cost(
                self._estimate_runtime_from_explain(sql, explain_analysis, 'snowflake', warehouse_size),
                warehouse_size
            )
            reason = f"Snowflake selected: ${snowflake_cost:.6f} (warehouse: {warehouse_size}) vs DuckDB ${duckdb_cost:.6f}"

        metadata = {
            'duckdb_runtime_seconds': duckdb_runtime,
            'snowflake_runtime_seconds': snowflake_runtime,
            'duckdb_cost_usd': duckdb_cost,
            'snowflake_cost_usd': snowflake_cost_medium,
            'can_use_duckdb': can_use_duckdb,
            'selected_warehouse': warehouse_size,
            'explain_analysis': explain_analysis,
            'reason': reason,
            'cpu_count': cpu_count,
            'available_memory_gb': available_memory_gb
        }

        logger.info(f"Engine selection: {engine} ({warehouse_size}) - {reason}")
        return engine, warehouse_size, metadata

    def _is_duckdb_viable(self, sql: str, explain_analysis: Dict[str, Any] = None) -> bool:
        """
        Determine if DuckDB is a viable option for this query based on EXPLAIN and resources.

        Args:
            sql: SQL query string
            explain_analysis: EXPLAIN analysis results (optional)

        Returns:
            True if DuckDB is viable, False otherwise
        """
        # Get available resources
        available_memory_gb = self.machine_specs.get('available_memory', 2 * 1024**3) / (1024**3)
        cpu_count = self.machine_specs.get('cpu_count', 1)

        # If we have EXPLAIN analysis, use it for more accurate viablility assessment
        if explain_analysis:
            # Extract key metrics from EXPLAIN
            scan_ops = explain_analysis.get('scan_operations', 0)
            join_ops = explain_analysis.get('join_operations', 0)
            agg_ops = explain_analysis.get('aggregation_operations', 0)
            estimated_complexity = explain_analysis.get('estimated_complexity', 0.5)
            operation_count = explain_analysis.get('operation_count', 1)

            # Estimate memory requirements based on operations
            # This is a simplified model - real systems would be more sophisticated
            base_memory_gb = 1.0  # Base memory requirement
            join_memory = join_ops * 0.5  # Each join might need extra memory for hash tables
            agg_memory = agg_ops * 0.3   # Aggregations might need memory for intermediate results
            scan_memory = scan_ops * 0.2  # Scans need some memory for buffering

            estimated_memory_gb = base_memory_gb + join_memory + agg_memory + scan_memory

            # Check if we have enough memory (use at most 60% of available memory for safety)
            max_usable_memory = available_memory_gb * 0.6
            if estimated_memory_gb > max_usable_memory:
                logger.debug(f"DuckDB not viable: needs {estimated_memory_gb:.2f}GB, have {max_usable_memory:.2f}GB usable")
                return False

            # Check if query is too complex for reasonable DuckDB execution time
            # Very complex queries might be better on Snowflake regardless of memory
            if estimated_complexity > 0.8 and operation_count > 20:
                logger.debug(f"DuckDB not viable: very complex query (complexity: {estimated_complexity:.2f}, ops: {operation_count})")
                return False

        else:
            # Fallback to heuristic checks when EXPLAIN not available
            sql_upper = sql.upper()

            # Basic viability checks
            max_query_time = 300  # 5 minutes max for DuckDB in this context
            max_memory_per_query_gb = available_memory_gb * 0.5  # Use at most 50% of available memory

            # Check for memory-intensive operations
            memory_intensive = any(keyword in sql_upper for keyword in ['GROUP BY', 'ORDER BY', 'DISTINCT', 'JOIN'])
            if memory_intensive:
                # Require more memory buffer for complex operations
                if available_memory_gb < 1:  # Less than 1GB available
                    return False

            # Check for potential spilling indicators
            large_aggregation = ('GROUP BY' in sql_upper and
                               any(agg in sql_upper for agg in ['COUNT(*)', 'SUM', 'AVG']) and
                               '_large_' in sql.lower())  # Simple heuristic

            if large_aggregation and available_memory_gb < 2:
                return False

        # Check CPU availability
        if cpu_count < 1:
            logger.warning(f"Insufficient CPU cores for DuckDB: {cpu_count}")
            return False

        return True

    def _estimate_runtimes_explain(self, sql: str, explain_analysis: Dict[str, Any] = None) -> Tuple[float, float]:
        """
        Estimate query runtime for both DuckDB and Snowflake using EXPLAIN when possible.

        Args:
            sql: SQL query string
            explain_analysis: Optional EXPLAIN analysis results

        Returns:
            Tuple of (duckdb_runtime_seconds, snowflake_runtime_seconds)
        """
        if explain_analysis:
            # Use EXPLAIN-based estimation
            duckdb_runtime = self.cost_estimator.estimate_runtime_from_explain(
                sql, explain_analysis, 'duckdb'
            )
            snowflake_runtime = self.cost_estimator.estimate_runtime_from_explain(
                sql, explain_analysis, 'snowflake', 'MEDIUM'  # Medium warehouse for baseline
            )
        else:
            # Fallback to heuristic estimation
            duckdb_runtime = self.cost_estimator._estimate_runtime_heuristic(sql, 'duckdb')
            snowflake_runtime = self.cost_estimator._estimate_runtime_heuristic(sql, 'snowflake')

        # Apply minimum bounds
        duckdb_runtime = max(duckdb_runtime, 0.1)  # At least 0.1 seconds
        snowflake_runtime = max(snowflake_runtime, 0.5)  # At least 0.5 seconds (overhead)

        return duckdb_runtime, snowflake_runtime

    def _select_warehouse_size_explain(self, sql: str, duckdb_runtime: float,
                                     snowflake_runtime_medium: float,
                                     explain_analysis: Dict[str, Any] = None) -> str:
        """
        Select appropriate Snowflake warehouse size based on EXPLAIN analysis and performance requirements.

        Args:
            sql: SQL query string
            duckdb_runtime: Estimated DuckDB runtime in seconds
            snowflake_runtime_medium: Estimated Snowflake runtime on MEDIUM warehouse in seconds
            explain_analysis: Optional EXPLAIN analysis results

        Returns:
            Warehouse size string (e.g., 'XSMALL', 'SMALL', 'MEDIUM', etc.)
        """
        if explain_analysis:
            # Use EXPLAIN-based analysis for more sophisticated warehouse selection
            return self._select_warehouse_from_explain(sql, explain_analysis, duckdb_runtime, snowflake_runtime_medium)
        else:
            # Fallback to original heuristic
            return self._select_warehouse_size_heuristic(sql, duckdb_runtime, snowflake_runtime_medium)

    def _select_warehouse_from_explain(self, sql: str, explain_analysis: Dict[str, Any],
                                     duckdb_runtime: float, snowflake_runtime_medium: float) -> str:
        """
        Select warehouse size based on EXPLAIN analysis.

        Args:
            sql: SQL query string
            explain_analysis: EXPLAIN analysis results
            duckdb_runtime: Estimated DuckDB runtime in seconds
            snowflake_runtime_medium: Estimated Snowflake runtime on MEDIUM warehouse in seconds

        Returns:
            Selected warehouse size string
        """
        # Extract key metrics from EXPLAIN
        scan_ops = explain_analysis.get('scan_operations', 0)
        join_ops = explain_analysis.get('join_operations', 0)
        agg_ops = explain_analysis.get('aggregation_operations', 0)
        sort_ops = explain_analysis.get('sort_operations', 0)
        has_limit = explain_analysis.get('has_limit', False)
        estimated_complexity = explain_analysis.get('estimated_complexity', 0.5)
        operation_count = explain_analysis.get('operation_count', 1)

        # Estimate data size factors from EXPLAIN if available
        # This would require more detailed EXPLAIN output with cardinality estimates
        # For now, we'll use operation counts as proxies

        # Base warehouse size decision on complexity and operation types
        # More complex queries with many joins/aggregations need larger warehouses

        complexity_factor = estimated_complexity
        join_factor = min(join_ops / 5.0, 1.0)  # Normalize join count
        agg_factor = min(agg_ops / 5.0, 1.0)    # Normalize aggregation count
        scan_factor = min(scan_ops / 10.0, 1.0) # Normalize scan count

        # Combined workload factor
        workload_factor = 1.0 + (complexity_factor * 0.4) + (join_factor * 0.3) + (agg_factor * 0.2) + (scan_factor * 0.1)

        # Adjust for presence of LIMIT (can reduce actual work needed)
        limit_factor = 0.7 if has_limit else 1.0

        # Target runtime we want to achieve (balanced between cost and performance)
        # We want Snowflake to be reasonably fast but not over-provisioned
        target_runtime = min(25.0, duckdb_runtime * 2.0)  # Don't want to be much slower than DuckDB option

        # Calculate required speedup factor
        if snowflake_runtime_medium > 0:
            current_runtime_factor = snowflake_runtime_medium / target_runtime
        else:
            current_runtime_factor = 1.0

        # Adjust required speedup by workload and limit factors
        adjusted_speedup_needed = current_runtime_factor * workload_factor * limit_factor

        # Map speedup to warehouse size (larger number = smaller warehouse)
        # XSMALL=1, SMALL=2, MEDIUM=4, LARGE=8, XLARGE=16, XXLARGE=32, XXXLARGE=64
        warehouse_mapping = [
            (0.25, 'XXXLARGE'),  # 4x speedup needed
            (0.5, 'XXLARGE'),    # 2x speedup needed
            (1.0, 'XLARGE'),     # Baseline speedup
            (2.0, 'LARGE'),      # 2x slower is OK
            (4.0, 'MEDIUM'),     # 4x slower is OK
            (8.0, 'SMALL'),      # 8x slower is OK
            (16.0, 'XSMALL')     # 16x slower is OK
        ]

        # Find the appropriate warehouse size
        for factor, size in warehouse_mapping:
            if adjusted_speedup_needed <= factor:
                return size

        # If we need even more power than XXXLARGE
        return 'XXXLARGE'

    def _select_warehouse_size_heuristic(self, sql: str, duckdb_runtime: float,
                                       snowflake_runtime_medium: float) -> str:
        """
        Original heuristic warehouse selection (fallback when EXPLAIN not available).

        Args:
            sql: SQL query string
            duckdb_runtime: Estimated DuckDB runtime in seconds
            snowflake_runtime_medium: Estimated Snowflake runtime on MEDIUM warehouse in seconds

        Returns:
            Selected warehouse size string
        """
        # Target maximum runtime we want to achieve (in seconds)
        target_max_runtime = min(30.0, duckdb_runtime * 3)  # Don't want to be much slower than DuckDB option

        # If Snowflake is already fast enough, use smallest economical warehouse
        if snowflake_runtime_medium <= target_max_runtime:
            # Try to minimize cost while meeting performance target
            if snowflake_runtime_medium <= 5.0:
                return 'XSMALL'
            elif snowflake_runtime_medium <= 10.0:
                return 'SMALL'
            else:
                return 'MEDIUM'

        # Need to scale up to meet performance target
        # Warehouse performance scales roughly linearly with size (1x, 2x, 4x, 8x, etc.)
        # XSMALL=1, SMALL=2, MEDIUM=4, LARGE=8, XLARGE=16, XXLARGE=32, XXXLARGE=64
        required_speedup = snowflake_runtime_medium / target_max_runtime

        # Map speedup to warehouse size
        if required_speedup <= 2:
            return 'SMALL'      # 2x speedup
        elif required_speedup <= 4:
            return 'MEDIUM'     # 4x speedup
        elif required_speedup <= 8:
            return 'LARGE'      # 8x speedup
        elif required_speedup <= 16:
            return 'XLARGE'     # 16x speedup
        elif required_speedup <= 32:
            return 'XXLARGE'    # 32x speedup
        else:
            return 'XXXLARGE'   # 64x speedup (or more)

def get_default_warehouse_size() -> str:
    """
    Get default warehouse size for simple queries.

    Returns:
        Default warehouse size string
    """
    return 'MEDIUM'