"""Narrow shared parsing helpers for canonical API routes."""
from __future__ import annotations

from dataclasses import dataclass


class ApiRequestError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Pagination:
    limit: int
    cursor: str


def parse_pagination(limit: int | None, cursor: str | None = "") -> Pagination:
    try:
        value = 20 if limit is None else int(limit)
    except (TypeError, ValueError) as exc:
        raise ApiRequestError("PAGINATION_LIMIT_INVALID", "limit must be an integer between 1 and 100.") from exc
    if value < 1 or value > 100:
        raise ApiRequestError("PAGINATION_LIMIT_INVALID", "limit must be between 1 and 100.")
    value_cursor = str(cursor or "").strip()
    if len(value_cursor) > 512:
        raise ApiRequestError("PAGINATION_CURSOR_INVALID", "cursor is too long.")
    return Pagination(limit=value, cursor=value_cursor)
