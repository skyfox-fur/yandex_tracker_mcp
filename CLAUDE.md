# yandex-tracker-mcp

MCP server for Yandex Tracker API v3 (Python 3.10+, FastMCP from `mcp` 1.x, httpx, python-dotenv).
Lets Claude and other MCP clients read/write issues, search, comment, transition, link, and log time.

## Commands

```bash
pip install -e ".[dev]"          # editable install + pytest, ruff
python -m pytest                 # tests use httpx.MockTransport, no real API calls
ruff check . && ruff format --check .
yandex-tracker-mcp               # entry point -> yandex_tracker_mcp:main
python server.py                 # legacy launcher, same thing
```

## Layout

- `yandex_tracker_mcp.py` — the whole server (single module)
- `server.py` — thin shim kept so existing `claude mcp add ... server.py` setups keep working
- `tests/` — `conftest.py` sets env **before** import (read-only mode is decided at import time)

## Architecture (yandex_tracker_mcp.py)

- `get_config()` — cached, validated `Config` (token, auth scheme, org header, https API URL).
  Raises `ConfigError`; `main()` reports it to stderr and exits 1 (stdout is the MCP transport).
- `READ_ONLY` — parsed at import; invalid value ⇒ read-only + startup error. Write tools are
  registered via `@_write_tool()` and are **not registered** in read-only mode; `_send(write=True)`
  re-checks as defense in depth.
- `_send()` / `_request()` / `_request_list()` — one shared `httpx.AsyncClient`; non-2xx, transport
  errors, non-JSON and wrong shapes become `RuntimeError` with a short, LLM-readable message.
- `_segment()` — validates every value interpolated into a URL path (blocks `../`, `?`, `#`).
- `_paged()` — wraps list results with `page/per_page/total/total_pages/has_more` from `X-Total-*` headers.
- `.env` is loaded only from next to the module or `TRACKER_ENV_FILE` — never from CWD.

## Adding a tool

```python
@mcp.tool(annotations=_READ)  # read tool
async def get_something(issue_key: str) -> str:
    """Описание на русском (его видит модель)."""
    data = await _request("GET", f"/issues/{_segment(issue_key, 'ключ задачи')}/something")
    return _out(data)


@_write_tool()  # write tool; destructive=True if it overwrites data
async def do_something(issue_key: str) -> str:
    """..."""
    return _out(await _request("POST", f"/issues/{_segment(issue_key, 'ключ задачи')}/x", body={}, write=True))
```

Add a test in `tests/test_server.py` and a row in README. Never commit `.env` or real tokens.
