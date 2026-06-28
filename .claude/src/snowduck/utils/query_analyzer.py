"""
Query analysis utility using EXPLAIN plans for cost estimation.
"""
import json
import logging
import re
from typing import Dict, Any, Tuple, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class QueryAnalyzer:
    """Analyzes queries using EXPLAIN plans to estimate resource requirements."""

    def __init__(self, duckdb_conn, snowflake_conn_factory):
        """
        Initialize query analyzer.

        Args:
            duckdb_conn: Active DuckDB connection
            snowflake_conn_factory: Function that returns a SnowflakeConnection instance
        """
        self.duckdb_conn = duckdb_conn
        self.snowflake_conn_factory = snowflake_conn_factory

    def analyze_query(self, sql: str) -> Dict[str, Any]:
        """
        Analyze a query using EXPLAIN on both platforms when possible.

        Args:
            sql: SQL query to analyze

        Returns:
            Dictionary with analysis results for both platforms
        """
        analysis = {
            'duckdb': self._analyze_duckdb_explain(sql),
            'snowflake': self._analyze_snowflake_explain(sql)
        }
        return analysis

    def _analyze_duckdb_explain(self, sql: str) -> Dict[str, Any]:
        """
        Get and parse EXPLAIN plan from DuckDB.

        Args:
            sql: SQL query to explain

        Returns:
            Dictionary with DuckDB EXPLAIN analysis
        """
        try:
            # DuckDB EXPLAIN returns a table with operator information
            explain_sql = f"EXPLAIN {sql}"
            result = self.duckdb_conn.execute(explain_sql).fetchall()

            if not result:
                return self._fallback_heuristic_analysis(sql, 'duckdb')

            # Convert to list of dictionaries for easier processing
            columns = [desc[0] for desc in self.duckdb_conn.description]
            plan_rows = [dict(zip(columns, row)) for row in result]

            # Analyze the plan
            return self._parse_explain_plan(plan_rows, 'duckdb')

        except Exception as e:
            logger.warning(f"Failed to get DuckDB EXPLAIN: {e}")
            return self._fallback_heuristic_analysis(sql, 'duckdb')

    def _analyze_snowflake_explain(self, sql: str) -> Dict[str, Any]:
        """
        Get and parse EXPLAIN plan from Snowflake via MCP.

        Args:
            sql: SQL query to explain

        Returns:
            Dictionary with Snowflake EXPLAIN analysis
        """
        try:
            # Get a Snowflake connection
            sf_conn = self.snowflake_conn_factory()

            # Use EXPLAIN to get the query plan
            explain_sql = f"EXPLAIN {sql}"
            result = sf_conn.process_request(explain_sql)

            # Clean up connection
            sf_conn.cleanup()

            if not result or not isinstance(result, list) or len(result) == 0:
                return self._fallback_heuristic_analysis(sql, 'snowflake')

            # Snowflake EXPLAIN returns JSON-like structure
            # The exact format may vary, but we'll try to parse it
            plan_data = result[0] if isinstance(result[0], dict) else {}

            # If the result is a string, try to parse as JSON
            if isinstance(plan_data, str):
                try:
                    plan_data = json.loads(plan_data)
                except json.JSONDecodeError:
                    # If it's not JSON, treat as text and parse heuristically
                    return self._parse_text_explain(plan_data, 'snowflake')

            return self._parse_explain_plan(plan_data, 'snowflake') if isinstance(plan_data, dict) else \
                   self._parse_text_explain(str(plan_data), 'snowflake')

        except Exception as e:
            logger.warning(f"Failed to get Snowflake EXPLAIN: {e}")
            return self._fallback_heuristic_analysis(sql, 'snowflake')

    def _parse_explain_plan(self, plan_data: dict, platform: str) -> Dict[str, Any]:
        """
        Parse EXPLAIN plan structure to estimate resource usage.

        Args:
            plan_data: Parsed EXPLAIN output
            platform: Either 'duckdb' or 'snowflake'

        Returns:
            Dictionary with resource estimates
        """
        # Initialize metrics
        metrics = {
            'operation_count': 0,
            'scan_operations': 0,
            'join_operations': 0,
            'aggregation_operations': 0,
            'sort_operations': 0,
            'has_limit': False,
            'estimated_complexity': 0.0,
            'raw_plan': plan_data
        }

        # Different parsing based on platform and structure
        if platform == 'duckdb':
            # DuckDB EXPLAIN typically returns rows with columns like:
            # id, parent_id, operator, estimate, etc.
            if isinstance(plan_data, list):
                for row in plan_data:
                    metrics['operation_count'] += 1
                    operator = str(row.get('operator', '')).upper()

                    if any(scan in operator for scan in ['SCAN', 'SEQ', 'HASH']):
                        metrics['scan_operations'] += 1
                    if 'JOIN' in operator:
                        metrics['join_operations'] += 1
                    if any(agg in operator for agg in ['AGGREGATE', 'HASH_GROUP']):
                        metrics['aggregation_operations'] += 1
                    if 'SORT' in operator:
                        metrics['sort_operations'] += 1
                    if 'LIMIT' in operator or 'LIMIT' in str(row.get('extra', '')).upper():
                        metrics['has_limit'] = True

                    # Extract estimate if available
                    estimate = row.get('estimate') or row.get('Estimated Cardinality')
                    if isinstance(estimate, (int, float)) and estimate > 0:
                        # Use log scale to prevent huge numbers from dominating
                        metrics['estimated_complexity'] += min(10, np.log10(float(estimate) + 1)) if 'np' in globals() else min(10, (len(str(int(estimate)))))

        elif platform == 'snowflake':
            # Snowflake EXPLAIN structure may vary
            # Common patterns: operations tree, or structured JSON
            if isinstance(plan_data, dict):
                # Recursively traverse the plan tree
                self._traverse_snowflake_plan(plan_data, metrics)
            elif isinstance(plan_data, list):
                for item in plan_data:
                    if isinstance(item, dict):
                        self._traverse_snowflake_plan(item, metrics)

        # Calculate overall complexity score (0-1 scale)
        # This is a simplified heuristic - in reality would be more sophisticated
        complexity_score = min(1.0, (
            (metrics['scan_operations'] * 0.1) +
            (metrics['join_operations'] * 0.3) +
            (metrics['aggregation_operations'] * 0.2) +
            (metrics['sort_operations'] * 0.15) +
            (min(metrics['operation_count'] / 10.0, 0.5))  # Base complexity from operation count
        ))

        metrics['estimated_complexity'] = complexity_score

        return metrics

    def _traverse_snowflake_plan(self, node: dict, metrics: Dict[str, Any]):
        """Recursively traverse Snowflake execution plan tree."""
        if not isinstance(node, dict):
            return

        # Count this operation
        metrics['operation_count'] += 1

        # Extract operation type
        operation = str(node.get('operation', node.get('nodeType', ''))).upper()

        if any(scan in operation for scan in ['TABLE', 'SCAN', 'SEQ']):
            metrics['scan_operations'] += 1
        if 'JOIN' in operation:
            metrics['join_operations'] += 1
        if any(agg in operation for agg in ['AGGREGATE', 'GROUP']):
            metrics['aggregation_operations'] += 1
        if 'SORT' in operation:
            metrics['sort_operations'] += 1
        if 'LIMIT' in operation:
            metrics['has_limit'] = True

        # Recursively process children
        # Common field names for children in query plans
        children_fields = ['children', 'inputs', 'input', 'child']
        for field in children_fields:
            if field in node and isinstance(node[field], list):
                for child in node[field]:
                    self._traverse_snowflake_plan(child, metrics)
                break  # Found children, no need to check other fields

    def _parse_text_explain(self, explain_text: str, platform: str) -> Dict[str, Any]:
        """
        Parse EXPLAIN output when it's returned as text.

        Args:
            explain_text: Text output from EXPLAIN
            platform: Either 'duckdb' or 'snowflake'

        Returns:
            Dictionary with resource estimates
        """
        metrics = {
            'operation_count': 0,
            'scan_operations': 0,
            'join_operations': 0,
            'aggregation_operations': 0,
            'sort_operations': 0,
            'has_limit': False,
            'estimated_complexity': 0.0,
            'raw_plan': explain_text
        }

        # Convert to uppercase for pattern matching
        text_upper = explain_text.upper()

        # Count lines as approximate operation count
        lines = [line.strip() for line in explain_text.split('\n') if line.strip()]
        metrics['operation_count'] = len(lines)

        # Look for operation types in the text
        metrics['scan_operations'] = len(re.findall(r'\b(SCAN|SEQ|TABLE)\b', text_upper))
        metrics['join_operations'] = len(re.findall(r'\bJOIN\b', text_upper))
        metrics['aggregation_operations'] = len(re.findall(r'\b(GROUP|AGGREGATE)\b', text_upper))
        metrics['sort_operations'] = len(re.findall(r'\bSORT\b', text_upper))
        metrics['has_limit'] = 'LIMIT' in text_upper

        # Calculate complexity score
        complexity_score = min(1.0, (
            (metrics['scan_operations'] * 0.1) +
            (metrics['join_operations'] * 0.3) +
            (metrics['aggregation_operations'] * 0.2) +
            (metrics['sort_operations'] * 0.15) +
            (min(metrics['operation_count'] / 10.0, 0.5))
        ))

        metrics['estimated_complexity'] = complexity_score

        return metrics

    def _fallback_heuristic_analysis(self, sql: str, platform: str) -> Dict[str, Any]:
        """
        Fallback to heuristic analysis when EXPLAIN fails.

        Args:
            sql: SQL query to analyze
            platform: Either 'duckdb' or 'snowflake'

        Returns:
            Dictionary with resource estimates based on heuristics
        """
        sql_upper = sql.upper()

        # Basic heuristics
        scan_ops = sql_upper.count('FROM') + sql_upper.count('JOIN')
        join_ops = sql_upper.count('JOIN')
        agg_ops = sum(1 for agg in ['GROUP BY', 'COUNT(', 'SUM(', 'AVG(', 'MIN(', 'MAX('] if agg in sql_upper)
        sort_ops = 1 if 'ORDER BY' in sql_upper else 0
        has_limit = 'LIMIT' in sql_upper or 'TOP' in sql_upper

        # Estimate operation count
        op_count = max(1, scan_ops + join_ops + agg_ops + sort_ops)

        # Calculate complexity score
        complexity_score = min(1.0, (
            (scan_ops * 0.1) +
            (join_ops * 0.3) +
            (agg_ops * 0.2) +
            (sort_ops * 0.15) +
            (min(op_count / 10.0, 0.5))
        ))

        return {
            'operation_count': op_count,
            'scan_operations': scan_ops,
            'join_operations': join_ops,
            'aggregation_operations': agg_ops,
            'sort_operations': sort_ops,
            'has_limit': has_limit,
            'estimated_complexity': complexity_score,
            'raw_plan': f"Heuristic analysis (EXPLAIN failed): {sql[:100]}..."
        }

# Global instance placeholder - will be initialized in agent.py
query_analyzer = None

def init_query_analyzer(duckdb_conn, snowflake_conn_factory):
    """Initialize the global query analyzer instance."""
    global query_analyzer
    query_analyzer = QueryAnalyzer(duckdb_conn, snowflake_conn_factory)
    return query_analyzer

def get_query_analyzer():
    """Get the global query analyzer instance."""
    global query_analyzer
    if query_analyzer is None:
        raise RuntimeError("Query analyzer not initialized. Call init_query_analyzer first.")
    return query_analyzer