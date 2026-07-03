from __future__ import annotations

from typing import Any


def api_ok(
    message: str = "",
    result: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "message": message,
        "result": result or {},
        "warnings": warnings or [],
        "errors": [],
    }


def api_error(
    message: str,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "message": message,
        "result": {},
        "warnings": warnings or [],
        "errors": errors or [message],
    }
