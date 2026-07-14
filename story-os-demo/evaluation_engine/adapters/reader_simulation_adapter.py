from __future__ import annotations

from typing import Any

def adapt(result: dict[str, Any], source_ref: str) -> dict[str, dict[str, Any]]:
    # Reader signals embedded in the existing quality report are handled by its adapter.
    del result, source_ref
    return {}
