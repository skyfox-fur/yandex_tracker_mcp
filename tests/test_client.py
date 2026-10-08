import asyncio

import httpx
import pytest

from conftest import run_tool
from yandex_tracker_mcp import client, config
from yandex_tracker_mcp.server import add_comment, add_worklog, get_issue, list_fields, whoami


def test_write_guard(api, monkeypatch):
    monkeypatch.setattr(config, "READ_ONLY", True)
    with pytest.raises(RuntimeError, match="read-only"):
        asyncio.run(client.request("POST", "/issues/", body={}, write=True))
    assert api.requests == []


@pytest.mark.parametrize("key", ["../../users", "PROJ-1/../x", "PROJ-1?a=b", "PROJ-1#x", "a.b", ""])
def test_path_traversal_rejected(api, key):
    with pytest.raises(ValueError, match="Invalid issue key"):
        asyncio.run(get_issue(key))
    assert api.requests == []


def test_auth_headers_sent(api):
    asyncio.run(whoami())
    request = api.requests[0]
    assert str(request.url) == "https://api.tracker.yandex.net/v3/myself"
    assert request.headers["Authorization"] == "OAuth test-token"
    assert request.headers["X-Org-ID"] == "42"


def test_tracker_error_messages(api):
    api.handler = lambda r: httpx.Response(404, json={"errorMessages": ["Issue does not exist."], "errors": {}})
    with pytest.raises(RuntimeError, match=r"404 GET /issues/PROJ-9: Issue does not exist\.$"):
        asyncio.run(get_issue("PROJ-9"))


def test_auth_hint_and_truncation(api):
    api.handler = lambda r: httpx.Response(401, text="x" * 5000)
    with pytest.raises(RuntimeError) as e:
        asyncio.run(whoami())
    assert "TRACKER_TOKEN" in str(e.value)
    assert len(str(e.value)) < client.ERROR_TEXT_LIMIT + 200


@pytest.mark.parametrize(
    "payload",
    [
        {"errorMessages": None, "errors": None},
        {"errorMessages": "string", "errors": ["list"]},
        ["array"],
        {},
    ],
)
def test_odd_error_payloads_fall_back_to_body(api, payload):
    api.handler = lambda r: httpx.Response(400, json=payload)
    with pytest.raises(RuntimeError, match=r"^Tracker API 400 GET /myself: "):
        asyncio.run(whoami())


def test_redirect_is_error(api):
    api.handler = lambda r: httpx.Response(302, headers={"Location": "https://elsewhere"})
    with pytest.raises(RuntimeError, match="redirect"):
        asyncio.run(whoami())


def test_non_json_body(api):
    api.handler = lambda r: httpx.Response(200, text="<html>", headers={"Content-Type": "text/html"})
    with pytest.raises(RuntimeError, match="non-JSON"):
        asyncio.run(whoami())


def test_write_timeout_warns_about_unknown_result(api):
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    api.handler = handler
    with pytest.raises(RuntimeError, match="may have been applied"):
        asyncio.run(add_comment("PROJ-1", "hi"))


def test_connect_error_on_write_has_no_ambiguity_warning(api):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    api.handler = handler
    with pytest.raises(RuntimeError) as e:
        asyncio.run(add_comment("PROJ-1", "hi"))
    assert "ConnectError" in str(e.value)
    assert "may have been applied" not in str(e.value)


def test_empty_body_is_ok(api):
    api.handler = lambda r: httpx.Response(204)
    assert run_tool(add_worklog("PROJ-1", "PT1H")) == {"ok": True, "http_status": 204}


def test_unexpected_shape(api):
    api.handler = lambda r: httpx.Response(200, json={"not": "a list"})
    with pytest.raises(RuntimeError, match="expected a list"):
        asyncio.run(list_fields())
