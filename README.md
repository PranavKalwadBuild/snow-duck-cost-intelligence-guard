# SnowDuck: Intelligent Query Routing Agent

SnowDuck is an intelligent agent that routes SQL queries between DuckDB and Snowflake based on dialect compatibility, cost estimation, and machine specifications. It uses a skill-based architecture with hot-reload capabilities, dependency injection, and a secure MCP boundary for Snowflake interactions.

## Features

- **Skill-Based Architecture**: Extendable skills (e.g., dialect checking) with automatic discovery and hot-reload.
- **Configuration Management**: YAML-based configuration with environment variable overrides using Pydantic.
- **Dialect Compatibility**: Uses sqlglot to detect Snowflake-specific syntax and recommend the appropriate engine.
- **Cost Estimation**: Estimates query cost using EXPLAIN-like analysis and machine specs.
- **Engine Selection**: Chooses between DuckDB (in-memory) and Snowflake based on compatibility, cost, and resource constraints.
- **Secure MCP Boundary**: Snowflake connections are created via a context manager that temporarily sets environment variables, avoiding global mutation.
- **Hot-Reload Skills**: Skills are reloaded automatically when their source files change (using watchdog).
- **Dependency Injection**: Core components (settings, skill registry, machine specs, etc.) are injected for testability and loose coupling.
- **Structured Logging**: Timed and contextual logging for debugging and monitoring.

## Directory Structure

```
snow-duck-cost-intellgent-guard/
├── .claude/                     # Claude Code specific files (skills, agents, commands, etc.)
│   ├── agents/                  # Claude Code agent definitions
│   ├── commands/                # Custom Claude Code commands
│   ├── config/                  # Configuration files (e.g., settings.yaml)
│   ├── mcp/                     # MCP servers (Snowflake MCP server)
│   ├── queries/                 # SQL query files
│   ├── scripts/                 # Backup scripts
│   ├── skills/                  # Legacy skill definitions (Markdown)
│   └── src/                     # Main Python source code
│       └── snowduck/
│           ├── agent.py         # Main entrypoint
│           ├── config/          # Configuration loading (Pydantic BaseSettings)
│           │   ├── loader.py
│           │   └── settings.py
│           ├── orchestrator.py  # Orchestrator class coordinating workflow
│           ├── skills/          # Skill implementations
│           │   ├── base.py      # Abstract Skill base class
│           │   ├── dialect.py   # Dialect check skill
│           │   └── registry.py  # Skill discovery and hot-reload
│           ├── ui.py            # Optional UI components
│           └── utils/           # Utility modules
│               ├── __init__.py
│               ├── cost_estimator.py
│               ├── engine_selector.py
│               ├── machine_utils.py
│               ├── query_analyzer.py
│               ├── query_helpers.py
│               └── snowflake_factory.py  # Secure Snowflake connection factory
├── queries/                     # SQL query files (also accessible via .claude/queries/)
│   ├── q1.sql
│   └── snowflake_sample_data_queries.sql
└── requirements.txt             # Python dependencies
```

*Note: The `.claude` directory is used by Claude Code for skills, agents, and configuration. The main Python package resides in `.claude/src/snowduck`.*

## Installation

1. Clone the repository.
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Ensure you have a Snowflake account and set the required environment variables (see Configuration below).

## Configuration

Configuration is managed via `settings.yaml` (located at `.claude/config/settings.yaml`) with optional environment variable overrides.

### settings.yaml Example

```yaml
duckdb:
  memory_fraction: 0.6  # Fraction of total RAM to allocate to DuckDB

snowflake_connection:
  account: "your_account"
  user: "your_user"
  password: "your_password"  # Can also be set via SNOWFLAKE_PASSWORD env var
  role: "your_role"
  warehouse: "your_warehouse"
  database: "your_database"
  schema: "your_schema"

snowflake_warehouse:
  default_size: "XSMALL"  # Default warehouse size if not overridden
  max_size: "XLarge"

logging:
  level: "INFO"
```

### Environment Variables

Environment variables override settings in `settings.yaml`. Use the same keys in uppercase with underscores, prefixed with `SNOWDUCK_` for top-level sections.

