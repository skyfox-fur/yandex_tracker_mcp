"""Local file safety: the upload policy and safe names for downloaded files."""

from __future__ import annotations

import fnmatch
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from yandex_tracker_mcp import config

MAX_NAME_BYTES = 120  # leaves room for the directory and " (n)" within Windows MAX_PATH and ext4's 255 bytes

_SEPARATORS = re.compile(r"[\\/]")
_UNSAFE_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CONIN$",
    "CONOUT$",
    *(f"{device}{n}" for device in ("COM", "LPT") for n in (*"123456789", "¹", "²", "³")),
}
# Extensions that Windows may execute or act on when the file is merely opened or browsed.
_RISKY_EXTENSIONS = {
    ".application", ".appref-ms", ".bat", ".cmd", ".com", ".cpl", ".exe", ".hta", ".js", ".jse",
    ".library-ms", ".lnk", ".msc", ".msi", ".pif", ".ps1", ".psm1", ".reg", ".scf", ".scr", ".sct",
    ".search-ms", ".settingcontent-ms", ".url", ".vbe", ".vbs", ".wsf", ".wsh",
}  # fmt: skip
# Typical secrets that may live in ordinary, non-hidden locations.
_SENSITIVE_NAMES = (
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx",
    "*.env", "credentials*", "*.tfstate", "*.tfstate.*", "kubeconfig", "known_hosts", "authorized_keys",
    "login data", "cookies", "ntuser.dat",
)  # fmt: skip
_WINDOWS_HIDDEN = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0) | getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0)


@dataclass(frozen=True)
class UploadFile:
    path: Path
    name: str
    data: bytes


def size_limit_message(max_bytes: int) -> str:
    return f"larger than the {max_bytes / 1024 / 1024:g} MB limit (TRACKER_MAX_FILE_MB)"


# ---------- Downloads ----------


def _truncate(text: str, max_bytes: int) -> str:
    return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def safe_filename(name: str) -> str:
    """Turns a name from Tracker into a plain file name that cannot leave its directory."""
    base = _SEPARATORS.split(name)[-1]
    base = _UNSAFE_CHARS.sub("_", base).strip().lstrip(".").rstrip(". ")
    if not base:
        return "attachment"
    if base.split(".")[0].rstrip(" ").upper() in _WINDOWS_RESERVED:
        base = f"_{base}"
    stem, suffix = os.path.splitext(base)
    if suffix.lower() in _RISKY_EXTENSIONS:
        stem, suffix = base, ".download"
    suffix = _truncate(suffix, 20)
    stem = _truncate(stem, MAX_NAME_BYTES - len(suffix.encode("utf-8"))).rstrip(". ")
    return f"{stem or 'attachment'}{suffix}"


def prepare_download_dir(directory: Path) -> Path:
    """Creates the directory private to the current user (0700) and refuses symlinked or foreign ones.

    directory must not be pre-resolved: the symlink check looks at the path as configured.
    """
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise RuntimeError(f"Download directory {directory} is not a plain directory")
    if hasattr(os, "getuid"):
        if info.st_uid != os.getuid():
            raise RuntimeError(f"Download directory {directory} belongs to another user")
        if info.st_mode & 0o077:
            directory.chmod(0o700)
    return directory


def create_unique(directory: Path, name: str) -> tuple[Path, BinaryIO]:
    """Atomically creates a new file 'name' (or 'name (n).ext') in directory; never overwrites."""
    stem, suffix = os.path.splitext(name)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    for n in range(1000):
        candidate = directory / (name if n == 0 else f"{stem} ({n}){suffix}")
        try:
            fd = os.open(candidate, flags, 0o600)
        except FileExistsError:
            continue
        return candidate, os.fdopen(fd, "wb")
    raise RuntimeError(f"Too many files named {name} in {directory}")


# ---------- Uploads ----------


def _upload_error(path: str, reason: str) -> ValueError:
    return ValueError(f"Cannot upload {path}: {reason}")


def _check_components(real: Path, root: Path, path: str) -> None:
    current = root
    for part in real.relative_to(root).parts:
        current = current / part
        if part.startswith("."):
            raise _upload_error(path, "hidden files and directories cannot be uploaded")
        if _WINDOWS_HIDDEN and getattr(current.stat(), "st_file_attributes", 0) & _WINDOWS_HIDDEN:
            raise _upload_error(path, "hidden or system files cannot be uploaded")


def read_upload(path: str) -> UploadFile:
    """Reads a local file the model wants to upload, enforcing the upload policy.

    Allowed: regular files inside cfg.upload_roots (the working directory and the download
    directory unless they are too broad, plus TRACKER_UPLOAD_DIRS), with no hidden path
    component, not a typical secret file, within the size limit. Symlinks are resolved before
    the checks, and the file is read right away and verified to be the file that was checked.
    """
    cfg = config.get_config()
    requested = Path(os.path.abspath(Path(path).expanduser()))
    if os.name == "nt" and ":" in os.path.splitdrive(str(requested))[1]:
        raise _upload_error(path, "alternate data streams are not allowed")
    # Check the requested location before touching the file system, so the tool
    # cannot be used to probe whether files exist outside the allowed directories.
    if not any(requested.is_relative_to(r) for r in cfg.upload_roots) and not any(
        requested.resolve().is_relative_to(r) for r in cfg.upload_roots
    ):
        raise _upload_error(path, "outside the allowed directories (see TRACKER_UPLOAD_DIRS)")

    try:
        real = requested.resolve(strict=True)
    except OSError:
        raise _upload_error(path, "file not found") from None
    root = next((r for r in cfg.upload_roots if real.is_relative_to(r)), None)
    if root is None:
        raise _upload_error(path, "outside the allowed directories (see TRACKER_UPLOAD_DIRS)")
    checked = real.stat()  # identity of the file the checks below are about
    if not stat.S_ISREG(checked.st_mode):
        raise _upload_error(path, "not a file")
    _check_components(real, root, path)
    if any(fnmatch.fnmatch(real.name.lower(), pattern) for pattern in _SENSITIVE_NAMES):
        raise _upload_error(path, "looks like a secret (keys, certificates, credentials) and is never uploaded")
    if _is_env_file(real):
        raise _upload_error(path, "this is the server's TRACKER_ENV_FILE")

    data = _read_checked(real, checked, cfg.max_file_bytes + 1, path)
    if len(data) > cfg.max_file_bytes:
        raise _upload_error(path, size_limit_message(cfg.max_file_bytes))
    return UploadFile(path=real, name=real.name, data=data)


def _is_env_file(real: Path) -> bool:
    env_file = os.environ.get("TRACKER_ENV_FILE")
    try:
        return bool(env_file) and real.samefile(env_file)
    except OSError:
        return False


def _read_checked(real: Path, checked: os.stat_result, limit: int, path: str) -> bytes:
    """Reads up to limit bytes, failing if real is no longer the file that was checked.

    Guards against the file, or a directory on its path, being swapped (e.g. for a symlink)
    between the checks and the read. O_NOFOLLOW/O_NONBLOCK exist on POSIX only.
    """
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(real, flags)
    except OSError:
        raise _upload_error(path, "the file cannot be opened") from None
    with os.fdopen(fd, "rb") as fh:
        opened = os.fstat(fh.fileno())
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(opened, checked):
            raise _upload_error(path, "the file changed while it was being checked")
        data = fh.read(limit)
    try:
        unchanged = real.resolve(strict=True) == real
    except OSError:
        unchanged = False
    if not unchanged:
        raise _upload_error(path, "the file changed while it was being checked")
    return data
