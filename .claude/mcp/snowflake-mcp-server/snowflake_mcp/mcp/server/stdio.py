"""
STDIO server transport for MCP.
"""
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator, Tuple, Any, Optional

class StdinStream:
    async def receive(self) -> Optional[str]:
        loop = asyncio.get_event_loop()
        # Read a line from stdin
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return None
        return line.strip()

class StdoutStream:
    async def send(self, message: str) -> None:
        # Write message to stdout followed by newline
        sys.stdout.write(message + "\n")
        await asyncio.get_event_loop().run_in_executor(None, sys.stdout.flush)

@asynccontextmanager
async def stdio_server() -> AsyncIterator[Tuple[Any, Any]]:
    """Create stdio streams for MCP communication."""
    try:
        yield (StdinStream(), StdoutStream())
    except Exception as e:
        print(f"Error in stdio server: {e}", file=sys.stderr)
        raise