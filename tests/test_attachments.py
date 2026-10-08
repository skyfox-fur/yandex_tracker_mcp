import asyncio
import dataclasses
import functools
import json
import os
from pathlib import Path

import httpx
import pytest

from conftest import run_tool
from yandex_tracker_mcp import client, config, files
from yandex_tracker_mcp.server import add_comment, attach_file, download_attachment, list_attachments

ATTACHMENTS = [
    {
        "id": "101",
        "name": "spec.pdf",
        "size": 2048,
        "mimetype": "application/pdf",
        "createdBy": {"display": "Jane"},
        "createdAt": "2026-10-08T10:00:00.000+0000",
    },
    {
        "id": "102",
        "name": "../../evil.txt",
        "size": 5,
        "mimetype": "text/plain",
        "createdBy": {"display": "Bob"},
        "createdAt": "2026-10-08T11:00:00.000+0000",
        "commentId": "555",
    },
]


@pytest.fixture
def workspace(tmp_path, monkeypatch, clean_config):
    """Isolated working directory (allowed for uploads) and download directory."""
    work, downloads = tmp_path / "work", tmp_path / "downloads"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("TRACKER_DOWNLOAD_DIR", str(downloads))
    monkeypatch.delenv("TRACKER_UPLOAD_DIRS", raising=False)
    monkeypatch.delenv("TRACKER_MAX_FILE_MB", raising=False)
    config.get_config.cache_clear()
    return work, downloads


def limit_size(monkeypatch, max_bytes: int) -> None:
    limited = dataclasses.replace(config.get_config(), max_file_bytes=max_bytes)
    monkeypatch.setattr(config, "get_config", functools.cache(lambda: limited))


# ---------- Configuration ----------


def test_file_settings_defaults(clean_config, monkeypatch):
    for name in ("TRACKER_DOWNLOAD_DIR", "TRACKER_UPLOAD_DIRS", "TRACKER_MAX_FILE_MB"):
        monkeypatch.delenv(name, raising=False)
    cfg = config.get_config()
    assert cfg.download_dir.name.startswith("yandex-tracker-mcp-")
    assert cfg.max_file_bytes == 50 * 1024 * 1024
    assert Path.cwd().resolve() in cfg.upload_roots
    assert cfg.download_dir.resolve() in cfg.upload_roots


def test_upload_dirs_from_env(clean_config, monkeypatch, tmp_path):
    extra_a, extra_b = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv("TRACKER_UPLOAD_DIRS", f"{extra_a}{os.pathsep}{extra_b}")
    roots = config.get_config().upload_roots
    assert extra_a.resolve() in roots
    assert extra_b.resolve() in roots


@pytest.mark.parametrize("value", ["0", "-1", "big"])
def test_invalid_max_file_mb(clean_config, monkeypatch, value):
    monkeypatch.setenv("TRACKER_MAX_FILE_MB", value)
    with pytest.raises(config.ConfigError, match="TRACKER_MAX_FILE_MB"):
        config.get_config()


# ---------- File name and path safety ----------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("report.pdf", "report.pdf"),
        ("../../evil.txt", "evil.txt"),
        ("..\\..\\evil.txt", "evil.txt"),
        ("/etc/passwd", "passwd"),
        ("a<b>c:d|e?.txt", "a_b_c_d_e_.txt"),
        (".bashrc", "bashrc"),
        ("", "attachment"),
        ("..", "attachment"),
        ("CON", "_CON"),
        ("CON .txt", "_CON.txt"),
        ("run.bat", "run.bat.download"),
        ("invite.LNK", "invite.LNK.download"),
    ],
)
def test_safe_filename(name, expected):
    assert files.safe_filename(name) == expected


@pytest.mark.parametrize("stem", ["x" * 500, "я" * 300])
def test_safe_filename_truncates_by_bytes_and_keeps_extension(stem):
    name = files.safe_filename(stem + ".tar.gz")
    assert len(name.encode("utf-8")) <= files.MAX_NAME_BYTES
    assert name.endswith(".gz")


def test_create_unique_does_not_overwrite(tmp_path):
    (tmp_path / "a.txt").write_text("1")
    (tmp_path / "a (1).txt").write_text("2")
    path, fh = files.create_unique(tmp_path, "a.txt")
    with fh:
        fh.write(b"3")
    assert path == tmp_path / "a (2).txt"
    assert (tmp_path / "a.txt").read_text() == "1"
    assert path.read_bytes() == b"3"


