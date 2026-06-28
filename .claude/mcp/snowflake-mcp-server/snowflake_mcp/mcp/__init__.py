# MCP package init file
# Expose submodules for proper imports
from . import server
from . import types

# Also export commonly used classes/functions at top level for convenience
from .types import TextContent
from .server import Server, stdio_server

__all__ = ["server", "types", "Server", "stdio_server", "TextContent"]