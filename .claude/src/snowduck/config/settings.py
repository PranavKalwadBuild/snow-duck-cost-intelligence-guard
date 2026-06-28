"""
Configuration loader using Pydantic BaseSettings with YAML support.
"""
import os
import yaml
from pathlib import Path
from pydantic.v1 import BaseSettings, Field
from typing import Dict, Any, Optional


CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"


class SnowflakeWarehouseSettings(BaseSettings):
    mapping: Dict[str, str] = Field(
        default_factory=lambda: {
            "XSMALL": "COMPUTE_WH",
            "SMALL": "LOAD_TEST_WH_S",
            "MEDIUM": "LOAD_TEST_WH_M",
            "LARGE": "LOAD_TEST_WH_L",
            "XLARGE": "LOAD_TEST_WH_XL",
            "XXLARGE": "LOAD_TEST_WH_2XL",
        }
    )
    default_size: str = Field("MEDIUM", env="SNOWFLAKE_WAREHOUSE")


class SnowflakePricingSettings(BaseSettings):
    per_second: Dict[str, float] = Field(
        default_factory=lambda: {
            "XSMALL": 0.0005,
            "SMALL": 0.001,
            "MEDIUM": 0.002,
            "LARGE": 0.004,
            "XLARGE": 0.008,
            "XXLARGE": 0.016,
            "XXXLARGE": 0.032,
        }
    )


class SnowflakeConnectionSettings(BaseSettings):
    user: Optional[str] = Field(None, env="SNOWFLAKE_USER")
    password: Optional[str] = Field(None, env="SNOWFLAKE_PASSWORD")
    account: Optional[str] = Field(None, env="SNOWFLAKE_ACCOUNT")
    role: Optional[str] = Field(None, env="SNOWFLAKE_ROLE")
    warehouse: Optional[str] = Field(None, env="SNOWFLAKE_WAREHOUSE")
    database: Optional[str] = Field(None, env="SNOWFLAKE_DATABASE")
    schema_name: Optional[str] = Field(None, env="SNOWFLAKE_SCHEMA")
    authenticator: Optional[str] = Field(None, env="AUTHENTICATOR")

    def snowflake_connection_params(self) -> dict:
        """Return a dict of non‑None connection parameters."""
        params = {}
        for k, v in self.dict().items():
            if v is None:
                continue
            if k == "schema_name":
                params["schema"] = v
            elif k == "password" and self.authenticator == "externalbrowser":
                # Skip password when using external browser authenticator
                continue
            else:
                params[k] = v
        return params


class SnowflakeSettings(BaseSettings):
    warehouse: SnowflakeWarehouseSettings = SnowflakeWarehouseSettings()
    pricing_per_second: SnowflakePricingSettings = SnowflakePricingSettings()


class DuckDBSettings(BaseSettings):
    memory_fraction: float = Field(0.7, ge=0.1, le=1.0)
    max_runtime_seconds: int = Field(300, ge=1)


class CostSettings(BaseSettings):
    duckdb_cost_per_second: float = 0.000001


class Settings(BaseSettings):
    snowflake: SnowflakeSettings = SnowflakeSettings()
    connection: SnowflakeConnectionSettings = SnowflakeConnectionSettings()
    duckdb: DuckDBSettings = DuckDBSettings()
    cost: CostSettings = CostSettings()

    class Config:
        env_file = ".env"
        env_nested_delimiter = "__"

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "Settings":
        """Load settings from YAML file, overlaying environment variables."""
        if config_path is None:
            config_path = CONFIG_PATH
        data = {}
        if config_path.exists():
            with open(config_path, "rt") as f:
                data = yaml.safe_load(f) or {}
        # Replace empty strings with None so env vars can override
        def replace_empty(obj):
            if isinstance(obj, dict):
                return {k: replace_empty(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [replace_empty(i) for i in obj]
            elif obj == "":
                return None
            else:
                return obj
        data = replace_empty(data)
        # Pydantic will read env vars and .env; we need to pass data as initial values
        return cls(**data)

    def snowflake_connection_params(self) -> dict:
        """Return a dict of non‑None connection parameters."""
        params = {}
        for k, v in self.connection.dict().items():
            if v is None:
                continue
            if k == "schema_name":
                params["schema"] = v
            elif k == "password" and self.connection.authenticator == "externalbrowser":
                # Skip password when using external browser authenticator
                continue
            else:
                params[k] = v
        return params

    @property
    def _data(self):
        """Return a dict of all settings for debugging."""
        return self.dict()


# Load once at import time
settings = Settings.load()