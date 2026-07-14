"""Author-confirmed rolling planning windows; never an execution plan."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any

from core.project_context import ProjectContext, get_project_context

from .control_service import PlanningControlError, PlanningControlService
from .models import base_entity, content_hash, new_id, now
from .rolling_models import SLOT_STATUSES, WINDOW_STATUSES, make_slot, validate_configuration, validate_slot
from .rolling_projection import blueprint_slot_suggestions, far_horizon_projection, resolve_planning_anchor


class RollingWindowService:
    def __init__(self, context: ProjectContext | None = None) -> None:
        self.context = context or get_project_context()
        self.control = PlanningControlService(self.context)
        self.project_id = self.context.root.resolve().as_posix()

    _CONTROL_FIELDS = {"expected_window_revision", "operation_id", "preview_id", "author_confirm"}

    def _save(self, window: dict[str, Any], event: str, old: dict[str, Any] | None = None, payload: dict[str, Any] | None = None, affected_slot_ids: list[str] | None = None) -> dict[str, Any]:
        payload = payload or {}
        expected = payload.get("expected_window_revision")
        try: expected_value = int(expected) if expected is not None else None
        except (TypeError, ValueError) as exc: raise PlanningControlError("ROLLING_WINDOW_REVISION_CONFLICT") from exc
        return self.control.save_rolling_window(window, event=event, old=old, expected_window_revision=expected_value, operation_id=str(payload.get("operation_id", "") or ""), affected_slot_ids=affected_slot_ids, reason=str(payload.get("reason", "") or ""))

    @classmethod
    def _content_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in payload.items() if key not in cls._CONTROL_FIELDS}

    def _record_preview(self, preview: dict[str, Any], kind: str, window: dict[str, Any], anchor: dict[str, Any]) -> dict[str, Any]:
        preview = copy.deepcopy(preview)
        stamp = datetime.now(timezone.utc)
        preview.update({"preview_id": new_id("rolling_preview"), "preview_type": kind, "project_id": self.project_id, "window_id": window.get("window_id", ""), "window_revision": int(window.get("window_revision", 0) or 0), "anchor_snapshot": copy.deepcopy(window.get("anchor", {})), "state_hash": anchor.get("state_hash", ""), "planning_control_version_id": window.get("anchor", {}).get("planning_control_version_id", ""), "created_at": stamp.isoformat(), "expires_at": (stamp + timedelta(minutes=10)).isoformat()})
        return self.control.save_rolling_preview(preview)

    def _validate_preview(self, payload: dict[str, Any], kind: str, window: dict[str, Any], anchor: dict[str, Any]) -> None:
        preview_id = str(payload.get("preview_id", "") or "")
        if not preview_id:
            return
        preview = self.control.get_rolling_preview(preview_id)
        if not preview or preview.get("preview_type") != kind or preview.get("project_id") != self.project_id:
            raise PlanningControlError("ROLLING_PREVIEW_STALE", "预览不存在、已过期或不属于当前项目。")
        expired = datetime.fromisoformat(str(preview.get("expires_at", "1970-01-01T00:00:00+00:00"))) <= datetime.now(timezone.utc)
        valid = int(preview.get("window_revision", -1)) == int(window.get("window_revision", 0) or 0) and preview.get("anchor_snapshot") == window.get("anchor", {}) and preview.get("state_hash") == anchor.get("state_hash")
        if expired or not valid:
            raise PlanningControlError("ROLLING_PREVIEW_STALE", "预览已失效，请重新查看预览后确认。")

    def _replay(self, payload: dict[str, Any], event: str) -> dict[str, Any] | None:
        record = self.control.get_rolling_operation(str(payload.get("operation_id", "") or ""), event)
        if not record:
            return None
        window = copy.deepcopy(record.get("result_window") or {})
        window["replayed"] = True
        return window

    def describe(self) -> dict[str, Any]:
        data = self.control._read()
        anchor = resolve_planning_anchor(self.context)
        window = data["rolling_window"]
        if not window:
            near, mid = 5, 10
            return {"materialized": False, "window": None, "anchor_suggestion": anchor, "configuration_suggestion": {"near_horizon_size": near, "mid_horizon_size": mid}, "near_range": self._range(anchor["next_chapter_number"], near), "mid_range": self._range(anchor["next_chapter_number"] + near, mid), "blueprint_slot_suggestions": blueprint_slot_suggestions(self.context, anchor, near + mid), "far_horizon_suggestion": far_horizon_projection(self.context, data, anchor), "warnings": anchor["warnings"]}
        health = self.check_window_health()
        view = copy.deepcopy(window)
        view["effective_status"] = health["status"]
        from .scheduling_service import NarrativeSchedulingService
        scheduler = NarrativeSchedulingService(self.context)
        view["schedule_summary"] = {slot["slot_id"]: scheduler.by_slot(slot["slot_id"]) for slot in self._all_slots(window)}
        return {"materialized": True, "window": view, "anchor_suggestion": anchor, "configuration_suggestion": window.get("configuration", {}), "near_range": self._range(anchor["next_chapter_number"], int(window.get("configuration", {}).get("near_horizon_size", 5))), "mid_range": self._range(anchor["next_chapter_number"] + int(window.get("configuration", {}).get("near_horizon_size", 5)), int(window.get("configuration", {}).get("mid_horizon_size", 10))), "blueprint_slot_suggestions": blueprint_slot_suggestions(self.context, anchor, sum(int(window.get("configuration", {}).get(key, default)) for key, default in (("near_horizon_size", 5), ("mid_horizon_size", 10)))), "far_horizon_suggestion": far_horizon_projection(self.context, data, anchor), "warnings": health["warnings"], "health": health}

    def initialize(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not bool(payload.get("author_confirm")):
            raise PlanningControlError("ROLLING_WINDOW_AUTHOR_CONFIRM_REQUIRED")
        if self.control._read()["rolling_window"]:
            raise PlanningControlError("ROLLING_WINDOW_ALREADY_EXISTS")
        near, mid = validate_configuration(payload.get("near_horizon_size", 5), payload.get("mid_horizon_size", 10))
        data = self.control._read(); anchor = resolve_planning_anchor(self.context)
        window = base_entity(self.project_id, new_id("rolling_window"))
        far_horizon = far_horizon_projection(self.context, data, anchor)
        window.update({"window_id": window["id"], "status": "active", "anchor": {key: value for key, value in anchor.items() if key != "warnings"}, "configuration": {"near_horizon_size": near, "mid_horizon_size": mid}, "near_slots": [make_slot(self.project_id, number, "near") for number in self._range(anchor["next_chapter_number"], near)], "mid_slots": [make_slot(self.project_id, number, "mid") for number in self._range(anchor["next_chapter_number"] + near, mid)], "elapsed_slots": [], "far_horizon": far_horizon, "source_refs": self._window_source_refs(data, far_horizon), "source_snapshot": self._source_snapshot(data), "author_confirmed_at": now()})
        return self._save(window, "rolling_window_initialized", payload=payload)

    def update_configuration(self, payload: dict[str, Any]) -> dict[str, Any]:
        window = self._window(); old = copy.deepcopy(window)
        near, mid = validate_configuration(payload.get("near_horizon_size", window["configuration"]["near_horizon_size"]), payload.get("mid_horizon_size", window["configuration"]["mid_horizon_size"]))
        self._assert_unlocked(window["window_id"], "configuration")
        window["configuration"] = {"near_horizon_size": near, "mid_horizon_size": mid}
        self._reclassify(window, int(window["anchor"]["next_chapter_number"]))
        return self._save(window, "rolling_window_configuration_updated", old, payload)

    def list_slots(self) -> dict[str, list[dict[str, Any]]]:
        window = self._window()
        return {"near_slots": window.get("near_slots", []), "mid_slots": window.get("mid_slots", [])}

    def create_slot(self, payload: dict[str, Any]) -> dict[str, Any]:
        window = self._window(); old = copy.deepcopy(window)
        chapter = int(payload.get("planned_chapter_number", 0) or 0)
        anchor = int(window["anchor"]["next_chapter_number"])
        if chapter < anchor or self._slot_by_chapter(window, chapter):
            raise PlanningControlError("CHAPTER_SLOT_POSITION_CONFLICT")
        horizon = self._horizon(window, chapter)
        if horizon is None:
            raise PlanningControlError("CHAPTER_SLOT_POSITION_CONFLICT")
        slot = make_slot(self.project_id, chapter, horizon); slot.update(self._content_payload(copy.deepcopy(payload))); slot.update({"slot_id": slot["id"], "project_id": self.project_id, "planned_chapter_number": chapter, "horizon": horizon})
        self._validate_slot(slot)
        window[f"{horizon}_slots"].append(slot); self._sort_slots(window)
        self._refresh_slot_locks(window)
        self._save(window, "chapter_slot_created", old, payload, [slot["slot_id"]])
        return slot

    def update_slot(self, slot_id: str, payload: dict[str, Any], event: str = "chapter_slot_updated") -> dict[str, Any]:
        window = self._window(); old = copy.deepcopy(window); slot = self._slot(window, slot_id); before = copy.deepcopy(slot)
        content = self._content_payload(payload)
        for field in content:
            self._assert_unlocked(slot_id, field)
        slot.update(copy.deepcopy(content)); slot["slot_id"] = slot_id; slot["id"] = slot_id
        self._validate_slot(slot); self._refresh_slot_locks(window)
        self._save(window, event, old, payload, [slot_id])
        return slot

    def transition_slot(self, slot_id: str, status: str, payload: dict[str, Any] | None = None, event: str = "chapter_slot_updated") -> dict[str, Any]:
        if status not in SLOT_STATUSES:
            raise PlanningControlError("CHAPTER_SLOT_STATUS_INVALID")
        existing = self._slot(self._window(), slot_id)
        if existing.get("status") == "elapsed" and status != "elapsed":
            raise PlanningControlError("CHAPTER_SLOT_ELAPSED_IMMUTABLE")
        if status == "elapsed":
            raise PlanningControlError("CHAPTER_SLOT_ELAPSED_REQUIRES_ROLL_FORWARD")
        content = dict(payload or {}); content["status"] = status
        return self.update_slot(slot_id, content, event)

    def cancel_slot(self, slot_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Keep the future-intent record while removing it from active consideration."""
        return self.transition_slot(slot_id, "cancelled", payload, "rolling_window_slot_cancelled")

    def move_slot(self, slot_id: str, chapter: int) -> dict[str, Any]:
        window = self._window(); old = copy.deepcopy(window); slot = self._slot(window, slot_id)
        self._assert_unlocked(slot_id, "planned_chapter_number")
        if self._slot_by_chapter(window, chapter, exclude=slot_id) or chapter < int(window["anchor"]["next_chapter_number"]):
            raise PlanningControlError("CHAPTER_SLOT_POSITION_CONFLICT")
        horizon = self._horizon(window, chapter)
        if horizon is None:
            raise PlanningControlError("CHAPTER_SLOT_POSITION_CONFLICT")
        for collection in ("near_slots", "mid_slots"):
            if slot in window[collection]: window[collection].remove(slot)
        slot.update({"planned_chapter_number": chapter, "horizon": horizon})
        if horizon == "mid" and slot.get("detail_level") == "detailed":
            slot["detail_level"] = "outline"
        self._validate_slot(slot); window[f"{horizon}_slots"].append(slot); self._sort_slots(window)
        self.control.save_rolling_window(window, event="chapter_slot_moved", old=old)
        return slot

    def adopt_blueprint_suggestion(self, slot_id: str, chapter: int) -> dict[str, Any]:
        window = self._window(); suggestions = {item["planned_chapter_number"]: item for item in blueprint_slot_suggestions(self.context, window["anchor"], 99)}
        suggestion = suggestions.get(chapter)
        if not suggestion:
            raise PlanningControlError("PLANNING_SOURCE_NOT_FOUND")
        summary = suggestion["summary"]
        payload = {"title_hint": summary.get("chapter_title", ""), "goal_summary": summary.get("chapter_goal", ""), "source_refs": [suggestion["source_ref"]]}
        return self.update_slot(slot_id, payload)

    def roll_forward(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Compatibility entry point: preview unless the author explicitly confirms."""
        payload = payload or {}
        if not bool(payload.get("author_confirm")):
            return {"preview": self.roll_forward_preview(), "applied": False}
        return self.confirm_roll_forward(payload)

    def roll_forward_preview(self) -> dict[str, Any]:
        window = self._window(); health = self.check_window_health(); anchor = resolve_planning_anchor(self.context)
        preview = self._roll_preview(window, anchor)
        preview.update({"status": health["status"], "issues": health["issues"], "warnings": health["warnings"]})
        return self._record_preview(preview, "roll_forward", window, anchor)

    def confirm_roll_forward(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        replay = self._replay(payload, "rolling_window_rolled_forward")
        if replay:
            return {"preview": {}, "applied": True, "replayed": True, "window": replay}
        window = self._window(); health = self.check_window_health(); anchor = resolve_planning_anchor(self.context)
        self._validate_preview(payload, "roll_forward", window, anchor)
        preview = self._roll_preview(window, anchor)
        if health["status"] == "reanchor_required":
            raise PlanningControlError("ROLLING_WINDOW_REANCHOR_REQUIRED")
        if health["status"] == "stale":
            raise PlanningControlError("ROLLING_WINDOW_REFRESH_REQUIRED")
        if int(anchor["next_chapter_number"]) <= int(window["anchor"].get("next_chapter_number", 0) or 0):
            return {"preview": preview, "applied": False, "window": window}
        if preview["locked_conflicts"]:
            raise PlanningControlError("PLANNING_LOCK_CONFLICT", "Locked slots require manual resolution before roll-forward")
        old = copy.deepcopy(window); target = int(anchor["next_chapter_number"])
        data = self.control._read(); far_horizon = far_horizon_projection(self.context, data, anchor)
        for slot in self._all_slots(window):
            if int(slot["planned_chapter_number"]) < target: slot["status"] = "elapsed"
        window["anchor"] = {key: value for key, value in anchor.items() if key != "warnings"}
        self._reclassify(window, target)
        window["far_horizon"] = far_horizon; window["source_refs"] = self._window_source_refs(data, far_horizon); window["source_snapshot"] = self._source_snapshot(data); window["status"] = "active"
        self._ensure_window_capacity(window); self._refresh_slot_locks(window)
        saved = self._save(window, "rolling_window_rolled_forward", old, payload, preview["elapsed_slot_ids"])
        try:
            from .scheduling_service import NarrativeSchedulingService
            elapsed = NarrativeSchedulingService(self.context).mark_elapsed_slots(preview["elapsed_slot_ids"])
            if elapsed.get("changed"):
                saved["schedule_elapsed"] = elapsed
        except PlanningControlError as error:
            saved.setdefault("warnings", []).append(f"SCHEDULE_ELAPSED_WARNING:{error.code}")
        return {"preview": preview, "applied": True, "window": saved}

    def reanchor(self, payload: dict[str, Any]) -> dict[str, Any]:
        if bool(payload.get("author_confirm")):
            replay = self._replay(payload, "rolling_window_reanchored")
            if replay:
                return {"preview": {}, "applied": True, "replayed": True, "window": replay}
        window = self._window(); anchor = resolve_planning_anchor(self.context)
        target = int(payload.get("next_chapter_number", anchor["next_chapter_number"]) or 0)
        preview = self._reanchor_preview(window, anchor, target)
        if target < 1:
            raise PlanningControlError("ROLLING_WINDOW_REANCHOR_INVALID")
        if not bool(payload.get("author_confirm")):
            return {"preview": self._record_preview(preview, "reanchor", window, anchor), "applied": False}
        self._validate_preview(payload, "reanchor", window, anchor)
        old = copy.deepcopy(window)
        conflicts = preview["locked_slot_ids"]
        if conflicts:
            raise PlanningControlError("PLANNING_LOCK_CONFLICT")
        anchor["next_chapter_number"] = target; anchor["last_canon_chapter_number"] = target - 1
        data = self.control._read(); far_horizon = far_horizon_projection(self.context, data, anchor)
        for slot in self._all_slots(window):
            if int(slot["planned_chapter_number"]) < target: slot["status"] = "elapsed"
        window["anchor"] = {key: value for key, value in anchor.items() if key != "warnings"}; self._reclassify(window, target); window["far_horizon"] = far_horizon; window["source_refs"] = self._window_source_refs(data, far_horizon); window["source_snapshot"] = self._source_snapshot(data); window["status"] = "active"; self._ensure_window_capacity(window); self._refresh_slot_locks(window)
        saved = self._save(window, "rolling_window_reanchored", old, payload, preview["affected_slot_ids"])
        try:
            from .scheduling_service import NarrativeSchedulingService
            elapsed = NarrativeSchedulingService(self.context).mark_elapsed_slots(preview["affected_slot_ids"])
            if elapsed.get("changed"):
                saved["schedule_elapsed"] = elapsed
        except PlanningControlError as error:
            saved.setdefault("warnings", []).append(f"SCHEDULE_ELAPSED_WARNING:{error.code}")
        return {"preview": preview, "applied": True, "window": saved}

    def refresh_sources(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        window = self._window(); old = copy.deepcopy(window); health = self.check_window_health(); anchor = resolve_planning_anchor(self.context)
        if health["status"] == "reanchor_required":
            raise PlanningControlError("ROLLING_WINDOW_REANCHOR_REQUIRED")
        self._assert_unlocked(window["window_id"], "far_horizon")
        data = self.control._read(); far_horizon = far_horizon_projection(self.context, data, anchor)
        window["far_horizon"] = far_horizon; window["source_refs"] = self._window_source_refs(data, far_horizon); window["source_snapshot"] = self._source_snapshot(data); window["status"] = "needs_roll_forward" if health["status"] == "needs_roll_forward" else "active"; window.pop("status_reason", None)
        return self._save(window, "rolling_window_refreshed", old, payload)

    def refresh_far_horizon(self) -> dict[str, Any]:
        """Compatibility alias retained for the 14.2A UI."""
        return self.refresh_sources()

    def lock(self, entity_type: str, entity_id: str, field: str, reason: str = "") -> dict[str, Any]:
        if entity_type not in {"chapter_slot", "rolling_window"}:
            raise PlanningControlError("PLANNING_LOCK_CONFLICT")
        record = self.control.lock({"entity_type": entity_type, "entity_id": entity_id, "field": field, "reason": reason})
        window = self._window(); old = copy.deepcopy(window); self._refresh_slot_locks(window)
        self.control.save_rolling_window(window, event="planning_field_locked", old=old)
        return record

    def release_lock(self, lock_id: str) -> dict[str, Any]:
        record = self.control.release_lock(lock_id)
        window = self._window(); old = copy.deepcopy(window); self._refresh_slot_locks(window)
        self.control.save_rolling_window(window, event="planning_field_unlocked", old=old)
        return record

    def mark_anchor_changed(self, reason: str) -> dict[str, Any]:
        data = self.control._read(); window = data["rolling_window"]
        if not window:
            return {"changed": False, "warning": "No rolling window is materialized."}
        old = copy.deepcopy(window); health = self.check_window_health()
        status = health["status"]
        if status == "active":
            return {"changed": False, "warning": "Rolling window remains current."}
        if window.get("status") == status:
            return {"changed": False, "status": status, "warning": "Rolling window lifecycle status is already recorded."}
        window["status"] = status; window["status_reason"] = reason
        self.control.save_rolling_window(window, event="rolling_window_anchor_changed", old=old)
        return {"changed": True, "status": status, "warnings": health["warnings"]}

    def check_window_health(self) -> dict[str, Any]:
        """Read-only lifecycle check. It never materializes or changes a window."""
        data = self.control._read(); window = data["rolling_window"]
        anchor = resolve_planning_anchor(self.context)
        if not window:
            return {"materialized": False, "status": "uninitialized", "issues": [], "warnings": anchor["warnings"], "anchor": {"saved": None, "suggested": anchor}, "source_changes": []}
        issues: list[dict[str, str]] = []
        warnings = list(anchor["warnings"])
        saved = window.get("anchor", {}) if isinstance(window.get("anchor"), dict) else {}
        source_changes = self._source_changes(window, data)
        if saved.get("blueprint_hash") != anchor.get("blueprint_hash"):
            source_changes.append({"type": "source_changed", "id": "story_blueprint"})
        if window.get("project_id") != self.project_id:
            issues.append({"type": "project_mismatch", "id": str(window.get("project_id", ""))})
        if not isinstance(saved.get("next_chapter_number"), int) or int(saved.get("next_chapter_number", 0)) < 1:
            issues.append({"type": "invalid_anchor", "id": "next_chapter_number"})
        if any("missing" in str(item).lower() or "缺失" in str(item) or "无效" in str(item) or "不一致" in str(item) or "不连续" in str(item) for item in anchor["warnings"]):
            issues.append({"type": "anchor_source_inconsistent", "id": "state_or_canon"})
        if saved.get("last_canon_version_id") and saved.get("last_canon_version_id") != anchor.get("last_canon_version_id") and int(saved.get("next_chapter_number", 0) or 0) == int(anchor["next_chapter_number"]):
            issues.append({"type": "canon_version_changed", "id": str(anchor.get("last_canon_version_id", ""))})
        issues.extend(self._missing_reference_issues(window, data))
        if issues:
            status = "reanchor_required"
        elif int(anchor["next_chapter_number"]) > int(saved.get("next_chapter_number", 0) or 0):
            status = "needs_roll_forward"
        elif int(anchor["next_chapter_number"]) < int(saved.get("next_chapter_number", 0) or 0):
            status = "reanchor_required"
            issues.append({"type": "anchor_ahead_of_canon", "id": str(saved.get("next_chapter_number", ""))})
        elif source_changes or window.get("status") == "stale":
            status = "stale"
        else:
            status = "active"
        return {"materialized": True, "status": status, "issues": issues, "warnings": warnings, "anchor": {"saved": saved, "suggested": anchor}, "source_changes": source_changes}

    def _window(self) -> dict[str, Any]:
        window = self.control._read()["rolling_window"]
        if not window:
            raise PlanningControlError("ROLLING_WINDOW_NOT_FOUND")
        if window.get("project_id") != self.project_id:
            raise PlanningControlError("ROLLING_WINDOW_PROJECT_MISMATCH")
        return copy.deepcopy(window)

    @staticmethod
    def _range(start: int, size: int) -> list[int]: return list(range(start, start + size))
    @staticmethod
    def _all_slots(window: dict[str, Any]) -> list[dict[str, Any]]: return list(window.get("near_slots", [])) + list(window.get("mid_slots", []))
    def _slot(self, window: dict[str, Any], slot_id: str) -> dict[str, Any]:
        value = next((item for item in self._all_slots(window) if item.get("slot_id") == slot_id), None)
        if not value: raise PlanningControlError("CHAPTER_SLOT_NOT_FOUND")
        return value
    def _slot_by_chapter(self, window: dict[str, Any], chapter: int, exclude: str = "") -> dict[str, Any] | None:
        return next((item for item in self._all_slots(window) if int(item.get("planned_chapter_number", 0)) == chapter and item.get("slot_id") != exclude), None)
    def _horizon(self, window: dict[str, Any], chapter: int) -> str | None:
        anchor, near = int(window["anchor"]["next_chapter_number"]), int(window["configuration"]["near_horizon_size"])
        mid = int(window["configuration"]["mid_horizon_size"])
        return "near" if anchor <= chapter < anchor + near else "mid" if anchor + near <= chapter < anchor + near + mid else None
    def _validate_slot(self, slot: dict[str, Any]) -> None:
        try: validate_slot(slot)
        except ValueError as exc: raise PlanningControlError(str(exc)) from exc
    def _sort_slots(self, window: dict[str, Any]) -> None:
        for key in ("near_slots", "mid_slots"): window[key] = sorted(window.get(key, []), key=lambda item: int(item["planned_chapter_number"]))
    def _reclassify(self, window: dict[str, Any], anchor: int) -> None:
        slots = self._all_slots(window); elapsed = list(window.get("elapsed_slots", [])); window["near_slots"], window["mid_slots"] = [], []
        for slot in slots:
            if int(slot["planned_chapter_number"]) < anchor:
                slot["status"] = "elapsed"
                if not any(item.get("slot_id") == slot.get("slot_id") for item in elapsed): elapsed.append(slot)
                continue
            horizon = self._horizon(window, int(slot["planned_chapter_number"]))
            if horizon:
                slot["horizon"] = horizon
                if horizon == "mid" and slot.get("detail_level") == "detailed": slot["detail_level"] = "outline"
                window[f"{horizon}_slots"].append(slot)
        window["elapsed_slots"] = sorted(elapsed, key=lambda item: int(item["planned_chapter_number"]))
        self._sort_slots(window)
    def _ensure_window_capacity(self, window: dict[str, Any]) -> None:
        anchor = int(window["anchor"]["next_chapter_number"]); near, mid = int(window["configuration"]["near_horizon_size"]), int(window["configuration"]["mid_horizon_size"])
        for chapter in self._range(anchor, near + mid):
            if not self._slot_by_chapter(window, chapter):
                horizon = self._horizon(window, chapter); window[f"{horizon}_slots"].append(make_slot(self.project_id, chapter, horizon))
        self._sort_slots(window)
    def _is_locked(self, entity_id: str, field: str) -> bool:
        locks = self.control._read()["locks"]
        return any(item.get("active") and item.get("entity_type") in {"chapter_slot", "rolling_window"} and item.get("entity_id") == entity_id and item.get("field") in {"*", field} for item in locks)
    def _assert_unlocked(self, entity_id: str, field: str) -> None:
        if self._is_locked(entity_id, field): raise PlanningControlError("PLANNING_LOCK_CONFLICT")
    def _refresh_slot_locks(self, window: dict[str, Any]) -> None:
        for slot in self._all_slots(window): slot["locked"] = self._is_locked(slot["slot_id"], "*")

    @staticmethod
    def _stable_source_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: RollingWindowService._stable_source_value(item) for key, item in value.items() if key not in {"version_id", "created_at", "updated_at", "author_confirmed_at"}}
        if isinstance(value, list):
            return [RollingWindowService._stable_source_value(item) for item in value]
        return value

    def _source_snapshot(self, data: dict[str, Any]) -> dict[str, str]:
        return {key: content_hash(self._stable_source_value(data.get(key))) for key in ("strategy", "milestones", "volume_contracts", "phase_contracts")}

    def _source_changes(self, window: dict[str, Any], data: dict[str, Any]) -> list[dict[str, str]]:
        previous = window.get("source_snapshot") if isinstance(window.get("source_snapshot"), dict) else {}
        current = self._source_snapshot(data)
        if not previous:
            return [{"type": "source_snapshot_missing", "id": "rolling_window"}]
        return [{"type": "source_changed", "id": key} for key, value in current.items() if previous.get(key) != value]

    @staticmethod
    def _window_source_refs(data: dict[str, Any], far_horizon: dict[str, Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        strategy = data.get("strategy")
        if isinstance(strategy, dict): refs.extend(item for item in strategy.get("source_refs", []) if isinstance(item, dict))
        refs.extend(item for item in far_horizon.get("source_refs", []) if isinstance(item, dict))
        return refs

    def _missing_reference_issues(self, window: dict[str, Any], data: dict[str, Any]) -> list[dict[str, str]]:
        known = {
            "milestone": {str(item.get("milestone_id", item.get("id", ""))) for item in data.get("milestones", []) if isinstance(item, dict)},
            "phase_contract": {str(item.get("contract_id", item.get("id", ""))) for item in data.get("phase_contracts", []) if isinstance(item, dict)},
            "volume_contract": {str(item.get("contract_id", item.get("id", ""))) for item in data.get("volume_contracts", []) if isinstance(item, dict)},
        }
        issues: list[dict[str, str]] = []
        for slot in self._all_slots(window):
            slot_id = str(slot.get("slot_id", ""))
            for reference in slot.get("milestone_refs", []) if isinstance(slot.get("milestone_refs"), list) else []:
                ref_id = str(reference.get("id", reference.get("milestone_id", "")) if isinstance(reference, dict) else reference)
                if ref_id and ref_id not in known["milestone"]: issues.append({"type": "missing_reference", "id": f"milestone:{ref_id}:slot:{slot_id}"})
            for field, kind in (("phase_contract_ref", "phase_contract"), ("volume_contract_ref", "volume_contract")):
                reference = slot.get(field)
                ref_id = str(reference.get("id", reference.get("contract_id", "")) if isinstance(reference, dict) else reference or "")
                if ref_id and ref_id not in known[kind]: issues.append({"type": "missing_reference", "id": f"{kind}:{ref_id}:slot:{slot_id}"})
        return issues

    def _reanchor_preview(self, window: dict[str, Any], anchor: dict[str, Any], target: int) -> dict[str, Any]:
        impacted = [slot for slot in self._all_slots(window) if int(slot.get("planned_chapter_number", 0) or 0) < target]
        return {"old_anchor": window.get("anchor", {}).get("next_chapter_number"), "suggested_anchor": anchor.get("next_chapter_number"), "requested_anchor": target, "affected_slot_ids": [str(slot.get("slot_id", "")) for slot in impacted], "locked_slot_ids": [str(slot.get("slot_id", "")) for slot in impacted if self._is_locked(str(slot.get("slot_id", "")), "*")]}

    def _effective_status(self, window: dict[str, Any], anchor: dict[str, Any]) -> tuple[str, list[str]]:
        warnings: list[str] = []
        if window.get("status") in {"archived", "invalid"}: return str(window["status"]), warnings
        saved = window.get("anchor", {})
        if int(anchor["next_chapter_number"]) > int(saved.get("next_chapter_number", 0) or 0): return "needs_roll_forward", warnings
        if any(saved.get(key) != anchor.get(key) for key in ("blueprint_hash", "planning_control_version_id")):
            return "stale", warnings
        return str(window.get("status", "active")), warnings
    def _roll_preview(self, window: dict[str, Any], anchor: dict[str, Any]) -> dict[str, Any]:
        target = int(anchor["next_chapter_number"])
        elapsed = [item["slot_id"] for item in self._all_slots(window) if int(item["planned_chapter_number"]) < target]
        locked = [slot_id for slot_id in elapsed if self._is_locked(slot_id, "*")]
        near = int(window["configuration"]["near_horizon_size"])
        mid = int(window["configuration"]["mid_horizon_size"])
        existing = {int(item["planned_chapter_number"]) for item in self._all_slots(window)}
        new_slots = [chapter for chapter in self._range(target, near + mid) if chapter not in existing]
        return {"old_anchor": window["anchor"].get("next_chapter_number"), "new_anchor": target, "elapsed_slots": elapsed, "entering_near": self._range(target, near), "new_empty_slots": new_slots, "from_next_chapter_number": window["anchor"].get("next_chapter_number"), "to_next_chapter_number": target, "elapsed_slot_ids": elapsed, "locked_conflicts": locked, "near_after": self._range(target, near), "mid_added_after": target + near + mid - 1}
