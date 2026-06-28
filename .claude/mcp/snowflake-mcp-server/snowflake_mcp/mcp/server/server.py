"""
Mock MCP Server module for Python 3.9 compatibility
"""
import asyncio
from typing import AsyncIterator, Tuple, Any

class Server:
    """Mock MCP Server class"""

    def __init__(self, name: str = "unknown"):
        self.name = name
        self._handlers = {}

    def list_resources(self):
        """Decorator for listing resources"""
        def decorator(func):
            self._handlers['list_resources'] = func
            return func
        return decorator

    def read_resource(self):
        """Decorator for reading resources"""
        def decorator(func):
            self._handlers['read_resource'] = func
            return func
        return decorator

    def list_tools(self):
        """Decorator for listing tools"""
        def decorator(func):
            self._handlers['list_tools'] = func
            return func
        return decorator

    def call_tool(self):
        """Decorator for calling tools"""
        def decorator(func):
            self._handlers['call_tool'] = func
            return func
        return decorator

    def create_initialization_options(self):
        """Create initialization options"""
        return {}

    async def run(
        self,
        read_stream,
        write_stream,
        initialization_options,
    ) -> None:
        """Run the server (mock implementation)"""
        # This is a simplified mock - in reality this would handle the MCP protocol
        # For our purposes, we just need it to not crash when imported
        pass

def stdio_server() -> AsyncIterator[Tuple[Any, Any]]:
    """Mock stdio server that returns dummy streams"""
    async def mock_streams():
        # Return dummy objects that won't be used in our simple case
        class MockStream:
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            async def receive(self):
                return None
            async def send(self, message):
                pass

        yield (MockStream(), MockStream())

    return mock_streams()