def test_upload_from_working_directory(workspace):
    work, _ = workspace
    (work / "doc.txt").write_text("hello")
    upload = files.read_upload("doc.txt")
    assert upload.path == (work / "doc.txt").resolve()
    assert upload.name == "doc.txt"
    assert upload.data == b"hello"


def test_upload_outside_allowed_dirs_rejected(workspace, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("x")
    with pytest.raises(ValueError, match="outside the allowed directories"):
        files.read_upload(str(outside))


@pytest.mark.parametrize("relative", [".env", ".ssh/id_rsa", "sub/.git/config"])
def test_hidden_files_rejected(workspace, relative):
    work, _ = workspace
    target = work / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("secret")
    with pytest.raises(ValueError, match="hidden"):
        files.read_upload(relative)


def test_symlink_escape_rejected(workspace, tmp_path):
    work, _ = workspace
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    try:
        (work / "link.txt").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available")
    with pytest.raises(ValueError, match="outside the allowed directories"):
        files.read_upload("link.txt")


def test_missing_and_directory_rejected(workspace):
    work, _ = workspace
    (work / "dir").mkdir()
    with pytest.raises(ValueError, match="not found"):
        files.read_upload("nope.txt")
    with pytest.raises(ValueError, match="not a file"):
        files.read_upload("dir")


def test_upload_size_limit(workspace, monkeypatch):
    work, _ = workspace
    (work / "big.bin").write_bytes(b"x" * 11)
    limit_size(monkeypatch, 10)
    with pytest.raises(ValueError, match="larger than"):
        files.read_upload("big.bin")


# ---------- Tools ----------


def test_list_attachments(api):
    api.handler = lambda r: httpx.Response(200, json=ATTACHMENTS)
    result = run_tool(list_attachments("PROJ-1"))
    assert api.requests[0].url.path == "/v3/issues/PROJ-1/attachments"
    assert result[0] == {
        "id": "101",
        "name": "spec.pdf",
        "size": 2048,
        "mimetype": "application/pdf",
        "createdBy": "Jane",
        "createdAt": "2026-10-08T10:00:00.000+0000",
        "commentId": None,
    }


def test_list_attachments_of_comment(api):
    api.handler = lambda r: httpx.Response(200, json=ATTACHMENTS)
    result = run_tool(list_attachments("PROJ-1", comment_id="555"))
    assert [a["id"] for a in result] == ["102"]


def _download_handler(content: bytes):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json=ATTACHMENTS)
        return httpx.Response(200, content=content, headers={"Content-Type": "text/plain"})

    return handler


def test_download_attachment_sanitizes_name_and_stays_in_dir(api, workspace):
    _, downloads = workspace
    api.handler = _download_handler(b"hello")
    result = run_tool(download_attachment("PROJ-1", "102"))
    saved = Path(result["path"])
    assert saved.read_bytes() == b"hello"
    assert saved.parent == downloads / "PROJ-1"
    assert saved.name == "evil.txt"
    assert result["size"] == 5
    assert api.requests[1].url.raw_path == b"/v3/issues/PROJ-1/attachments/102/..%2F..%2Fevil.txt"


def test_download_does_not_overwrite(api, workspace):
    api.handler = _download_handler(b"hello")
    first = run_tool(download_attachment("PROJ-1", "102"))["path"]
    second = run_tool(download_attachment("PROJ-1", "102"))["path"]
    assert first != second
    assert Path(second).name == "evil (1).txt"


def test_download_unknown_attachment(api, workspace):
    api.handler = _download_handler(b"")
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(download_attachment("PROJ-1", "999"))


def test_download_too_large_leaves_no_file(api, workspace, monkeypatch):
    _, downloads = workspace
    limit_size(monkeypatch, 3)
    api.handler = _download_handler(b"hello")
    with pytest.raises(RuntimeError, match="larger than"):
        asyncio.run(download_attachment("PROJ-1", "102"))
    assert not any(downloads.rglob("*.*"))


