"""Configuration from environment variables.

Variables:
  TRACKER_TOKEN         OAuth token, or an IAM token with TRACKER_AUTH_TYPE=iam (required)
  TRACKER_AUTH_TYPE     "oauth" (default) or "iam"
  TRACKER_ORG_ID        Yandex 360 organization ID   (X-Org-ID header)
  TRACKER_CLOUD_ORG_ID  Yandex Cloud organization ID (X-Cloud-Org-ID header)
  TRACKER_READ_ONLY     1/true/yes/on: write tools are not registered
  TRACKER_API_URL       API base URL, https only (default https://api.tracker.yandex.net/v3)
  TRACKER_DOWNLOAD_DIR  where download_attachment saves files (default <temp>/yandex-tracker-mcp)
  TRACKER_UPLOAD_DIRS   extra directories files may be uploaded from (os.pathsep-separated);
                        the working directory and the download directory are always allowed
  TRACKER_MAX_FILE_MB   size limit for downloads and uploads, MB (default 50)
  TRACKER_ENV_FILE      optional path to a .env file with the variables above

Exactly one of TRACKER_ORG_ID / TRACKER_CLOUD_ORG_ID must be set.
Process environment variables take precedence over the .env file.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

DEFAULT_API_URL = "https://api.tracker.yandex.net/v3"
DEFAULT_MAX_FILE_MB = 50

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}
_AUTH_SCHEMES = {"oauth": "OAuth", "iam": "Bearer"}

# A .env file is read only when explicitly configured: an implicit lookup in the
# working directory would let a foreign .env redirect the token to another host.
if env_file := os.environ.get("TRACKER_ENV_FILE"):
    load_dotenv(env_file)


class ConfigError(RuntimeError):
    """Invalid or missing environment configuration."""


@dataclass(frozen=True)
class Config:
    token: str
    auth_scheme: str
    org_header: tuple[str, str]
    api_url: str
    download_dir: Path
    upload_roots: tuple[Path, ...]
    max_file_bytes: int

    @property
    def headers(self) -> dict[str, str]:
        name, value = self.org_header
        return {"Authorization": f"{self.auth_scheme} {self.token}", name: value}


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def parse_bool(name: str) -> bool:
    value = _env(name).lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"{name}={value!r}: expected 1/0, true/false, yes/no or on/off")


@cache
def get_config() -> Config:
    token = _env("TRACKER_TOKEN")
    if not token:
        raise ConfigError("TRACKER_TOKEN is not set")

    auth_type = _env("TRACKER_AUTH_TYPE").lower() or "oauth"
    if auth_type not in _AUTH_SCHEMES:
        raise ConfigError(f"TRACKER_AUTH_TYPE={auth_type!r}: expected oauth or iam")

    org_id, cloud_org_id = _env("TRACKER_ORG_ID"), _env("TRACKER_CLOUD_ORG_ID")
    if org_id and cloud_org_id:
        raise ConfigError("Set only one of TRACKER_ORG_ID / TRACKER_CLOUD_ORG_ID")
    if not (org_id or cloud_org_id):
        raise ConfigError("Set TRACKER_ORG_ID or TRACKER_CLOUD_ORG_ID")
    org_header = ("X-Org-ID", org_id) if org_id else ("X-Cloud-Org-ID", cloud_org_id)

    api_url = (_env("TRACKER_API_URL") or DEFAULT_API_URL).rstrip("/")
    parts = urlsplit(api_url)
    if parts.scheme != "https" or not parts.netloc:
        raise ConfigError(f"TRACKER_API_URL={api_url!r}: an https URL is required")

    # Kept unresolved, so prepare_download_dir() can detect a symlink planted in its place.
    download_dir = Path(_env("TRACKER_DOWNLOAD_DIR") or _default_download_dir()).expanduser().absolute()

    return Config(
        token=token,
        auth_scheme=_AUTH_SCHEMES[auth_type],
        org_header=org_header,
        api_url=api_url,
        download_dir=download_dir,
        upload_roots=_upload_roots(download_dir.resolve()),
        max_file_bytes=_parse_max_file_mb() * 1024 * 1024,
    )


def _default_download_dir() -> Path:
    # Per-user name, so users of a shared /tmp do not share (or pre-create) the directory.
    user = os.getuid() if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
    return Path(tempfile.gettempdir()) / f"yandex-tracker-mcp-{user}"


def is_broad_directory(path: Path) -> bool:
    """A filesystem root, the home directory or one of its ancestors: too broad to upload files from."""
    path = path.resolve()
    return path == path.parent or Path.home().resolve().is_relative_to(path)


def _upload_roots(download_dir: Path) -> tuple[Path, ...]:
    # The working directory is chosen by the MCP client and may be "/" or the home directory;
    # it is allowed only when it is narrower than that. Explicit directories must be narrow too.
    roots = [p for p in (Path.cwd().resolve(), download_dir) if not is_broad_directory(p)]
    for raw in _env("TRACKER_UPLOAD_DIRS").split(os.pathsep):
        if not raw.strip():
            continue
        directory = Path(raw.strip()).expanduser().resolve()
        if is_broad_directory(directory):
            raise ConfigError(f"TRACKER_UPLOAD_DIRS: {directory} is too broad (a drive root or the home directory)")
        roots.append(directory)
    return tuple(roots)


def _parse_max_file_mb() -> int:
    value = _env("TRACKER_MAX_FILE_MB") or str(DEFAULT_MAX_FILE_MB)
    try:
        megabytes = int(value)
    except ValueError:
        megabytes = 0
    if megabytes <= 0:
        raise ConfigError(f"TRACKER_MAX_FILE_MB={value!r}: expected a positive integer")
    return megabytes


# Read-only mode decides which tools get registered, so it is resolved at import time.
# An unparseable value falls back to read-only; main() reports the error and exits.
try:
    READ_ONLY = parse_bool("TRACKER_READ_ONLY")
    STARTUP_ERROR: ConfigError | None = None
except ConfigError as exc:
    READ_ONLY = True
    STARTUP_ERROR = exc
