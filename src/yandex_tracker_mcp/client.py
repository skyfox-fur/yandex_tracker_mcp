"""HTTP layer: a shared httpx client and LLM-readable error handling."""

from __future__ import annotations

import contextlib
import mimetypes
import re
from pathlib import Path
from typing import Any, BinaryIO

import anyio
import httpx

from yandex_tracker_mcp import config
from yandex_tracker_mcp.files import UploadFile, create_unique, size_limit_message
from yandex_tracker_mcp.formatting import drop_none

ERROR_TEXT_LIMIT = 1000
MAX_REDIRECTS = 3
DOWNLOAD_TIMEOUT = 300  # seconds for a whole download, not per read

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


def _transport_error(method: str, path: str, error: httpx.TransportError, write: bool) -> RuntimeError:
    message = f"Tracker {method} {path}: {type(error).__name__} {error}".rstrip()
    if write and not isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout)):
        message += ". The request may have been applied; check before retrying"
    return RuntimeError(message)


async def send(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: Any = None,
    files: dict[str, Any] | None = None,
    write: bool = False,
) -> tuple[Any, httpx.Headers]:
    if write and config.READ_ONLY:
        raise RuntimeError("The server is in read-only mode (TRACKER_READ_ONLY)")
    try:
        resp = await get_client().request(method, path, params=drop_none(params or {}), json=body, files=files)
    except httpx.TransportError as e:
        raise _transport_error(method, path, e, write) from e

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


async def upload(path: str, file: UploadFile) -> dict[str, Any]:
    """Sends file contents as multipart field 'file' (the format of Tracker's upload endpoints)."""
    content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    result = await request("POST", path, files={"file": (file.name, file.data, content_type)}, write=True)
    if not isinstance(result, dict) or not result.get("id"):
        raise RuntimeError(f"Tracker POST {path}: upload of {file.name} returned no attachment id")
    return result


async def _open_stream(path: str) -> httpx.Response:
    """GETs path as a stream, following up to MAX_REDIRECTS https redirects by hand.

    File content may be served from storage on another host. Requests to any other host
    are sent without the Authorization and organization headers.
    """
    client = get_client()
    api_origin = _origin(client.base_url)
    # identity: the size limit is enforced on bytes as received, so a compressed body cannot expand past it
    request_ = client.build_request("GET", path, headers={"Accept-Encoding": "identity"})
    for _ in range(MAX_REDIRECTS + 1):
        resp = await client.send(request_, stream=True)
        if not resp.is_redirect:
            return resp
        await resp.aclose()
        target = resp.url.join(resp.headers.get("Location", ""))
        if target.scheme != "https":
            raise RuntimeError(f"Tracker GET {path}: refusing to follow a redirect to {target.scheme}://{target.host}")
        request_ = client.build_request("GET", target, headers={"Accept-Encoding": "identity"})
        if _origin(target) != api_origin:
            for header in ("Authorization", *config.get_config().headers):
                request_.headers.pop(header, None)
    raise RuntimeError(f"Tracker GET {path}: too many redirects")


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    return url.scheme, url.host, url.port


async def _stream_to_file(path: str, resp: httpx.Response, fh: BinaryIO, max_bytes: int) -> int:
    if not resp.is_success:
        await resp.aread()
        raise RuntimeError(_error_message("GET", path, resp))
    declared = resp.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise RuntimeError(f"Tracker GET {path}: file is {size_limit_message(max_bytes)}")
    written = 0
    async for chunk in resp.aiter_bytes():
        written += len(chunk)
        if written > max_bytes:
            raise RuntimeError(f"Tracker GET {path}: file is {size_limit_message(max_bytes)}")
        fh.write(chunk)
    return written


async def download(path: str, directory: Path, name: str, max_bytes: int) -> tuple[Path, int]:
    """Downloads into a new file in directory (never overwriting) and returns its path and size.

    The file is removed again if the download fails, so no partial files are left behind.
    """
    dest, fh = create_unique(directory, name)
    deadline = None
    try:
        with fh, anyio.fail_after(DOWNLOAD_TIMEOUT) as deadline:
            resp = await _open_stream(path)
            try:
                written = await _stream_to_file(path, resp, fh, max_bytes)
            finally:
                await resp.aclose()
    except BaseException as e:
        with contextlib.suppress(OSError):  # e.g. a virus scanner holding the file must not hide the real error
            dest.unlink(missing_ok=True)
        if deadline is not None and deadline.cancelled_caught:
            raise RuntimeError(f"Tracker GET {path}: download took longer than {DOWNLOAD_TIMEOUT} s") from e
        if isinstance(e, httpx.TransportError):
            raise _transport_error("GET", path, e, write=False) from e
        if isinstance(e, (httpx.HTTPError, OSError)):
            raise RuntimeError(f"Tracker GET {path}: {type(e).__name__} {e}") from e
        raise
    return dest, written
