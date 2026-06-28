"""
Mock MCP types for Python 3.9 compatibility
"""
from typing import Optional, Any, Dict, List, Union
from pydantic import AnyUrl, BaseModel, Field


class TextContent:
    """Text content type"""

    def __init__(self, type: str, text: str):
        self.type = type
        self.text = text


class Resource(BaseModel):
    """Resource model"""

    name: str
    description: Optional[str] = None
    uri: AnyUrl
    mimeType: Optional[str] = None


class Tool(BaseModel):
    """Tool model"""

    name: str
    description: Optional[str] = None
    inputSchema: dict[str, Any] = Field(default_factory=dict)


# For backward compatibility with direct imports
__all__ = ["TextContent", "Resource", "Tool"]