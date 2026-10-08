import asyncio
import json

import httpx
import pytest

from conftest import run_tool
from yandex_tracker_mcp.server import (
    create_issue,
    delete_comment,
    edit_comment,
    get_comments,
    get_issue,
    list_queues,
    mcp,
    search_issues,
    transition_issue,
    update_issue,
)


def test_get_issue_brief(api):
    api.handler = lambda r: httpx.Response(
        200,
        json={
            "key": "PROJ-1",
            "summary": "S",
            "status": {"key": "open", "display": "Open"},
            "queue": {"key": "PROJ", "display": "Project"},
            "createdBy": {"display": "Jane"},
            "parent": {"key": "PROJ-0"},
            "description": "D",
        },
    )
    result = run_tool(get_issue("PROJ-1"))
    assert result["status"] == "Open"
    assert result["queue"] == "PROJ"
    assert result["createdBy"] == "Jane"
    assert result["parent"] == "PROJ-0"


def test_search_requires_exactly_one_criterion(api):
    with pytest.raises(ValueError, match="exactly one"):
        asyncio.run(search_issues())
    with pytest.raises(ValueError, match="exactly one"):
        asyncio.run(search_issues(query="x", queue="PROJ"))
    assert api.requests == []


def test_search_pagination(api):
    api.handler = lambda r: httpx.Response(
        200, json=[{"key": "PROJ-1"}], headers={"X-Total-Count": "120", "X-Total-Pages": "3"}
    )
    result = run_tool(search_issues(filters={"queue": "PROJ"}, per_page=50, page=2))
    request = api.requests[0]
    assert request.url.params["perPage"] == "50"
    assert request.url.params["page"] == "2"
    assert json.loads(request.content) == {"filter": {"queue": "PROJ"}}
    assert result["total"] == 120
    assert result["total_pages"] == 3
    assert result["has_more"] is True
    assert result["items"][0]["key"] == "PROJ-1"


def test_list_queues_last_page(api):
    api.handler = lambda r: httpx.Response(
        200, json=[{"key": "A", "name": "a", "extra": 1}], headers={"X-Total-Pages": "1"}
    )
    result = run_tool(list_queues())
    assert result["items"] == [{"key": "A", "name": "a"}]
    assert result["has_more"] is False


def test_comments_cursor(api):
    api.handler = lambda r: httpx.Response(200, json=[{"id": 1, "text": "a"}, {"id": 2, "text": "b"}])
    result = run_tool(get_comments("PROJ-1", per_page=2, after_id=10))
    assert api.requests[0].url.params["id"] == "10"
    assert result["has_more"] is True
    assert result["next_after_id"] == 2


def test_create_issue_body(api):
    api.handler = lambda r: httpx.Response(201, json={"key": "PROJ-2"})
    result = run_tool(create_issue("PROJ", "S", issue_type="bug", extra_fields={"deadline": "2026-10-10"}))
    assert json.loads(api.requests[0].content) == {
        "queue": "PROJ",
        "summary": "S",
        "type": "bug",
        "deadline": "2026-10-10",
    }
    assert result["key"] == "PROJ-2"


def test_create_issue_extra_fields_cannot_override(api):
    with pytest.raises(ValueError, match="queue"):
        asyncio.run(create_issue("PROJ", "S", extra_fields={"queue": "OTHER"}))
    assert api.requests == []


def test_update_issue_rejects_empty(api):
    with pytest.raises(ValueError, match="empty"):
        asyncio.run(update_issue("PROJ-1", {}))


def test_transition_path(api):
    api.handler = lambda r: httpx.Response(200, json=[])
    asyncio.run(transition_issue("PROJ-1", "close", resolution="fixed"))
    assert api.requests[0].url.path == "/v3/issues/PROJ-1/transitions/close/_execute"
    assert json.loads(api.requests[0].content) == {"resolution": "fixed"}
    with pytest.raises(ValueError, match="Invalid transition id"):
        asyncio.run(transition_issue("PROJ-1", "../../x"))


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
    """FastMCP enforces schema constraints before the tool runs and before any HTTP request."""
    with pytest.raises(Exception, match="validation error"):
        asyncio.run(mcp.call_tool(tool, args))
    assert api.requests == []


def test_tool_annotations():
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert tools["get_issue"].annotations.readOnlyHint is True
    assert tools["create_issue"].annotations.readOnlyHint is False
    assert tools["update_issue"].annotations.destructiveHint is True


def test_edit_comment(api):
    api.handler = lambda r: httpx.Response(200, json={"id": 42, "updatedAt": "now", "version": 2, "text": "new"})
    result = run_tool(edit_comment("PROJ-1", 42, "new"))
    request = api.requests[0]
    assert request.method == "PATCH"
    assert request.url.path == "/v3/issues/PROJ-1/comments/42"
    assert json.loads(request.content) == {"text": "new"}
    assert result == {"id": 42, "updatedAt": "now", "version": 2}


def test_edit_comment_with_files(api, tmp_path, monkeypatch, clean_config):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("a")

    def handler(request):
        if request.url.path == "/v3/attachments":
            return httpx.Response(201, json={"id": "t1"})
        return httpx.Response(200, json={"id": 42})

    api.handler = handler
    result = run_tool(edit_comment("PROJ-1", "42", "new", file_paths=["a.txt"]))
    assert json.loads(api.requests[1].content) == {"text": "new", "attachmentIds": ["t1"]}
    assert [p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in result["uploaded_from"]] == ["a.txt"]


def test_delete_comment(api):
    api.handler = lambda r: httpx.Response(204)
    result = run_tool(delete_comment("PROJ-1", "42"))
    assert api.requests[0].method == "DELETE"
    assert api.requests[0].url.path == "/v3/issues/PROJ-1/comments/42"
    assert result == {"deleted": True, "comment_id": "42"}


@pytest.mark.parametrize("comment_id", ["../42", "42?x=1", "4.2", ""])
def test_comment_id_validated(api, comment_id):
    with pytest.raises(ValueError, match="Invalid comment id"):
        asyncio.run(delete_comment("PROJ-1", comment_id))
    with pytest.raises(ValueError, match="Invalid comment id"):
        asyncio.run(edit_comment("PROJ-1", comment_id, "x"))
    assert api.requests == []


def test_edit_comment_rejects_empty_text(api):
    with pytest.raises(ValueError, match="text"):
        asyncio.run(edit_comment("PROJ-1", "42", "  "))
    assert api.requests == []


def test_comment_tools_are_destructive():
    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert tools["edit_comment"].annotations.destructiveHint is True
    assert tools["delete_comment"].annotations.destructiveHint is True


def test_comment_long_id_accepted(api):
    api.handler = lambda r: httpx.Response(204)
    run_tool(delete_comment("PROJ-1", "5f3c9a1b2d4e6f7a8b9c0d1e"))
    assert api.requests[0].url.path == "/v3/issues/PROJ-1/comments/5f3c9a1b2d4e6f7a8b9c0d1e"
