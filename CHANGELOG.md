# Changelog

## 0.5.0

- `edit_comment` and `delete_comment` tools (destructive; hidden in read-only mode).

## 0.4.0

- Attachments: `list_attachments`, `download_attachment` and `attach_file` tools; `add_comment` accepts `file_paths`.
- New settings: `TRACKER_DOWNLOAD_DIR`, `TRACKER_UPLOAD_DIRS` and `TRACKER_MAX_FILE_MB`.
- Uploads are restricted to allowed directories, and hidden files are never uploaded. Downloads use sanitized,
  non-overwriting file names.

## 0.3.0

- Project translated to English: code, tool descriptions, error messages and docs.
- Package moved to `src/yandex_tracker_mcp/` and split into `config`, `client`, `formatting` and `server` modules.
  Run it with `yandex-tracker-mcp` or `python -m yandex_tracker_mcp`.
- `.env` is now loaded only from `TRACKER_ENV_FILE`.
- Removed `server.py`, `requirements.txt` and the setup scripts. Dependencies are declared in `pyproject.toml` only.

## 0.2.0

- Security hardening: URL path arguments are validated, the API URL must be https, and the `.env` lookup is restricted.
- Strict configuration validation at startup. An invalid `TRACKER_READ_ONLY` falls back to read-only.
- Write tools are hidden in read-only mode and carry MCP annotations.
- Pagination metadata (`total`, `has_more`) and cursor pagination for comments.
- Clear errors for HTTP failures, timeouts, redirects and non-JSON responses.
- Added a test suite, ruff, CI and Dependabot.

## 0.1.0

- Initial release: 12 read tools and 6 write tools for Yandex Tracker API v3.
