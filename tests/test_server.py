import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import yandex_tracker_mcp as ytm

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def api(monkeypatch):
    """Подменяет HTTP-клиент; handler задаётся в тесте через api.handler."""

    state = SimpleNamespace(requests=[], handler=lambda request: httpx.Response(200, json={}))

    def transport(request: httpx.Request) -> httpx.Response:
        state.requests.append(request)
        return state.handler(request)

    config = ytm.get_config()
    client = httpx.AsyncClient(
        base_url=config.api_url, headers=config.headers, transport=httpx.MockTransport(transport)
    )
    monkeypatch.setattr(ytm, "_client", client)
    return state


def run(coro):
    return json.loads(asyncio.run(coro))


# ---------- Конфигурация ----------


@pytest.fixture
def clean_config(monkeypatch):
    ytm.get_config.cache_clear()
    yield monkeypatch
    ytm.get_config.cache_clear()


def test_config_headers(clean_config):
    assert ytm.get_config().headers == {"Authorization": "OAuth test-token", "X-Org-ID": "42"}


def test_config_iam_and_cloud_org(clean_config):
    clean_config.setenv("TRACKER_AUTH_TYPE", " IAM ")
    clean_config.delenv("TRACKER_ORG_ID")
    clean_config.setenv("TRACKER_CLOUD_ORG_ID", "bpf123")
    assert ytm.get_config().headers == {"Authorization": "Bearer test-token", "X-Cloud-Org-ID": "bpf123"}


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"TRACKER_TOKEN": ""}, "TRACKER_TOKEN"),
        ({"TRACKER_AUTH_TYPE": "bearer"}, "TRACKER_AUTH_TYPE"),
        ({"TRACKER_CLOUD_ORG_ID": "bpf123"}, "только один"),
        ({"TRACKER_ORG_ID": " "}, "Задайте TRACKER_ORG_ID"),
        ({"TRACKER_API_URL": "http://evil.example"}, "https"),
    ],
)
def test_config_errors(clean_config, env, message):
    for name, value in env.items():
        clean_config.setenv(name, value)
    with pytest.raises(ytm.ConfigError, match=message):
        ytm.get_config()


@pytest.mark.parametrize("value", ["1", "true", "Yes", " on "])
def test_parse_bool_true(monkeypatch, value):
    monkeypatch.setenv("TRACKER_READ_ONLY", value)
    assert ytm._parse_bool("TRACKER_READ_ONLY") is True


def test_parse_bool_typo_is_error(monkeypatch):
    monkeypatch.setenv("TRACKER_READ_ONLY", "enabled")
    with pytest.raises(ytm.ConfigError):
        ytm._parse_bool("TRACKER_READ_ONLY")


def _run_python(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, "TRACKER_ENV_FILE": os.devnull, **env}
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=full_env, capture_output=True, encoding="utf-8", timeout=60
    )


LIST_TOOLS = "import asyncio, yandex_tracker_mcp as m; print(len(asyncio.run(m.mcp.list_tools())))"


def test_all_tools_registered():
    assert _run_python(LIST_TOOLS).stdout.strip() == "18"


def test_read_only_hides_write_tools():
    assert _run_python(LIST_TOOLS, TRACKER_READ_ONLY="1").stdout.strip() == "12"


def test_read_only_typo_fails_safe_and_main_exits():
    assert _run_python(LIST_TOOLS, TRACKER_READ_ONLY="enabled").stdout.strip() == "12"
    result = _run_python("import yandex_tracker_mcp as m; m.main()", TRACKER_READ_ONLY="enabled")
    assert result.returncode == 1
    assert "TRACKER_READ_ONLY" in result.stderr


def test_main_reports_missing_token():
    result = _run_python("import yandex_tracker_mcp as m; m.main()", TRACKER_TOKEN="")
    assert result.returncode == 1
    assert "TRACKER_TOKEN" in result.stderr


PRINT_TOKEN = "import os, yandex_tracker_mcp; print(os.environ.get('TRACKER_TOKEN', ''))"


def test_env_file_in_cwd_is_ignored(tmp_path):
    (tmp_path / ".env").write_text("TRACKER_TOKEN=from-cwd\n")
    env = {k: v for k, v in os.environ.items() if k != "TRACKER_TOKEN"}
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", PRINT_TOKEN], cwd=tmp_path, env=env, capture_output=True, encoding="utf-8", timeout=60
    )
    assert result.stdout.strip() == ""


