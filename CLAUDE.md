# yandex-tracker-mcp

MCP server for Yandex Tracker API v3 (Python 3.10+, FastMCP from `mcp` 1.x, httpx, python-dotenv).

## Commands

```bash
pip install -e ".[dev]"                # editable install + pytest, ruff
python -m pytest                       # HTTP is mocked with httpx.MockTransport
ruff check . && ruff format --check .
yandex-tracker-mcp                     # run the server (stdio); also: python -m yandex_tracker_mcp
```

## Layout

- `src/yandex_tracker_mcp/config.py`: env parsing and validation (`get_config()`, `READ_ONLY`, `STARTUP_ERROR`).
  `.env` is loaded only from `TRACKER_ENV_FILE`.
- `src/yandex_tracker_mcp/client.py`: shared `httpx.AsyncClient`, `send/request/request_list`,
  `path_segment()` validation, and LLM-readable `RuntimeError`s.
- `src/yandex_tracker_mcp/files.py`: upload policy (`read_upload`) and safe downloads
  (`safe_filename`, `create_unique`, `prepare_download_dir`). `client.upload()` and `client.download()` do the HTTP part.
- `src/yandex_tracker_mcp/formatting.py`: `to_json`, `brief_issue`, `paged`, and small helpers.
- `src/yandex_tracker_mcp/server.py`: the `mcp` instance, all tools, and `main()`.
- `tests/conftest.py`: sets env **before** importing the package, because read-only mode is resolved at import.
  Provides the `api` (mock HTTP) and `clean_config` fixtures.

## Conventions

- All code, comments, docstrings and messages are in English.
- Read tools: `@mcp.tool(annotations=_READ)`. Write tools: `@_write_tool()` + `write=True` in `request()`.
  Write tools are not registered when `READ_ONLY`.
- Every value interpolated into a URL path goes through `path_segment()` (`_issue_path()` for issue keys).
- Local files: upload only via `read_upload()`; write downloads only via `safe_filename()` + `create_unique()`.
- `main()` writes config errors to stderr only; stdout is the MCP transport.
- New tool → test in `tests/test_tools.py` + row in the README table. Never commit `.env` or tokens.
