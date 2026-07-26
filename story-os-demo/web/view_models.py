from __future__ import annotations

from typing import Any
import re

from core.contracts import ErrorEnvelope


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
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    values = errors or [message]
    code = next((item for item in values if re.fullmatch(r"[A-Z]+(?:_[A-Z0-9]+)+", str(item))), "SYS_ERROR")
    return ErrorEnvelope(code=code, message=message, details=details or {}).compatibility_view(
        warnings=warnings,
        errors=values,
    )