Examples:
- `SNOWDUCK_DUCKDB_MEMORY_FRACTION=0.5`
- `SNOWDUCK_SNOWFLAKE_CONNECTION_ACCOUNT="myaccount"`
- `SNOWDUCK_SNOWFLAKE_CONNECTION_USER="myuser"`
- `SNOWDUCK_SNOWFLAKE_CONNECTION_PASSWORD="mypassword"` (or use `SNOWFLAKE_PASSWORD` directly)
- `SNOWDUCK_SNOWFLAKE_CONNECTION_AUTHENTICATOR="externalbrowser"` (to use browser-based SSO)
- `SNOWDUCK_SNOWFLAKE_WAREHOUSE_DEFAULT_SIZE="XSMALL"`

The Snowflake connection factory also respects standard Snowflake environment variables (e.g., `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_AUTHENTICATOR`, etc.).

## Usage

Run the agent with a query name (without the `.sql` extension) that corresponds to a file in the `queries/` directory:

```bash
python .claude/src/snowduck/agent.py q1
```

The agent will:
1. Load configuration from `settings.yaml` and environment variables.
2. Detect machine specs (CPU, available memory).
3. Initialize a DuckDB in-memory connection with memory limit.
4. Create a Snowflake connection factory (secure, temporary env).
5. Initialize the query analyzer (needs both connections).
6. Load skill registry with hot-reload enabled.
7. Check dialect compatibility using the `dialect_check` skill.
8. Select engine (DuckDB or Snowflake) based on compatibility, cost estimation, and constraints.
9. Execute the query and print results.
10. Clean up connections and stop skill watcher.

## Adding New Skills

To add a new skill:

1. Create a Python file in `.claude/src/snowduck/skills/` (e.g., `my_skill.py`).
2. Implement a class that inherits from `Skill` (found in `.claude/src/snowduck/skills/base.py`).
3. Implement the `name` property (return a unique skill name).
4. Implement the `run(self, context: Dict[str, Any]) -> Dict[str, Any]` method.
5. The skill will be automatically discovered and loaded by the `SkillRegistry`.
6. Hot-reload is enabled: changing the skill file will reload it without restarting the agent.

### Skill Base Class

```python
from .base import Skill

class MySkill(Skill):
    @property
    def name(self) -> str:
        return "my_skill"

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # Your skill logic here
        return {"result": "success"}
```

## Architecture Overview

### Dependency Injection

The main agent (`agent.py`) receives its dependencies via direct instantiation but is designed for easy injection:
- `settings`: Application configuration.
- `SkillRegistry`: Manages skill discovery and hot-reload.
- `MachineUtils`: Provides CPU and memory info.
- `CostEstimator`: Estimates query execution cost.
- `EngineSelector`: Chooses between DuckDB and Snowflake.
- `SnowflakeConnectionFactory`: Creates Snowflake connections securely.
- `QueryHelpers`: Retrieves SQL and table stats.

### Hot-Reload Skills

The `SkillRegistry` uses `watchdog` to monitor the skills directory. When a skill file changes, it is automatically reloaded, allowing rapid iteration during development.

### MCP Boundary Safety

Snowflake connections are created via `SnowflakeConnectionFactory` which uses `contextlib.contextmanager` to temporarily set environment variables (e.g., `SNOWFLAKE_WAREHOUSE`) within a `with` block. This avoids mutating the global `os.environ` and ensures thread safety.

### Query Analysis

The agent uses `sqlglot` to parse SQL and detect Snowflake-specific constructs. The `dialect_check` skill returns compatibility issues and a recommended engine.

### Cost Estimation

The `CostEstimator` uses machine specs and (optionally) query statistics to estimate the cost of running a query on DuckDB vs. Snowflake. The `EngineSelector` combines this with dialect compatibility to make a final decision.

## Development

### Running Tests

*(Add test instructions as appropriate)*

### Linting

*(Add linting instructions as appropriate)*

## Dependencies

See `requirements.txt` for the full list. Key dependencies:
- `duckdb`: For in-memory analytical queries.
- `snowflake-connector-python`: For Snowflake connectivity.
- `sqlglot`: For SQL parsing and dialect translation.
- `dbt-core`: For potential dbt integration (if used).
- `streamlit`: For optional UI components.
- `pandas`: For data manipulation.
- `psutil`: For machine spec detection.
- `pydantic`: For configuration management.
- `pyyaml`: For YAML parsing.
- `watchdog`: For hot-reloading skills.

## License

*(Specify license if applicable)*

## Acknowledgments

*(Any acknowledgments)*