def test_download_follows_redirect(api, workspace):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json=ATTACHMENTS)
        if request.url.host == "storage.example":
            assert "Authorization" not in request.headers
            assert "X-Org-ID" not in request.headers
            return httpx.Response(200, content=b"from-storage")
        return httpx.Response(302, headers={"Location": "https://storage.example/blob"})

    api.handler = handler
    result = run_tool(download_attachment("PROJ-1", "101"))
    assert Path(result["path"]).read_bytes() == b"from-storage"


def test_attach_file(api, workspace):
    work, _ = workspace
    (work / "notes.txt").write_text("content")
    api.handler = lambda r: httpx.Response(201, json={"id": "201", "name": "notes.txt", "size": 7})
    result = run_tool(attach_file("PROJ-1", "notes.txt"))
    request = api.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/v3/issues/PROJ-1/attachments"
    assert request.headers["Content-Type"].startswith("multipart/form-data")
    assert b'name="file"; filename="notes.txt"' in request.content
    assert b"content" in request.content
    assert result == {
        "id": "201",
        "name": "notes.txt",
        "size": 7,
        "uploaded_from": [str((work / "notes.txt").resolve())],
    }


def test_attach_file_rejected_before_request(api, workspace):
    work, _ = workspace
    (work / ".env").write_text("TRACKER_TOKEN=secret")
    with pytest.raises(ValueError, match="hidden"):
        asyncio.run(attach_file("PROJ-1", ".env"))
    assert api.requests == []


def test_comment_with_files(api, workspace):
    work, _ = workspace
    (work / "a.txt").write_text("a")
    (work / "b.txt").write_text("b")
    uploaded = iter(["t1", "t2"])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/attachments":
            return httpx.Response(201, json={"id": next(uploaded)})
        return httpx.Response(201, json={"id": 9, "createdAt": "now"})

    api.handler = handler
    result = run_tool(add_comment("PROJ-1", "see files", file_paths=["a.txt", "b.txt"]))
    paths = [r.url.path for r in api.requests]
    assert paths == ["/v3/attachments", "/v3/attachments", "/v3/issues/PROJ-1/comments"]
    assert json.loads(api.requests[2].content) == {"text": "see files", "attachmentIds": ["t1", "t2"]}
    assert result["id"] == 9
    assert [Path(p).name for p in result["uploaded_from"]] == ["a.txt", "b.txt"]


def test_comment_files_validated_before_any_upload(api, workspace):
    work, _ = workspace
    (work / "a.txt").write_text("a")
    with pytest.raises(ValueError, match="not found"):
        asyncio.run(add_comment("PROJ-1", "x", file_paths=["a.txt", "missing.txt"]))
    assert api.requests == []


# ---------- Hardening ----------


def test_broad_working_directory_is_not_an_upload_root(clean_config, monkeypatch):
    monkeypatch.chdir(Path.home())
    config.get_config.cache_clear()
    assert Path.home().resolve() not in config.get_config().upload_roots


def test_broad_upload_dir_is_a_config_error(clean_config, monkeypatch):
    monkeypatch.setenv("TRACKER_UPLOAD_DIRS", str(Path.home()))
    with pytest.raises(config.ConfigError, match="too broad"):
        config.get_config()


@pytest.mark.parametrize("name", ["id_rsa", "server.pem", "prod.env", "credentials.json", "state.tfstate"])
def test_secret_looking_files_rejected(workspace, name):
    work, _ = workspace
    (work / name).write_text("secret")
    with pytest.raises(ValueError, match="looks like a secret"):
        files.read_upload(name)


def test_tracker_env_file_rejected(workspace, monkeypatch):
    work, _ = workspace
    (work / "tracker.cfg").write_text("TRACKER_TOKEN=secret")
    monkeypatch.setenv("TRACKER_ENV_FILE", str(work / "tracker.cfg"))
    with pytest.raises(ValueError, match="TRACKER_ENV_FILE"):
        files.read_upload("tracker.cfg")


@pytest.mark.skipif(os.name != "nt", reason="NTFS alternate data streams")
def test_alternate_data_stream_rejected(workspace):
    with pytest.raises(ValueError, match="alternate data streams"):
        files.read_upload("notes.txt:hidden")


def test_outside_path_rejected_without_probing(workspace, tmp_path):
    with pytest.raises(ValueError, match="outside the allowed directories"):
        files.read_upload(str(tmp_path / "does-not-exist.txt"))


