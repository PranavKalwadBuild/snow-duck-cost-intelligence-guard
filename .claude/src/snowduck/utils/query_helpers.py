"""
Helper functions to retrieve query SQL and table stats.
"""
from pathlib import Path
from typing import Dict, Any

def get_query_sql(query_name: str) -> str:
    """Extract SQL query from file."""
    # Assuming queries are located in <project_root>/queries/
    # We need to locate the project root: two levels up from this file? 
    # Since we are in .claude/src/snowduck/utils, project root is three levels up.
    # However we can rely on environment variable or assume the caller passes correct path.
    # For simplicity, we'll look in ../../queries relative to this file.
    base_dir = Path(__file__).resolve().parents[3]  # .claude
    query_path = base_dir / "queries" / f"{query_name}.sql"
    if not query_path.exists():
        raise FileNotFoundError(f"Query file not found: {query_path}")
    return query_path.read_text(encoding="utf-8")


def get_table_stats(query_name: str) -> Dict[str, Any]:
    """Extract table statistics (placeholder)."""
    # In a real implementation, parse the query to get table stats.
    # For now, return placeholder values.
    return {
        "size_gb": 1.0,
        "row_count": 100000,
    }
