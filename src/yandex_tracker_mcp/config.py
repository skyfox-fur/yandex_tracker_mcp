"""Configuration from environment variables.

Variables:
  TRACKER_TOKEN         OAuth token, or an IAM token with TRACKER_AUTH_TYPE=iam (required)
  TRACKER_AUTH_TYPE     "oauth" (default) or "iam"
  TRACKER_ORG_ID        Yandex 360 organization ID   (X-Org-ID header)
  TRACKER_CLOUD_ORG_ID  Yandex Cloud organization ID (X-Cloud-Org-ID header)
  TRACKER_READ_ONLY     1/true/yes/on: write tools are not registered
  TRACKER_API_URL       API base URL, https only (default https://api.tracker.yandex.net/v3)
  TRACKER_ENV_FILE      optional path to a .env file with the variables above

Exactly one of TRACKER_ORG_ID / TRACKER_CLOUD_ORG_ID must be set.
Process environment variables take precedence over the .env file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache
from urllib.parse import urlsplit

from dotenv import load_dotenv

DEFAULT_API_URL = "https://api.tracker.yandex.net/v3"

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

    return Config(token, _AUTH_SCHEMES[auth_type], org_header, api_url)


# Read-only mode decides which tools get registered, so it is resolved at import time.
# An unparseable value falls back to read-only; main() reports the error and exits.
try:
    READ_ONLY = parse_bool("TRACKER_READ_ONLY")
    STARTUP_ERROR: ConfigError | None = None
except ConfigError as exc:
    READ_ONLY = True
    STARTUP_ERROR = exc