def test_download_streaming_cap_without_size_metadata(api, workspace, monkeypatch):
    _, downloads = workspace
    limit_size(monkeypatch, 3)
    meta = [{"id": "7", "name": "big.bin"}]  # no "size": only the streaming check can stop it

    def handler(request):
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json=meta)
        return httpx.Response(200, content=b"0123456789")

    api.handler = handler
    with pytest.raises(RuntimeError, match="larger than"):
        asyncio.run(download_attachment("PROJ-1", "7"))
    assert not any(p.is_file() for p in downloads.rglob("*"))


def test_download_failing_midway_leaves_no_file(api, workspace):
    _, downloads = workspace

    async def broken_body():
        yield b"part"
        raise httpx.ReadError("connection reset")

    def handler(request):
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json=ATTACHMENTS)
        return httpx.Response(200, content=broken_body())

    api.handler = handler
    with pytest.raises(RuntimeError, match="ReadError"):
        asyncio.run(download_attachment("PROJ-1", "101"))
    assert not any(p.is_file() for p in downloads.rglob("*"))


def test_download_refuses_non_https_redirect(api, workspace):
    def handler(request):
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json=ATTACHMENTS)
        return httpx.Response(302, headers={"Location": "http://storage.example/blob"})

    api.handler = handler
    with pytest.raises(RuntimeError, match="refusing to follow"):
        asyncio.run(download_attachment("PROJ-1", "101"))


def test_concurrent_downloads_get_distinct_files(api, workspace):
    api.handler = _download_handler(b"hello")

    async def both():
        return await asyncio.gather(download_attachment("PROJ-1", "101"), download_attachment("PROJ-1", "101"))

    paths = {json.loads(r)["path"] for r in asyncio.run(both())}
    assert len(paths) == 2


def test_dot_name_is_not_used_in_url(api, workspace):
    meta = [{"id": "8", "name": ".."}]

    def handler(request):
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json=meta)
        return httpx.Response(200, content=b"x")

    api.handler = handler
    run_tool(download_attachment("PROJ-1", "8"))
    assert api.requests[1].url.path == "/v3/issues/PROJ-1/attachments/8/attachment"


def test_comment_upload_without_id_fails_clearly(api, workspace):
    work, _ = workspace
    (work / "a.txt").write_text("a")
    api.handler = lambda r: httpx.Response(201)  # empty body: no attachment id
    with pytest.raises(RuntimeError, match="No comment was created"):
        asyncio.run(add_comment("PROJ-1", "x", file_paths=["a.txt"]))
    assert all(r.url.path == "/v3/attachments" for r in api.requests)


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX permissions")
def test_downloads_are_private(api, workspace):
    _, downloads = workspace
    api.handler = _download_handler(b"hello")
    saved = Path(run_tool(download_attachment("PROJ-1", "101"))["path"])
    assert saved.stat().st_mode & 0o777 == 0o600
    assert (downloads / "PROJ-1").stat().st_mode & 0o777 == 0o700


def test_download_timeout(api, workspace, monkeypatch):
    _, downloads = workspace
    monkeypatch.setattr(client, "DOWNLOAD_TIMEOUT", 0.05)

    async def slow_body():
        yield b"a"
        await asyncio.sleep(5)
        yield b"b"

    def handler(request):
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json=ATTACHMENTS)
        return httpx.Response(200, content=slow_body())

    api.handler = handler
    with pytest.raises(RuntimeError, match="longer than"):
        asyncio.run(download_attachment("PROJ-1", "101"))
    assert not any(p.is_file() for p in downloads.rglob("*"))


def test_download_requests_uncompressed_body(api, workspace):
    api.handler = _download_handler(b"hello")
    run_tool(download_attachment("PROJ-1", "101"))
    assert api.requests[1].headers["Accept-Encoding"] == "identity"


def test_redirect_to_same_host_other_port_drops_credentials(api, workspace):
    def handler(request):
        if request.url.path.endswith("/attachments"):
            return httpx.Response(200, json=ATTACHMENTS)
        if request.url.port == 8443:
            assert "Authorization" not in request.headers
            return httpx.Response(200, content=b"ok")
        return httpx.Response(302, headers={"Location": "https://api.tracker.yandex.net:8443/blob"})

    api.handler = handler
    assert Path(run_tool(download_attachment("PROJ-1", "101"))["path"]).read_bytes() == b"ok"
