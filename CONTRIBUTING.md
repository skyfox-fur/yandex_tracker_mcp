# Contributing

Thanks for your interest! Bug reports and pull requests are welcome.

## Issues

Use the issue templates. For bugs, include steps to reproduce, versions and the error output,
with tokens and organization IDs removed.

## Pull requests

1. Fork the repository and create a branch: `git checkout -b feature/short-description`.
2. Set up the environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -e ".[dev]"
   ```
3. Make your change, with tests.
4. Check that everything passes:
   ```bash
   python -m pytest
   ruff check . && ruff format --check .
   ```
5. Open a pull request describing what changed and why. CI runs the same checks.

## Adding a tool

Tools live in `src/yandex_tracker_mcp/server.py`.

- Read tools use `@mcp.tool(annotations=_READ)`.
- Write tools use `@_write_tool()`, or `@_write_tool(destructive=True)` when they overwrite data,
  and pass `write=True` to `request()`.
- The docstring is what the model sees: keep it short and precise.
- Pass every argument that goes into a URL path through `path_segment()`; `_issue_path()` does it for issue keys.
- Fetch lists with `request_list()` and wrap paginated ones with `paged()`.
- Return compact JSON via `to_json()`, without fields the model does not need.
- Add a test in `tests/test_tools.py` and a row to the tools table in `README.md`.

```python
@_write_tool()
async def add_something(issue_key: str, text: str) -> str:
    """One-line description for the model."""
    result = await request("POST", _issue_path(issue_key, "/something"), body={"text": text}, write=True)
    return to_json(result)
```

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
