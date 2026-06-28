"""
Cost estimation utility for the DuckDB/Snowflake agent.
"""
import math
from typing import Dict, Any, Optional

class CostEstimator:
    def __init__(self, machine_specs: Dict[str, Any]):
        """
        Initialize cost estimator with machine specifications.

        Args:
            machine_specs: Dictionary containing CPU, memory, disk information
        """
        self.machine_specs = machine_specs

        # Snowflake pricing estimates (USD per second) - these are approximate
        # In practice, these would be configurable or fetched from pricing API
        self.snowflake_pricing_per_second = {
            'XSMALL': 0.0005,   # ~$1.80/hour
            'SMALL': 0.001,     # ~$3.60/hour
            'MEDIUM': 0.002,    # ~$7.20/hour
            'LARGE': 0.004,     # ~$14.40/hour
            'XLARGE': 0.008,    # ~$28.80/hour
            'XXLARGE': 0.016,   # ~$57.60/hour
            'XXXLARGE': 0.032   # ~$115.20/hour
        }

        # DuckDB compute cost is near zero (just electricity)
        self.duckdb_cost_per_second = 0.000001  # Negligible

        # Reference performance metrics (would be calibrated in production)
        self.base_performance = {
            'duckdb': 1.0,   # Base performance score
            'snowflake': 1.0 # Base performance score (will be scaled by warehouse size)
        }

    def estimate_duckdb_cost(self, estimated_runtime_seconds: float) -> float:
        """
        Estimated cost of running query in DuckDB.

        Args:
            estimated_runtime_seconds: Estimated query runtime in seconds

        Returns:
            Estimated cost in USD
        """
        return estimated_runtime_seconds * self.duckdb_cost_per_second

    def estimate_snowflake_cost(self, estimated_runtime_seconds: float, warehouse_size: str) -> float:
        """
        Estimated cost of running query in Snowflake.

        Args:
            estimated_runtime_seconds: Estimated query runtime in seconds
            warehouse_size: Snowflake warehouse size

        Returns:
            Estimated cost in USD
        """
        cost_per_second = self.snowflake_pricing_per_second.get(
            warehouse_size.upper(),
            self.snowflake_pricing_per_second['MEDIUM']  # Default to MEDIUM
        )
        return estimated_runtime_seconds * cost_per_second

    def estimate_query_complexity_from_explain(self, explain_analysis: Dict[str, Any]) -> float:
        """
        Extract complexity score from EXPLAIN analysis.

        Args:
            explain_analysis: Output from query analyzer

        Returns:
            Complexity score (0.0 to 1.0+)
        """
        if not explain_analysis:
            return 0.5  # Default medium complexity

        # Use the estimated_complexity from the analysis if available
        complexity = explain_analysis.get('estimated_complexity', 0.5)
        return max(0.1, min(2.0, complexity))  # Clamp to reasonable range

    def estimate_runtime_from_explain(self, sql: str, explain_analysis: Dict[str, Any],
                                    engine: str, warehouse_size: str = None) -> float:
        """
        Estimate query runtime based on EXPLAIN analysis and system characteristics.

        Args:
            sql: SQL query string
            explain_analysis: EXPLAIN analysis results
            engine: Target engine ('duckdb' or 'snowflake')
            warehouse_size: Snowflake warehouse size (if engine is snowflake)

        Returns:
            Estimated runtime in seconds
        """
        if not explain_analysis:
            # Fallback to heuristic estimation
            return self._estimate_runtime_heuristic(sql, engine, warehouse_size)

        # Get complexity score from EXPLAIN
        complexity = self.estimate_query_complexity_from_explain(explain_analysis)

        # Base runtime estimates (in seconds) for a query of complexity 1.0
        base_runtime = 1.0  # 1 second for complexity 1.0 on reference hardware

        # Adjust based on operation counts from EXPLAIN
        operation_count = explain_analysis.get('operation_count', 1)
        scan_ops = explain_analysis.get('scan_operations', 0)
        join_ops = explain_analysis.get('join_operations', 0)
        agg_ops = explain_analysis.get('aggregation_operations', 0)
        sort_ops = explain_analysis.get('sort_operations', 0)

        # Calculate workload factor based on operation types
        workload_factor = 1.0 + (
            (scan_ops * 0.1) +
            (join_ops * 0.5) +  # Joins are typically more expensive
            (agg_ops * 0.3) +   # Aggregations medium cost
            (sort_ops * 0.4)    # Sorting can be expensive
        ) * (operation_count / 10.0)  # Scale with number of operations

        # Adjust based on engine and warehouse
        if engine == 'duckdb':
            # DuckDB performance depends on available memory and CPU
            memory_gb = self.machine_specs.get('available_memory', 4 * 1024**3) / (1024**3)
            cpu_count = self.machine_specs.get('cpu_count', 1)

            # Normalize to reference system (4GB RAM, 2 CPU cores)
            memory_factor = max(0.5, min(2.0, memory_gb / 4.0))
            cpu_factor = max(0.5, min(2.0, cpu_count / 2.0))

            # DuckDB is efficient for moderate-sized data that fits in memory
            resource_factor = (memory_factor * cpu_factor) ** 0.7  # Diminishing returns

        else:  # snowflake
            # Snowflake performance scales with warehouse size
            warehouse_factors = {
                'XSMALL': 0.5,
                'SMALL': 1.0,
                'MEDIUM': 2.0,
                'LARGE': 4.0,
                'XLARGE': 8.0,
                'XXLARGE': 16.0,
                'XXXLARGE': 32.0
            }
            warehouse_factor = warehouse_factors.get(
                warehouse_size.upper() if warehouse_size else 'MEDIUM',
                2.0  # Default to MEDIUM
            )
            # Larger warehouses execute faster (but cost more)
            resource_factor = warehouse_factor  # Direct scaling

        # Calculate estimated runtime
        estimated_runtime = base_runtime * complexity * workload_factor / resource_factor

        # Ensure minimum runtime
        return max(estimated_runtime, 0.1)

    def _estimate_runtime_heuristic(self, sql: str, engine: str, warehouse_size: str = None) -> float:
        """
        Fallback heuristic estimation when EXPLAIN is not available.

        Args:
            sql: SQL query string
            engine: Target engine ('duckdb' or 'snowflake')
            warehouse_size: Snowflake warehouse size (if engine is snowflake)

        Returns:
            Estimated runtime in seconds
        """
        sql_upper = sql.upper()

        # Basic complexity factors
        has_joins = 'JOIN' in sql_upper
        has_aggregation = any(agg in sql_upper for agg in ['GROUP BY', 'COUNT(', 'SUM(', 'AVG(', 'MIN(', 'MAX('])
        has_window = 'OVER (' in sql_upper or 'PARTITION BY' in sql_upper
        has_recursive = 'RECURSIVE' in sql_upper
        has_cte = 'WITH' in sql_upper

        # Base complexity
        complexity = 0.2  # Base
        if has_joins: complexity += 0.3
        if has_aggregation: complexity += 0.2
        if has_window: complexity += 0.2
        if has_recursive: complexity += 0.3
        if has_cte: complexity += 0.1

        # Cap complexity
        complexity = min(1.0, complexity)

        # Base runtime
        base_runtime = 1.0

        if engine == 'duckdb':
            # DuckDB performance depends on available memory and CPU
            memory_gb = self.machine_specs.get('available_memory', 4 * 1024**3) / (1024**3)
            cpu_count = self.machine_specs.get('cpu_count', 1)

            # Normalize to reference system (4GB RAM, 2 CPU cores)
            memory_factor = max(0.5, min(2.0, memory_gb / 4.0))
            cpu_factor = max(0.5, min(2.0, cpu_count / 2.0))

            # DuckDB is efficient for moderate-sized data that fits in memory
            resource_factor = (memory_factor * cpu_factor) ** 0.7

        else:  # snowflake
            # Snowflake performance scales with warehouse size
            warehouse_factors = {
                'XSMALL': 0.5,
                'SMALL': 1.0,
                'MEDIUM': 2.0,
                'LARGE': 4.0,
                'XLARGE': 8.0,
                'XXLARGE': 16.0,
                'XXXLARGE': 32.0
            }
            warehouse_factor = warehouse_factors.get(
                warehouse_size.upper() if warehouse_size else 'MEDIUM',
                2.0  # Default to MEDIUM
            )
            resource_factor = warehouse_factor

        estimated_runtime = base_runtime * (1.0 + complexity) / resource_factor
        return max(estimated_runtime, 0.1)