def test_env_file_from_tracker_env_file(tmp_path):
    env_file = tmp_path / "custom.env"
    env_file.write_text("TRACKER_TOKEN=from-file\n")
    env = {k: v for k, v in os.environ.items() if k != "TRACKER_TOKEN"}
    result = subprocess.run(
        [sys.executable, "-c", PRINT_TOKEN],
        cwd=ROOT,
        env={**env, "TRACKER_ENV_FILE": str(env_file)},
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    assert result.stdout.strip() == "from-file"


def test_write_guard_in_request(api, monkeypatch):
    monkeypatch.setattr(ytm, "READ_ONLY", True)
    with pytest.raises(RuntimeError, match="только чтения"):
        asyncio.run(ytm._request("POST", "/issues/", body={}, write=True))
    assert api.requests == []


# ---------- Запросы и ошибки ----------


@pytest.mark.parametrize("key", ["../../users", "PROJ-1/../x", "PROJ-1?a=b", "PROJ-1#x", "a.b", ""])
def test_path_traversal_rejected(api, key):
    with pytest.raises(ValueError, match="Недопустимый"):
        asyncio.run(ytm.get_issue(key))
    assert api.requests == []


def test_get_issue_brief(api):
    api.handler = lambda r: httpx.Response(
        200,
        json={
            "key": "PROJ-1",
            "summary": "S",
            "status": {"key": "open", "display": "Открыт"},
            "queue": {"key": "PROJ", "display": "Проект"},
            "createdBy": {"display": "Иван"},
            "parent": {"key": "PROJ-0"},
            "description": "D",
        },
    )
    result = run(ytm.get_issue("PROJ-1"))
    assert str(api.requests[0].url) == "https://api.tracker.yandex.net/v3/issues/PROJ-1"
    assert api.requests[0].headers["Authorization"] == "OAuth test-token"
    assert api.requests[0].headers["X-Org-ID"] == "42"
    assert result["status"] == "Открыт"
    assert result["queue"] == "PROJ"
    assert result["createdBy"] == "Иван"
    assert result["parent"] == "PROJ-0"


def test_error_message_parses_tracker_errors(api):
    api.handler = lambda r: httpx.Response(404, json={"errorMessages": ["Задача не существует."], "errors": {}})
    with pytest.raises(RuntimeError, match=r"404 GET /issues/PROJ-9: Задача не существует\.$"):
        asyncio.run(ytm.get_issue("PROJ-9"))


def test_error_message_auth_hint_and_truncation(api):
    api.handler = lambda r: httpx.Response(401, text="x" * 5000)
    with pytest.raises(RuntimeError) as e:
        asyncio.run(ytm.whoami())
    assert "TRACKER_TOKEN" in str(e.value)
    assert len(str(e.value)) < ytm.ERROR_TEXT_LIMIT + 200


@pytest.mark.parametrize(
    "payload",
    [
        {"errorMessages": None, "errors": None},
        {"errorMessages": "строка", "errors": ["список"]},
        ["массив"],
        {},
    ],
)
def test_error_message_odd_payloads_fall_back_to_body(api, payload):
    api.handler = lambda r: httpx.Response(400, json=payload)
    with pytest.raises(RuntimeError, match=r"^Tracker API 400 GET /myself: "):
        asyncio.run(ytm.whoami())


def test_redirect_is_error(api):
    api.handler = lambda r: httpx.Response(302, headers={"Location": "https://elsewhere"})
    with pytest.raises(RuntimeError, match="редирект"):
        asyncio.run(ytm.whoami())


def test_non_json_body(api):
    api.handler = lambda r: httpx.Response(200, text="<html>", headers={"Content-Type": "text/html"})
    with pytest.raises(RuntimeError, match="не JSON"):
        asyncio.run(ytm.whoami())


def test_write_timeout_warns_about_unknown_result(api):
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    api.handler = handler
    with pytest.raises(RuntimeError, match="мог выполниться"):
        asyncio.run(ytm.add_comment("PROJ-1", "hi"))


def test_connect_error_on_write_has_no_ambiguity_warning(api):
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    api.handler = handler
    with pytest.raises(RuntimeError) as e:
        asyncio.run(ytm.add_comment("PROJ-1", "hi"))
    assert "ConnectError" in str(e.value)
    assert "мог выполниться" not in str(e.value)


def test_empty_body_is_ok(api):
    api.handler = lambda r: httpx.Response(204)
    assert run(ytm.add_worklog("PROJ-1", "PT1H")) == {"ok": True, "http_status": 204}


def test_unexpected_shape(api):
    api.handler = lambda r: httpx.Response(200, json={"not": "a list"})
    with pytest.raises(RuntimeError, match="ожидался список"):
        asyncio.run(ytm.list_fields())


# ---------- Инструменты ----------


def test_search_requires_exactly_one_criterion(api):
    with pytest.raises(ValueError, match="ровно один"):
        asyncio.run(ytm.search_issues())
    with pytest.raises(ValueError, match="ровно один"):
        asyncio.run(ytm.search_issues(query="x", queue="PROJ"))
    assert api.requests == []


def test_search_pagination(api):
    api.handler = lambda r: httpx.Response(
        200, json=[{"key": "PROJ-1"}], headers={"X-Total-Count": "120", "X-Total-Pages": "3"}
    )
    result = run(ytm.search_issues(filters={"queue": "PROJ"}, per_page=50, page=2))
    request = api.requests[0]
    assert request.url.params["perPage"] == "50" and request.url.params["page"] == "2"
    assert json.loads(request.content) == {"filter": {"queue": "PROJ"}}
    assert result["total"] == 120 and result["total_pages"] == 3 and result["has_more"] is True
    assert result["items"][0]["key"] == "PROJ-1"


def test_list_queues_last_page(api):
    api.handler = lambda r: httpx.Response(
        200, json=[{"key": "A", "name": "a", "extra": 1}], headers={"X-Total-Pages": "1"}
    )
    result = run(ytm.list_queues())
    assert result["items"] == [{"key": "A", "name": "a"}]
    assert result["has_more"] is False


def test_comments_cursor(api):
    api.handler = lambda r: httpx.Response(200, json=[{"id": 1, "text": "a"}, {"id": 2, "text": "b"}])
    result = run(ytm.get_comments("PROJ-1", per_page=2, after_id=10))
    assert api.requests[0].url.params["id"] == "10"
    assert result["has_more"] is True and result["next_after_id"] == 2


def test_create_issue_body(api):
    api.handler = lambda r: httpx.Response(201, json={"key": "PROJ-2"})
    result = run(ytm.create_issue("PROJ", "S", issue_type="bug", extra_fields={"deadline": "2026-10-10"}))
    assert json.loads(api.requests[0].content) == {
        "queue": "PROJ",
        "summary": "S",
        "type": "bug",
        "deadline": "2026-10-10",
    }
    assert result["key"] == "PROJ-2"


def test_create_issue_extra_fields_cannot_override(api):
    with pytest.raises(ValueError, match="queue"):
        asyncio.run(ytm.create_issue("PROJ", "S", extra_fields={"queue": "OTHER"}))
    assert api.requests == []


def test_update_issue_rejects_empty(api):
    with pytest.raises(ValueError, match="пуст"):
        asyncio.run(ytm.update_issue("PROJ-1", {}))


def test_transition_path(api):
    api.handler = lambda r: httpx.Response(200, json=[])
    asyncio.run(ytm.transition_issue("PROJ-1", "close", resolution="fixed"))
    assert api.requests[0].url.path == "/v3/issues/PROJ-1/transitions/close/_execute"
    assert json.loads(api.requests[0].content) == {"resolution": "fixed"}
    with pytest.raises(ValueError):
        asyncio.run(ytm.transition_issue("PROJ-1", "../../x"))


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("search_issues", {"query": "x", "per_page": 0}),
        ("search_issues", {"query": "x", "per_page": 101}),
        ("list_users", {"page": 0}),
        ("link_issues", {"issue_key": "A-1", "other_issue": "A-2", "relationship": "blocks"}),
    ],
)
def test_schema_validation_via_mcp(api, tool, args):
    """Ограничения из схемы проверяет FastMCP, до вызова функции и HTTP-запроса."""
    with pytest.raises(Exception, match="validation error"):
        asyncio.run(ytm.mcp.call_tool(tool, args))
    assert api.requests == []


def test_tool_annotations():
    tools = {t.name: t for t in asyncio.run(ytm.mcp.list_tools())}
    assert tools["get_issue"].annotations.readOnlyHint is True
    assert tools["create_issue"].annotations.readOnlyHint is False
    assert tools["update_issue"].annotations.destructiveHint is True
