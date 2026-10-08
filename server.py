"""MCP-сервер для Яндекс Трекера (API v3).

Переменные окружения:
  TRACKER_TOKEN      — OAuth-токен (или IAM-токен, см. TRACKER_AUTH_TYPE)
  TRACKER_AUTH_TYPE  — "oauth" (по умолчанию) или "iam"
  TRACKER_ORG_ID     — ID организации Яндекс 360 (заголовок X-Org-ID)
  TRACKER_CLOUD_ORG_ID — ID организации Yandex Cloud (заголовок X-Cloud-Org-ID)
  TRACKER_READ_ONLY  — "1", чтобы отключить все пишущие инструменты
Нужен ровно один из TRACKER_ORG_ID / TRACKER_CLOUD_ORG_ID.

Значения можно положить в .env рядом с server.py или в текущей папке.
Переменные окружения (например, из `claude mcp add -e`) имеют приоритет.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import find_dotenv, load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).with_name(".env"))
load_dotenv(find_dotenv(usecwd=True))

BASE_URL = os.environ.get("TRACKER_API_URL", "https://api.tracker.yandex.net/v3")
READ_ONLY = os.environ.get("TRACKER_READ_ONLY", "").lower() in ("1", "true", "yes")

mcp = FastMCP("yandex-tracker")


def _headers() -> dict[str, str]:
    token = os.environ.get("TRACKER_TOKEN")
    if not token:
        raise RuntimeError("Не задан TRACKER_TOKEN")
    auth_type = os.environ.get("TRACKER_AUTH_TYPE", "oauth").lower()
    headers = {
        "Authorization": f"{'Bearer' if auth_type == 'iam' else 'OAuth'} {token}",
        "Content-Type": "application/json",
    }
    if org := os.environ.get("TRACKER_ORG_ID"):
        headers["X-Org-ID"] = org
    elif cloud_org := os.environ.get("TRACKER_CLOUD_ORG_ID"):
        headers["X-Cloud-Org-ID"] = cloud_org
    else:
        raise RuntimeError("Задайте TRACKER_ORG_ID или TRACKER_CLOUD_ORG_ID")
    return headers


async def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    body: Any = None,
) -> Any:
    params = {k: v for k, v in (params or {}).items() if v is not None}
    async with httpx.AsyncClient(base_url=BASE_URL, headers=_headers(), timeout=30) as client:
        resp = await client.request(method, path, params=params, json=body)
    if resp.status_code >= 400:
        raise RuntimeError(f"Tracker API {resp.status_code} {method} {path}: {resp.text}")
    if not resp.content:
        return {"status": resp.status_code}
    return resp.json()


def _out(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _brief_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """Сжатое представление задачи, чтобы не забивать контекст."""

    def display(field: str) -> Any:
        v = issue.get(field)
        return v.get("display") if isinstance(v, dict) else v

    return {
        "key": issue.get("key"),
        "summary": issue.get("summary"),
        "status": display("status"),
        "type": display("type"),
        "priority": display("priority"),
        "assignee": display("assignee"),
        "queue": (issue.get("queue") or {}).get("key"),
        "updatedAt": issue.get("updatedAt"),
    }


def _writable() -> None:
    if READ_ONLY:
        raise RuntimeError("Сервер запущен в режиме только чтения (TRACKER_READ_ONLY)")


# ---------- Чтение ----------


@mcp.tool()
async def whoami() -> str:
    """Текущий пользователь, от имени которого работает токен."""
    me = await _request("GET", "/myself")
    return _out({k: me.get(k) for k in ("uid", "login", "display", "email")})


@mcp.tool()
async def get_issue(issue_key: str, full: bool = False) -> str:
    """Получить задачу по ключу (например, PROJ-123). full=True — все поля как есть."""
    issue = await _request("GET", f"/issues/{issue_key}")
    if full:
        return _out(issue)
    brief = _brief_issue(issue)
    brief["description"] = issue.get("description")
    brief["createdBy"] = (issue.get("createdBy") or {}).get("display")
    brief["createdAt"] = issue.get("createdAt")
    brief["deadline"] = issue.get("deadline")
    brief["tags"] = issue.get("tags")
    brief["parent"] = (issue.get("parent") or {}).get("key")
    return _out(brief)


@mcp.tool()
async def search_issues(
    query: str | None = None,
    queue: str | None = None,
    filter: dict[str, Any] | None = None,
    per_page: int = 50,
    page: int = 1,
) -> str:
    """Поиск задач.

    query  — запрос на языке Трекера, напр.: 'Queue: PROJ AND Assignee: me() AND Resolution: empty()'
             или '"Sort by": Updated DESC'.
    queue  — ключ очереди (все задачи очереди).
    filter — фильтр по полям, напр. {"queue": "PROJ", "assignee": "login"}.
    Указывайте что-то одно. Возвращает краткий список.
    """
    body: dict[str, Any] = {}
    if query:
        body["query"] = query
    elif queue:
        body["queue"] = queue
    elif filter:
        body["filter"] = filter
    else:
        raise ValueError("Нужен query, queue или filter")
    issues = await _request(
        "POST", "/issues/_search", params={"perPage": min(per_page, 100), "page": page}, body=body
    )
    return _out([_brief_issue(i) for i in issues])


@mcp.tool()
async def count_issues(query: str) -> str:
    """Количество задач по запросу на языке Трекера."""
    return _out(await _request("POST", "/issues/_count", body={"query": query}))


@mcp.tool()
async def get_comments(issue_key: str) -> str:
    """Комментарии к задаче."""
    comments = await _request("GET", f"/issues/{issue_key}/comments")
    return _out(
        [
            {
                "id": c.get("id"),
                "author": (c.get("createdBy") or {}).get("display"),
                "createdAt": c.get("createdAt"),
                "text": c.get("text"),
            }
            for c in comments
        ]
    )


@mcp.tool()
async def get_transitions(issue_key: str) -> str:
    """Доступные переходы по статусам для задачи (id нужен для transition_issue)."""
    transitions = await _request("GET", f"/issues/{issue_key}/transitions")
    return _out(
        [
            {"id": t.get("id"), "display": t.get("display"), "to": (t.get("to") or {}).get("display")}
            for t in transitions
        ]
    )


@mcp.tool()
async def get_links(issue_key: str) -> str:
    """Связи задачи с другими задачами."""
    links = await _request("GET", f"/issues/{issue_key}/links")
    return _out(
        [
            {
                "id": l.get("id"),
                "type": (l.get("type") or {}).get("id"),
                "direction": l.get("direction"),
                "issue": (l.get("object") or {}).get("key"),
                "summary": (l.get("object") or {}).get("display"),
            }
            for l in links
        ]
    )


@mcp.tool()
async def get_worklog(issue_key: str) -> str:
    """Записи о затраченном времени по задаче."""
    return _out(await _request("GET", f"/issues/{issue_key}/worklog"))


@mcp.tool()
async def list_queues(per_page: int = 100) -> str:
    """Список очередей."""
    queues = await _request("GET", "/queues/", params={"perPage": per_page})
    return _out([{"key": q.get("key"), "name": q.get("name")} for q in queues])


@mcp.tool()
async def get_queue(queue_key: str) -> str:
    """Информация об очереди (с типами задач и приоритетами)."""
    return _out(await _request("GET", f"/queues/{queue_key}", params={"expand": "all"}))


@mcp.tool()
async def list_users(per_page: int = 100, page: int = 1) -> str:
    """Пользователи организации (логины нужны для назначения исполнителя)."""
    users = await _request("GET", "/users", params={"perPage": per_page, "page": page})
    return _out([{k: u.get(k) for k in ("uid", "login", "display", "email")} for u in users])


@mcp.tool()
async def list_fields() -> str:
    """Глобальные поля задач (id, название, тип) — полезно для update_issue."""
    fields = await _request("GET", "/fields")
    return _out(
        [{"id": f.get("id"), "name": f.get("name"), "type": (f.get("schema") or {}).get("type")} for f in fields]
    )


# ---------- Запись ----------


@mcp.tool()
async def create_issue(
    queue: str,
    summary: str,
    description: str | None = None,
    type: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    parent: str | None = None,
    tags: list[str] | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> str:
    """Создать задачу. type/priority — ключи (напр. 'task', 'bug' / 'normal', 'critical'),
    assignee — логин, parent — ключ родительской задачи, extra_fields — любые другие поля."""
    _writable()
    body: dict[str, Any] = {"queue": queue, "summary": summary}
    for k, v in {
        "description": description,
        "type": type,
        "priority": priority,
        "assignee": assignee,
        "parent": parent,
        "tags": tags,
    }.items():
        if v is not None:
            body[k] = v
    body.update(extra_fields or {})
    issue = await _request("POST", "/issues/", body=body)
    return _out(_brief_issue(issue))


@mcp.tool()
async def update_issue(issue_key: str, fields: dict[str, Any]) -> str:
    """Изменить поля задачи. Пример fields: {"summary": "...", "assignee": "login",
    "tags": {"add": ["x"]}, "description": "..."}."""
    _writable()
    issue = await _request("PATCH", f"/issues/{issue_key}", body=fields)
    return _out(_brief_issue(issue))


@mcp.tool()
async def add_comment(issue_key: str, text: str, summonees: list[str] | None = None) -> str:
    """Добавить комментарий (поддерживается разметка YFM). summonees — логины для призыва."""
    _writable()
    body: dict[str, Any] = {"text": text}
    if summonees:
        body["summonees"] = summonees
    c = await _request("POST", f"/issues/{issue_key}/comments", body=body)
    return _out({"id": c.get("id"), "createdAt": c.get("createdAt")})


@mcp.tool()
async def transition_issue(
    issue_key: str,
    transition_id: str,
    comment: str | None = None,
    resolution: str | None = None,
) -> str:
    """Перевести задачу в другой статус. transition_id брать из get_transitions.
    resolution — напр. 'fixed', если переход требует резолюцию."""
    _writable()
    body: dict[str, Any] = {}
    if comment:
        body["comment"] = comment
    if resolution:
        body["resolution"] = resolution
    result = await _request(
        "POST", f"/issues/{issue_key}/transitions/{transition_id}/_execute", body=body
    )
    return _out(result)


@mcp.tool()
async def link_issues(issue_key: str, other_issue: str, relationship: str = "relates") -> str:
    """Связать задачи. relationship: relates, depends on, is dependent by, is subtask for,
    is parent task for, duplicates, is duplicated by, is epic of, has epic."""
    _writable()
    return _out(
        await _request(
            "POST",
            f"/issues/{issue_key}/links",
            body={"relationship": relationship, "issue": other_issue},
        )
    )


@mcp.tool()
async def add_worklog(issue_key: str, duration: str, start: str | None = None, comment: str | None = None) -> str:
    """Списать время. duration в ISO 8601 (напр. 'PT1H30M'),
    start — '2026-10-08T10:00:00.000+0300' (по умолчанию — сейчас)."""
    _writable()
    body: dict[str, Any] = {"duration": duration}
    if start:
        body["start"] = start
    if comment:
        body["comment"] = comment
    return _out(await _request("POST", f"/issues/{issue_key}/worklog", body=body))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
