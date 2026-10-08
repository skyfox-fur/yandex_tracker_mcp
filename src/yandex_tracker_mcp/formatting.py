"""Compact, LLM-friendly views of Tracker API objects."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import httpx


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def drop_none(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def attr(value: Any, name: str = "display") -> Any:
    """Reads a field of a nested Tracker reference such as {"key": ..., "display": ...}."""
    return value.get(name) if isinstance(value, dict) else value


def pick(data: dict[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    return {k: data.get(k) for k in keys}


def _int_header(headers: httpx.Headers, name: str) -> int | None:
    try:
        return int(headers[name])
    except (KeyError, ValueError):
        return None


def paged(items: list[Any], headers: httpx.Headers, page: int, per_page: int) -> dict[str, Any]:
    """Wraps a page of results with totals from Tracker's X-Total-Count / X-Total-Pages headers."""
    result: dict[str, Any] = {"items": items, "page": page, "per_page": per_page}
    total, pages = _int_header(headers, "X-Total-Count"), _int_header(headers, "X-Total-Pages")
    if total is not None:
        result["total"] = total
    if pages is not None:
        result["total_pages"] = pages
        result["has_more"] = page < pages
    else:
        result["has_more"] = len(items) == per_page
    return result


def brief_issue(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": issue.get("key"),
        "summary": issue.get("summary"),
        "status": attr(issue.get("status")),
        "type": attr(issue.get("type")),
        "priority": attr(issue.get("priority")),
        "assignee": attr(issue.get("assignee")),
        "queue": attr(issue.get("queue"), "key"),
        "updatedAt": issue.get("updatedAt"),
    }
