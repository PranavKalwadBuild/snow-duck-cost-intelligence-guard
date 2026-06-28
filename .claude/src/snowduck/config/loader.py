"""
Configuration loader using Pydantic BaseSettings.
"""
from .settings import settings

def get_settings() -> "Settings":
    """Return the singleton settings object."""
    return settings
