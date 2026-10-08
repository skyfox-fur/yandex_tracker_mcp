# yandex-tracker-mcp

**Version:** 0.1.0 | **Port:** N/A (MCP service) | **Stack:** Python 3.10+, FastMCP, httpx, python-dotenv

## What

MCP server for Yandex Tracker API v3. Allows Claude and other MCP clients to read/write issues, search, add comments, transition statuses, create links, and log time.

## Quick Start

```bash
./setup.sh              # Linux/macOS (Windows: .\setup.ps1): venv + deps
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate      # Windows
python -c "import asyncio, server; print(len(asyncio.run(server.mcp.list_tools())))"  # 18 tools
```

## Commands

```bash
# Development
pip install -e .        # Install in editable mode (auto entry point)

# Testing
python -c "import asyncio, server; print(len(asyncio.run(server.mcp.list_tools())))"  # 18

# Docker (if added)
# N/A — this is a microservice, run with uvx or pip install

# Entry point
yandex-tracker-mcp      # Runs server:main() after pip install -e .
```

## Architecture

```
server.py               Main FastMCP server (single file)
├── _headers()          Build auth headers (OAuth or IAM)
├── _request()          Async HTTP wrapper (httpx)
├── _brief_issue()      Format issue for context efficiency
├── _writable()         Guard for write-only mode
│
├── Read tools (12):
│   whoami, get_issue, search_issues, count_issues,
│   get_comments, get_transitions, get_links, get_worklog,
│   list_queues, get_queue, list_users, list_fields
│
└── Write tools (6):
    create_issue, update_issue, add_comment,
    transition_issue, link_issues, add_worklog
```

All tools call Yandex Tracker API v3. Write tools check `TRACKER_READ_ONLY` env var.

## Key Files

- `server.py` — single-file FastMCP server with 18 tools
- `pyproject.toml` — package metadata + entry point `yandex-tracker-mcp = "server:main"`
- `.env.example` — all env var placeholders
- `requirements.txt` — mcp>=1.2,<2; httpx>=0.27; python-dotenv>=1.0

## Configuration

All config via environment variables or a `.env` file (loaded via python-dotenv). See `.env.example`:

| Variable | Required | Description |
|----------|----------|-------------|
| `TRACKER_TOKEN` | Yes | OAuth or IAM token |
| `TRACKER_ORG_ID` | One of | Yandex 360 org ID (numeric) |
| `TRACKER_CLOUD_ORG_ID` | One of | Yandex Cloud org ID |
| `TRACKER_AUTH_TYPE` | No | "oauth" (default) or "iam" |
| `TRACKER_READ_ONLY` | No | Set to "1" to disable writes |
| `TRACKER_API_URL` | No | Default: https://api.tracker.yandex.net/v3 |

## Adding a Tool

1. Create async function in `server.py` with `@mcp.tool()` decorator
2. Add docstring (Russian)
3. Use `_request(method, path, ...)` for API calls
4. Use `_out(data)` to return JSON
5. For writes: call `_writable()` first
6. Update README.md with tool description

Example:

```python
@mcp.tool()
async def my_tool(issue_key: str) -> str:
    """Описание на русском."""
    _writable()  # only for write operations
    data = await _request("GET", f"/issues/{issue_key}")
    return _out(data)
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

Never commit `.env` with real tokens.
