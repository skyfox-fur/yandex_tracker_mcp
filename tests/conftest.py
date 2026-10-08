import asyncio
import json
import os
import subprocess
import sys
from types import SimpleNamespace

# The environment must be set before importing the package: read-only mode is resolved at import time.
os.environ.update(TRACKER_TOKEN="test-token", TRACKER_ORG_ID="42")
for name in ("TRACKER_CLOUD_ORG_ID", "TRACKER_AUTH_TYPE", "TRACKER_READ_ONLY", "TRACKER_API_URL", "TRACKER_ENV_FILE"):
    os.environ.pop(name, None)

import httpx  # noqa: E402
import pytest  # noqa: E402

from yandex_tracker_mcp import client, config  # noqa: E402


@pytest.fixture
def api(monkeypatch):
    """Replaces the HTTP client with a mock; tests set the response via api.handler."""
    state = SimpleNamespace(requests=[], handler=lambda request: httpx.Response(200, json={}))

    def transport(request: httpx.Request) -> httpx.Response:
        state.requests.append(request)
        return state.handler(request)

    cfg = config.get_config()
    mock_client = httpx.AsyncClient(base_url=cfg.api_url, headers=cfg.headers, transport=httpx.MockTransport(transport))
    monkeypatch.setattr(client, "_client", mock_client)
    return state


@pytest.fixture
def clean_config(monkeypatch):
    config.get_config.cache_clear()
    yield monkeypatch
    config.get_config.cache_clear()


def run_tool(coro):
    """Runs a tool coroutine and decodes its JSON result."""
    return json.loads(asyncio.run(coro))


def run_python(code: str, cwd=None, **env: str | None) -> subprocess.CompletedProcess[str]:
    """Runs code in a fresh interpreter, to test import-time behavior. env=None unsets a variable."""
    merged = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        env={k: v for k, v in merged.items() if v is not None},
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
