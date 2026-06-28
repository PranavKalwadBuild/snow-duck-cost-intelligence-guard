"""
Factory for creating Snowflake connections with temporary environment
variables to avoid polluting the global os.environ.
"""
import os
import contextlib
import logging
from typing import Optional, Dict

# Import the SnowflakeConnection from the MCP server
MCP_PATH = (
    __file__
)  # we will compute path dynamically; easier: add to sys.path in __init__.py? but we'll do here
import sys
from pathlib import Path

# Add the MCP server to path
_mcp_path = Path(__file__).resolve().parents[3] / "mcp" / "snowflake-mcp-server"
print(f"[DEBUG] MCP path: {_mcp_path}", file=sys.stderr)
if str(_mcp_path) not in sys.path:
    sys.path.insert(0, str(_mcp_path))

from snowflake_mcp.connection import SnowflakeConnection  # type: ignore

logger = logging.getLogger(__name__)


class SnowflakeConnectionFactory:
    """Factory that creates SnowflakeConnection with optional overrides."""

    def __init__(self, defaults: Optional[Dict[str, str]] = None):
        """
        Args:
            defaults: dict with keys like 'user', 'password', 'account', 'role',
                      'warehouse', 'database', 'schema'. If None, empty dict.
        """
        self.defaults = defaults or {}
        # Capture the original environment at instantiation
        self._original_env = dict(os.environ)

    @contextlib.contextmanager
    def temporary_env(self, **overrides):
        """
        Context manager that temporarily sets Snowflake-related env vars.
        Starts from defaults, then applies overrides.
        After exiting, restores the original environment.
        """
        # Start with defaults
        params = dict(self.defaults)
        # Override with passed kwargs
        params.update({k: v for k, v in overrides.items() if v is not None})

        # Map to env var names
        env_map = {
            "user": "SNOWFLAKE_USER",
            "password": "SNOWFLAKE_PASSWORD",
            "account": "SNOWFLAKE_ACCOUNT",
            "role": "SNOWFLAKE_ROLE",
            "warehouse": "SNOWFLAKE_WAREHOUSE",
            "database": "SNOWFLAKE_DATABASE",
            "schema": "SNOWFLAKE_SCHEMA",
        }

        # Determine which vars we will change
        vars_to_set = {}
        for key, env_var in env_map.items():
            if key in params:
                vars_to_set[env_var] = params[key]

        # Save current values for these keys
        old_values = {k: os.environ.get(k) for k in vars_to_set}
        # Apply new values
        for k, v in vars_to_set.items():
            os.environ[k] = v
        try:
            yield
        finally:
            # Restore original values
            for k, old_val in old_values.items():
                if old_val is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = old_val

    def create_connection(self) -> SnowflakeConnection:
        """Create a new SnowflakeConnection using the current environment."""
        logger.debug("Creating SnowflakeConnection with current environment")
        return SnowflakeConnection()
