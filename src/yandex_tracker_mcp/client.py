"""HTTP layer: a shared httpx client and LLM-readable error handling."""

from __future__ import annotations

import re
from typing import Any

import httpx

from yandex_tracker_mcp import config
from yandex_tracker_mcp.formatting import drop_none

ERROR_TEXT_LIMIT = 1000

# Values interpolated into URL paths (issue/queue keys, transition IDs). No '/', '.', '?'
# or '#', so an argument cannot escape its resource and reach another API endpoint.
_PATH_SEGMENT = re.compile(r"[A-Za-z0-9_-]+")

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        cfg = config.get_config()
        _client = httpx.AsyncClient(
            base_url=cfg.api_url,
            headers=cfg.headers,
            timeout=httpx.Timeout(30, connect=10),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def path_segment(value: str, what: str) -> str:
    if not _PATH_SEGMENT.fullmatch(value):
        raise ValueError(f"Invalid {what}: {value!r}")
    return value


def _tracker_errors(resp: httpx.Response) -> str | None:
    """Extracts text from Tracker's {"errorMessages": [...], "errors": {...}} error format."""
    try:
        payload = resp.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    messages, errors = payload.get("errorMessages"), payload.get("errors")
    parts = [str(m) for m in messages] if isinstance(messages, list) else []
    if isinstance(errors, dict):
        parts += [f"{k}: {v}" for k, v in errors.items()]
    return "; ".join(parts) or None


def _error_message(method: str, path: str, resp: httpx.Response) -> str:
    detail = _tracker_errors(resp) or resp.text
    message = f"Tracker API {resp.status_code} {method} {path}: {detail[:ERROR_TEXT_LIMIT]}"
    if resp.is_redirect:
        message += f" (redirect to {resp.headers.get('Location')}; check TRACKER_API_URL)"
    elif resp.status_code in (401, 403):
        message += " (check TRACKER_TOKEN, TRACKER_AUTH_TYPE and the organization ID)"
    elif resp.status_code == 429 and (retry_after := resp.headers.get("Retry-After")):
        message += f" (retry in {retry_after} s)"
    return message


async def send(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: Any = None,
    write: bool = False,
) -> tuple[Any, httpx.Headers]:
    if write and config.READ_ONLY:
        raise RuntimeError("The server is in read-only mode (TRACKER_READ_ONLY)")
    try:
        resp = await get_client().request(method, path, params=drop_none(params or {}), json=body)
    except httpx.TransportError as e:
        message = f"Tracker {method} {path}: {type(e).__name__} {e}".rstrip()
        if write and not isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):
            message += ". The request may have been applied; check before retrying"
        raise RuntimeError(message) from e

    if not resp.is_success:
        raise RuntimeError(_error_message(method, path, resp))
    if not resp.content:
        return {"ok": True, "http_status": resp.status_code}, resp.headers
    try:
        return resp.json(), resp.headers
    except ValueError as e:
        content_type = resp.headers.get("Content-Type")
        raise RuntimeError(f"Tracker {method} {path}: non-JSON response ({content_type}): {resp.text[:300]}") from e


async def request(method: str, path: str, **kwargs: Any) -> Any:
    data, _ = await send(method, path, **kwargs)
    return data


async def request_list(method: str, path: str, **kwargs: Any) -> tuple[list[Any], httpx.Headers]:
    data, headers = await send(method, path, **kwargs)
    if not isinstance(data, list):
        raise RuntimeError(f"Tracker {method} {path}: expected a list, got {type(data).__name__}")
    return data, headers
