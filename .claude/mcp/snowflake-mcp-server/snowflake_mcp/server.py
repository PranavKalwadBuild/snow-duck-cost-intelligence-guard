import os
import asyncio
import logging
import json
import time
from typing import Optional, Any, Dict, List
import mimetypes
from pathlib import Path
import snowflake.connector
from dotenv import load_dotenv
import sys

# Add the project root to Python path so we can import snowflake_mcp
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.insert(0, project_root)

# Use our local MCP implementation instead of the external package
from snowflake_mcp.mcp.server import Server
from snowflake_mcp.mcp.types import Resource, Tool, TextContent
from snowflake_mcp.mcp.server import stdio
from snowflake_mcp.connection import SnowflakeConnection

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('snowflake_server')

load_dotenv()


class SnowflakeServer(Server):
    """MCP server that handles Snowflake database operations with metadata discovery."""

    def __init__(self) -> None:
        """Initialize the MCP server with a Snowflake connection."""
        super().__init__(name="snowflake-server")
        self.db = SnowflakeConnection()
        logger.info("SnowflakeServer initialized")

        # Set up resources
        @self.list_resources()
        async def list_resources():
            """Expose static resources from the local resources directory."""
            resources_dir = Path(__file__).parent / "resources"
            items: List[Resource] = []
            if resources_dir.exists() and resources_dir.is_dir():
                for entry in resources_dir.iterdir():
                    if entry.is_file():
                        mime_type, _ = mimetypes.guess_type(entry.name)
                        uri = f"file://{entry.resolve()}"
                        items.append(
                            Resource(
                                name=entry.name,
                                description=f"Static resource: {entry.name}",
                                uri=uri,  # type: ignore[arg-type]
                                mimeType=mime_type or "application/octet-stream",  # type: ignore[call-arg]
                            )
                        )
            return items

        @self.read_resource()
        async def read_resource(uri: str):
            """Read and return the contents of a text-like resource."""
            try:
                # Support only local file URIs
                if not uri.startswith("file://"):
                    return [TextContent(type="text", text=f"Unsupported URI scheme: {uri}")]
                # Convert file URI to path
                path = Path(uri[7:])  # Remove 'file://' prefix
                if not path.exists() or not path.is_file():
                    return [TextContent(type="text", text=f"Resource not found: {path}")]
                mime_type, _ = mimetypes.guess_type(path.name)
                # Return textual content only; for binary types advise using the URI
                if mime_type and (mime_type.startswith("text/") or mime_type in {"application/json", "application/sql"}):
                    text = path.read_text(encoding="utf-8", errors="replace")
                    return [TextContent(type="text", text=text)]
                return [TextContent(type="text", text=f"Binary resource. Use URI directly: file://{path.resolve()}")]
            except Exception as e:
                logger.error(f"Failed to read resource {uri}: {e}")
                return [TextContent(type="text", text=f"Error reading resource: {e}")]

        # Set up tools
        @self.list_tools()
        async def get_supported_operations():
            """Return list of available tools."""
            return [
                Tool(
                    name="process_req",
                    description="Execute a SQL query on Snowflake",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "SQL query to execute"
                            }
                        },
                        "required": ["query"]
                    }
                ),
                Tool(
                    name="inspect_schema",
                    description="Get database schema information",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "table_name": {
                                "type": "string",
                                "description": "Specific table name to inspect (optional)"
                            },
                            "schema_name": {
                                "type": "string",
                                "description": "Schema name to inspect (optional)"
                            }
                        },
                        "required": ["table_name", "schema_name"]
                    }
                ),
                Tool(
                    name="analyze_performance",
                    description="Analyze query performance and suggest optimizations",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "SQL query to analyze"
                            },
                            "explain_plan": {
                                "type": "boolean",
                                "description": "Include execution plan",
                                "default": True
                            }
                        },
                        "required": ["query"]
                    }
                ),
                Tool(
                    name="check_data_quality",
                    description="Run data quality checks on tables",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "table_name": {
                                "type": "string",
                                "description": "Table name to check"
                            }
                        },
                        "required": ["table_name"]
                    }
                ),
                Tool(
                    name="list_databases",
                    description="List all databases accessible to the current user",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                ),
                Tool(
                    name="list_schemas",
                    description="List all schemas in a database",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "database_name": {
                                "type": "string",
                                "description": "Database name (optional - if not provided, lists schemas from all databases)"
                            }
                        },
                        "required": ["database_name"]
                    }
                ),
                Tool(
                    name="list_tables",
                    description="List all tables in a database/schema",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "database_name": {
                                "type": "string",
                                "description": "Database name (optional)"
                            },
                            "schema_name": {
                                "type": "string",
                                "description": "Schema name (optional)"
                            },
                            "checks": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["null_check", "duplicate_check", "range_check", "format_check"]
                                },
                                "description": "Types of checks to perform",
                                "default": ["null_check", "duplicate_check"]
                            }
                        },
                        "required": ["database_name", "schema_name"]
                    }
                ),
                Tool(
                    name="describe_table",
                    description="Get detailed information about a specific table including columns and metadata",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "table_name": {
                                "type": "string",
                                "description": "Name of the table to describe"
                            },
                            "database_name": {
                                "type": "string",
                                "description": "Database name (optional)"
                            },
                            "schema_name": {
                                "type": "string",
                                "description": "Schema name (optional)"
                            }
                        },
                        "required": ["table_name", "database_name", "schema_name"]
                    }
                ),
                Tool(
                    name="get_table_sample",
                    description="Get a sample of data from a table",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "table_name": {
                                "type": "string",
                                "description": "Name of the table to sample"
                            },
                            "database_name": {
                                "type": "string",
                                "description": "Database name (optional)"
                            },
                            "schema_name": {
                                "type": "string",
                                "description": "Schema name (optional)"
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Number of rows to sample (default: 10, max: 100)",
                                "minimum": 1,
                                "maximum": 100
                            }
                        },
                        "required": ["table_name", "database_name", "schema_name"]
                    }
                ),
                Tool(
                    name="get_column_stats",
                    description="Get statistical information about a specific column",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "table_name": {
                                "type": "string",
                                "description": "Name of the table"
                            },
                            "column_name": {
                                "type": "string",
                                "description": "Name of the column"
                            },
                            "database_name": {
                                "type": "string",
                                "description": "Database name (optional)"
                            },
                            "schema_name": {
                                "type": "string",
                                "description": "Schema name (optional)"
                            }
                        },
                        "required": ["table_name", "column_name", "database_name", "schema_name"]
                    }
                ),
                Tool(
                    name="search_tables",
                    description="Search for tables by name or comment",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "search_term": {
                                "type": "string",
                                "description": "Term to search for in table names and comments"
                            },
                            "database_name": {
                                "type": "string",
                                "description": "Database name to limit search (optional)"
                            }
                        },
                        "required": ["search_term", "database_name"]
                    }
                ),
                Tool(
                    name="search_columns",
                    description="Search for columns by name or comment",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "search_term": {
                                "type": "string",
                                "description": "Term to search for in column names and comments"
                            },
                            "database_name": {
                                "type": "string",
                                "description": "Database name to limit search (optional)"
                            }
                        },
                        "required": ["search_term", "database_name"]
                    }
                ),
                Tool(
                    name="get_warehouse_info",
                    description="Get comprehensive information about available warehouses including usage statistics and performance metrics",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                ),
                Tool(
                    name="create_stored_procedure",
                    description="Create a stored procedure in Snowflake from a .sql file",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "sql_file_path": {
                                "type": "string",
                                "description": "Path to the .sql file containing the stored procedure definition"
                            },
                            "database_name": {
                                "type": "string",
                                "description": "Database name to create the procedure in (optional)"
                            },
                            "schema_name": {
                                "type": "string",
                                "description": "Schema name to create the procedure in (optional)"
                            },
                            "replace_if_exists": {
                                "type": "boolean",
                                "description": "Replace procedure if it already exists (default: true)"
                            }
                        },
                        "required": ["sql_file_path"]
                    }
                ),
                Tool(
                    name="compare_tables",
                    description="Compare schema and row counts of two Snowflake tables, highlighting column-only differences, type mismatches, and optionally differing rows",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "table1_name": {
                                "type": "string",
                                "description": "Name of the first table"
                            },
                            "table2_name": {
                                "type": "string",
                                "description": "Name of the second table"
                            },
                            "database_name": {
                                "type": "string",
                                "description": "Database name (optional)"
                            },
                            "schema_name": {
                                "type": "string",
                                "description": "Schema name (optional)"
                            },
                            "columns_to_compare": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Restrict comparison to these specific columns (optional)"
                            },
                            "where_clause": {
                                "type": "string",
                                "description": "SQL WHERE clause (without the WHERE keyword) to filter rows in both tables before comparing (optional)"
                            },
                            "compare_data": {
                                "type": "boolean",
                                "description": "Also diff row-level data on shared/requested columns, capped at 1000 rows (default: false)"
                            }
                        },
                        "required": ["table1_name", "table2_name"]
                    }
                ),
                Tool(
                    name="put_file",
                    description="Upload a file to a Snowflake stage",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "local_file_path": {
                                "type": "string",
                                "description": "Path to the local file to upload"
                            },
                            "stage_path": {
                                "type": "string",
                                "description": "Snowflake stage path (e.g., '@my_stage/path/')"
                            },
                            "auto_compress": {
                                "type": "boolean",
                                "description": "Whether to auto-compress the file (default: true)"
                            },
                            "overwrite": {
                                "type": "boolean",
                                "description": "Whether to overwrite existing file (default: true)"
                            }
                        },
                        "required": ["local_file_path", "stage_path"]
                    }
                ),
                Tool(
                    name="get_table_metadata",
                    description="Get metadata about a specific table including row count and size information",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "table_name": {
                                "type": "string",
                                "description": "Name of the table"
                            },
                            "database_name": {
                                "type": "string",
                                "description": "Database name (optional)"
                            },
                            "schema_name": {
                                "type": "string",
                                "description": "Schema name (optional)"
                            }
                        },
                        "required": ["table_name"]
                    }
                ),
                Tool(
                    name="create_stage",
                    description="Create a stage in Snowflake",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "stage_name": {
                                "type": "string",
                                "description": "Name of the stage to create"
                            },
                            "is_temporary": {
                                "type": "boolean",
                                "description": "Whether the stage is temporary (default: true)"
                            }
                        }
                    }
                )
            ]

        # Tool call handler
        @self.call_tool()
        async def handle_tool_call(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            start_time = time.time()
            try:
                if name == "process_req":
                    result = self.db.process_request(arguments["query"])
                elif name == "inspect_schema":
                    result = self.db.inspect_schema(
                        arguments.get("table_name"),
                        arguments.get("schema_name")
                    )
                elif name == "analyze_performance":
                    result = self.db.analyze_performance(
                        arguments["query"],
                        arguments.get("explain_plan", True)
                    )
                elif name == "check_data_quality":
                    result = self.db.check_data_quality(
                        arguments["table_name"],
                        arguments.get("schema_name"),
                        arguments.get("checks", [])
                    )
                elif name == "list_databases":
                    result = self.db.list_databases()
                elif name == "list_schemas":
                    result = self.db.list_schemas(arguments.get("database_name"))
                elif name == "list_tables":
                    result = self.db.list_tables(
                        arguments.get("database_name"),
                        arguments.get("schema_name"),
                    )
                elif name == "describe_table":
                    result = self.db.describe_table(
                        arguments["table_name"],
                        arguments.get("database_name"),
                        arguments.get("schema_name"),
                    )
                elif name == "get_table_sample":
                    result = self.db.get_table_sample(
                        arguments["table_name"],
                        arguments.get("database_name"),
                        arguments.get("schema_name"),
                        arguments.get("limit", 10)
                    )
                elif name == "get_column_stats":
                    result = self.db.get_column_stats(
                        arguments["table_name"],
                        arguments["column_name"],
                        arguments.get("database_name"),
                        arguments.get("schema_name")
                    )
                elif name == "search_tables":
                    result = self.db.search_tables(
                        arguments["search_term"],
                        arguments.get("database_name")
                    )
                elif name == "search_columns":
                    result = self.db.search_columns(
                        arguments["search_term"],
                        arguments.get("database_name")
                    )
                elif name == "get_warehouse_info":
                    result = self.db.get_warehouse_info()
                elif name == "create_stored_procedure":
                    result = self.db.create_stored_procedure(
                        arguments["sql_file_path"],
                        arguments.get("database_name"),
                        arguments.get("schema_name"),
                        arguments.get("replace_if_exists", True)
                    )
                elif name == "compare_tables":
                    result = self.db.compare_tables(
                        arguments["table1_name"],
                        arguments["table2_name"],
                        arguments.get("database_name"),
                        arguments.get("schema_name"),
                        arguments.get("columns_to_compare"),
                        arguments.get("where_clause"),
                        arguments.get("compare_data", False)
                    )
                elif name == "put_file":
                    result = self.db.put_file(
                        arguments["local_file_path"],
                        arguments["stage_path"],
                        arguments.get("auto_compress", True),
                        arguments.get("overwrite", True)
                    )
                elif name == "get_table_metadata":
                    result = self.db.get_table_metadata(
                        arguments["table_name"],
                        arguments.get("database_name"),
                        arguments.get("schema_name")
                    )
                elif name == "create_stage":
                    result = self.db.create_stage(
                        arguments["stage_name"],
                        arguments.get("is_temporary", True)
                    )
                else:
                    return [TextContent(type="text", text=f"Unknown tool: {name}")]

                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
            except Exception as exc:
                logger.error("Tool %s failed: %s", name, exc, exc_info=True)
                return [TextContent(type="text", text=f"Error in {name}: {exc}")]

    async def run(
        self,
        read_stream,
        write_stream,
        initialization_options,
    ) -> None:
        """Run the server, handling JSON-RPC messages over stdio."""
        logger.info("Starting server")
        none_count = 0
        try:
            while True:
                # Read a line from stdin
                message_str = await read_stream.receive()
                if message_str is None:
                    none_count += 1
                    if none_count > 100:  # after 100 consecutive None, break
                        break
                    else:
                        # Wait a bit before trying again
                        await asyncio.sleep(0.1)
                        continue
                else:
                    none_count = 0
                    # Parse the JSON-RPC message
                    try:
                        message = json.loads(message_str)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON: {e}")
                        # Send error response
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": None,  # We don't have an id from the malformed request
                            "error": {
                                "code": -32700,
                                "message": "Parse error"
                            }
                        }
                        await write_stream.send(json.dumps(error_response))
                        continue

                # Check if it's a request (has 'method')
                if "method" in message:
                    method = message["method"]
                    msg_id = message.get("id")

                    # Handle different methods
                    if method == "initialize":
                        # Initialize request
                        result = {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {
                                "resources": {},
                                "tools": {}
                            },
                            "serverInfo": {
                                "name": self.name,
                                "version": "0.1.0"
                            }
                        }
                        response = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": result
                        }
                    elif method == "notifications/initialized":
                        # Notification, no response needed
                        continue
                    elif method == "ping":
                        # Ping request
                        response = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": {}
                        }
                    elif method == "resources/list":
                        # List resources
                        result = await self._handlers.get('list_resources', lambda: [])()
                        response = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": result
                        }
                    elif method == "resources/read":
                        # Read resource
                        uri = message["params"]["uri"]
                        result = await self._handlers.get('read_resource', lambda _: [])(uri)
                        response = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": result
                        }
                    elif method == "tools/list":
                        # List tools
                        result = await self._handlers.get('list_tools', lambda: [])()
                        response = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": result
                        }
                    elif method == "tools/call":
                        # Call a tool
                        name = message["params"]["name"]
                        arguments = message["params"].get("arguments", {})
                        result = await self._handlers.get('call_tool', lambda _, __: [])(name, arguments)
                        response = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "result": result
                        }
                    else:
                        # Unknown method
                        response = {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "error": {
                                "code": -32601,
                                "message": f"Method not found: {method}"
                            }
                        }

                    # Send response
                    await write_stream.send(json.dumps(response))
                else:
                    # This might be a response or notification we don't care about
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Server error: {e}", exc_info=True)
        finally:
            logger.info("Server shutting down")

    def __del__(self) -> None:
        """Clean up resources when the server is deleted."""
        if hasattr(self, "db"):
            self.db.cleanup()


async def start_service() -> None:
    """Start and run the MCP server."""
    try:
        # Initialize the server
        server = SnowflakeServer()
        initialization_options = server.create_initialization_options()
        logger.info("Starting server")

        # Run the server using stdio communication
        async with stdio.stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                initialization_options
            )
    except Exception as e:
        logger.critical(f"Server failed: {str(e)}", exc_info=True)
        raise
    finally:
        logger.info("Server shutting down")


if __name__ == "__main__":
    asyncio.run(start_service())