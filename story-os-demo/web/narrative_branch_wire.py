"""JSON-safe DTOs for Phase 0D4-E1 Branch Lifecycle API."""
from __future__ import annotations

from typing import Any


def branch_wire(branch: dict[str, Any]) -> dict[str, Any]:
    return {
        "branch_id": branch.get("branch_id"),
        "parent_branch_id": branch.get("parent_branch_id"),
        "created_from_turn_id": branch.get("created_from_turn_id"),
        "lifecycle_status": branch.get("lifecycle_status"),
        "activity": branch.get("activity"),
        "is_active": bool(branch.get("is_active")),
        "created_at": branch.get("created_at"),
        "archived_at": branch.get("archived_at"),
    }


def branch_list_wire(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "registry_revision": result.get("registry_revision"),
        "active_branch_id": result.get("active_branch_id"),
        "branches": [branch_wire(item) for item in result.get("branches", [])],
    }


def branch_operation_wire(result: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "schema_version": "1.0",
        "operation_id": result.get("operation_id"),
        "operation_type": result.get("operation_type"),
        "idempotent_replay": bool(result.get("idempotent_replay")),
        "recovery_performed": bool(result.get("recovery_performed")),
        "registry_revision": result.get("registry_revision"),
        "active_branch_id": result.get("active_branch_id"),
        "branch": branch_wire(result["branch"]) if result.get("branch") else None,
    }
    if result.get("replacement_branch"):
        payload["replacement_branch"] = branch_wire(result["replacement_branch"])
    return payload
