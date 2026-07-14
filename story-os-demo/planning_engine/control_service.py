"""Author-operated, project-isolated planning control persistence."""
from __future__ import annotations

import copy
from typing import Any

from core.project_context import ProjectContext, get_project_context
from system.data_store import DataStore, DataWriteError

from .conflict_service import ConflictService
from .models import MILESTONE_STATUSES, MILESTONE_TYPES, base_entity, content_hash, new_id, now
from .source_service import SourceService
from .version_service import VersionService


class PlanningControlError(RuntimeError):
    def __init__(self, code: str, message: str | None = None, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(message or code)


class PlanningControlService:
    """The Stage 14.1 control layer; it never writes blueprint, state, or chapter plans."""

    COLLECTIONS = {"milestones": ("milestone_id", "narrative_milestone"), "volume_contracts": ("contract_id", "volume_contract"), "phase_contracts": ("contract_id", "phase_contract")}

    def __init__(self, context: ProjectContext | None = None) -> None:
        self.context = context or get_project_context()
        self.store = DataStore(self.context)
        self.project_id = self.context.root.resolve().as_posix()
        self.sources = SourceService(self.context)
        self.versions = VersionService(self.context)

    def overview(self) -> dict[str, Any]:
        data = self._read()
        projection = self.sources.blueprint_projection()
        return {"materialized": self.context.planning_control_dir.exists(), "saved_strategy": data["strategy"], "suggested_projection": projection, "authority_order": self.sources.authority_order(), "milestones": data["milestones"], "volume_contracts": data["volume_contracts"], "phase_contracts": data["phase_contracts"], "rolling_window": data["rolling_window"], "dependencies": data["dependencies"], "locks": data["locks"], "conflicts": data["conflicts"], "versions": self.versions.list()}

    def get_strategy(self) -> dict[str, Any] | None:
        return self._read()["strategy"]

    def save_strategy(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        previous = copy.deepcopy(data)
        old = data["strategy"]
        strategy = copy.deepcopy(old) if old else base_entity(self.project_id, new_id("strategy"))
        strategy["strategy_id"] = strategy.get("strategy_id") or strategy["id"]
        strategy.update(copy.deepcopy(payload))
        strategy.update({"schema_version": "1.0", "project_id": self.project_id, "id": strategy["strategy_id"], "created_by": "user", "updated_at": now(), "author_confirmed_at": now()})
        strategy.setdefault("target_length", {"target_word_count": None, "target_chapter_count": None, "target_volume_count": None})
        for key in ("story_promise", "core_question", "central_conflict", "protagonist_end_state", "ending_direction"):
            strategy.setdefault(key, "")
        for key in ("reader_experience_contract", "non_negotiable_payoffs", "prohibited_directions", "long_term_rules", "locked_fields", "source_refs"):
            strategy.setdefault(key, [])
        self._validate_locked_change("story_strategy", strategy["strategy_id"], old, strategy, data["locks"])
        data["strategy"] = strategy
        self._write(data, "strategy_created" if old is None else "strategy_updated", "story_strategy", strategy["strategy_id"], old, strategy, previous)
        return strategy

    def list(self, collection: str) -> list[dict[str, Any]]:
        self._collection(collection)
        return self._read()[collection]

    def get(self, collection: str, entity_id: str) -> dict[str, Any] | None:
        key, _ = self._collection(collection)
        return next((item for item in self._read()[collection] if item.get(key) == entity_id), None)

    def create(self, collection: str, payload: dict[str, Any]) -> dict[str, Any]:
        key, entity_type = self._collection(collection)
        data = self._read()
        previous = copy.deepcopy(data)
        item = base_entity(self.project_id, new_id(collection.rstrip("s")))
        item[key] = item["id"]
        item.update(copy.deepcopy(payload))
        item.update({"schema_version": "1.0", "project_id": self.project_id, "id": item[key], "created_by": "user", "updated_at": now(), "author_confirmed_at": now()})
        self._validate_entity(collection, item)
        data[collection].append(item)
        self._write(data, "milestone_created" if collection == "milestones" else f"{entity_type}_saved", entity_type, item[key], None, item, previous)
        return item

    def update(self, collection: str, entity_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        key, entity_type = self._collection(collection)
        data = self._read()
        previous = copy.deepcopy(data)
        index = next((i for i, item in enumerate(data[collection]) if item.get(key) == entity_id), None)
        if index is None:
            raise PlanningControlError(self._not_found(collection))
        old = copy.deepcopy(data[collection][index])
        item = copy.deepcopy(old)
        item.update(copy.deepcopy(payload))
        item[key] = entity_id
        item["id"] = entity_id
        item["updated_at"] = now()
        self._validate_locked_change(entity_type, entity_id, old, item, data["locks"])
        self._validate_entity(collection, item)
        data[collection][index] = item
        event = "milestone_transitioned" if collection == "milestones" and old.get("status") != item.get("status") else f"{entity_type}_saved"
        self._write(data, event, entity_type, entity_id, old, item, previous)
        return item

    def delete_milestone(self, milestone_id: str) -> dict[str, Any]:
        return self.update("milestones", milestone_id, {"status": "cancelled"})

    def lock(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        previous = copy.deepcopy(data)
        entity_type, entity_id, field = str(payload.get("entity_type", "")), str(payload.get("entity_id", "")), str(payload.get("field", ""))
        if not entity_type or not entity_id or not field:
            raise PlanningControlError("PLANNING_LOCK_CONFLICT", "entity_type, entity_id, and field are required")
        if any(lock.get("active") and lock.get("entity_type") == entity_type and lock.get("entity_id") == entity_id and lock.get("field") == field for lock in data["locks"]):
            raise PlanningControlError("PLANNING_LOCK_CONFLICT")
        lock = base_entity(self.project_id, new_id("lock"))
        lock.update({"lock_id": lock["id"], "entity_type": entity_type, "entity_id": entity_id, "field": field, "reason": str(payload.get("reason", "")), "locked_by": "user", "locked_at": now(), "active": True})
        data["locks"].append(lock)
        self._write(data, "planning_field_locked", entity_type, entity_id, None, lock, previous)
        return lock

    def release_lock(self, lock_id: str) -> dict[str, Any]:
        data = self._read()
        previous = copy.deepcopy(data)
        lock = next((item for item in data["locks"] if item.get("lock_id") == lock_id), None)
        if not lock:
            raise PlanningControlError("PLANNING_LOCK_NOT_FOUND")
        old = copy.deepcopy(lock)
        lock["active"], lock["released_at"], lock["updated_at"] = False, now(), now()
        self._write(data, "planning_field_unlocked", lock["entity_type"], lock["entity_id"], old, lock, previous)
        return lock

    def scan_conflicts(self) -> list[dict[str, Any]]:
        data = self._read()
        previous = copy.deepcopy(data)
        findings = ConflictService().scan(self.project_id, data["strategy"], data["milestones"], data["volume_contracts"], data["phase_contracts"], data["locks"], self.sources)
        open_fingerprints = {item.get("fingerprint") for item in data["conflicts"] if item.get("status") == "open"}
        created = [item for item in findings if item.get("fingerprint") not in open_fingerprints]
        if created:
            data["conflicts"].extend(created)
            self._write(data, "planning_conflicts_scanned", "planning_conflict", "scan", None, created, previous)
        return data["conflicts"] + ([] if created else [])

    def resolve_conflict(self, conflict_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        previous = copy.deepcopy(data)
        conflict = next((item for item in data["conflicts"] if item.get("conflict_id") == conflict_id), None)
        if not conflict:
            raise PlanningControlError("PLANNING_SOURCE_CONFLICT")
        action = str(payload.get("action", ""))
        if action not in {"keep_control_value", "adopt_blueprint_value", "manual_value", "rebind_source", "ignore"}:
            raise PlanningControlError("PLANNING_SOURCE_CONFLICT", "Unsupported conflict resolution")
        old = copy.deepcopy(conflict)
        if action == "adopt_blueprint_value" and conflict.get("entity_type") == "story_strategy" and data["strategy"]:
            field = conflict.get("field")
            if field:
                blueprint_value = (conflict.get("sources") or [{}, {}])[1].get("value")
                self._validate_locked_change("story_strategy", data["strategy"]["strategy_id"], data["strategy"], {**data["strategy"], field: blueprint_value}, data["locks"])
                data["strategy"][field] = blueprint_value
        if action == "manual_value" and conflict.get("entity_type") == "story_strategy" and data["strategy"]:
            field = conflict.get("field")
            self._validate_locked_change("story_strategy", data["strategy"]["strategy_id"], data["strategy"], {**data["strategy"], field: payload.get("value")}, data["locks"])
            data["strategy"][field] = payload.get("value")
        conflict.update({"status": "resolved" if action != "ignore" else "ignored", "resolution": {"action": action, "note": payload.get("note", "")}, "resolved_at": now(), "updated_at": now()})
        self._write(data, "planning_conflict_resolved", "planning_conflict", conflict_id, old, conflict, previous)
        return conflict

    def list_versions(self) -> list[dict[str, Any]]:
        return self.versions.list()

    def get_version(self, version_id: str) -> dict[str, Any] | None:
        return self.versions.get(version_id)

    def restore_version(self, version_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        record = self.versions.get(version_id)
        if not record:
            raise PlanningControlError("PLANNING_VERSION_NOT_FOUND")
        if record.get("project_id") != self.project_id:
            raise PlanningControlError("PLANNING_VERSION_PROJECT_MISMATCH")
        current = self._read()
        current_window = current.get("rolling_window") or {}
        expected = payload.get("expected_window_revision")
        if expected is not None and int(expected) != int(current_window.get("window_revision", 0) or 0):
            raise PlanningControlError("ROLLING_WINDOW_REVISION_CONFLICT", "滚动规划窗口已被其他操作更新，请刷新后重试。", {"expected_revision": int(expected), "actual_revision": int(current_window.get("window_revision", 0) or 0)})
        operation_id = str(payload.get("operation_id", "") or "")
        replay = self.get_rolling_operation(operation_id, "rolling_window_restore_completed")
        if replay:
            return {"overview": self.overview(), "replayed": True, "window": copy.deepcopy(replay.get("result_window") or {})}
        restored = copy.deepcopy(record.get("snapshot", {}))
        for key, default in {"strategy": None, "milestones": [], "volume_contracts": [], "phase_contracts": [], "rolling_window": None, "dependencies": None, "locks": [], "conflicts": [], "metadata": {}}.items():
            restored.setdefault(key, default)
        self._validate_restore_locks(current, restored)
        if isinstance(restored.get("rolling_window"), dict):
            # A restore is a new operation: never move the optimistic revision backward.
            restored["rolling_window"]["window_revision"] = int(current_window.get("window_revision", 0) or 0)
        self._write(restored, "planning_control_restored", "planning_control", version_id, current, restored, current)
        if isinstance(restored.get("rolling_window"), dict):
            from .rolling_service import RollingWindowService
            rolling = RollingWindowService(self.context)
            window = rolling._window(); old = copy.deepcopy(window)
            window["status"] = rolling.check_window_health()["status"]
            saved = self.save_rolling_window(window, event="rolling_window_restore_completed", old=old, expected_window_revision=int(current_window.get("window_revision", 0) or 0), operation_id=operation_id, reason="planning_control_restore")
            return {"overview": self.overview(), "window": saved}
        return {"overview": self.overview(), "window": None}

    def save_rolling_window(
        self,
        window: dict[str, Any],
        *,
        event: str,
        old: dict[str, Any] | None = None,
        expected_window_revision: int | None = None,
        operation_id: str = "",
        affected_slot_ids: list[str] | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """Commit one complete rolling-window state with optimistic concurrency.

        The window file itself is atomically replaced by DataStore.  Its version
        snapshot is created before replacement; a metadata/audit write failure is
        intentionally non-fatal and reported on the returned window.
        """
        data = self._read()
        current = data.get("rolling_window")
        metadata = copy.deepcopy(data.get("metadata", {}))
        operations = metadata.get("rolling_operations", []) if isinstance(metadata.get("rolling_operations"), list) else []
        if operation_id:
            replay = next((item for item in operations if item.get("operation_id") == operation_id and item.get("operation_type") == event), None)
            if replay:
                result = copy.deepcopy(replay.get("result_window") or current or window)
                result["replayed"] = True
                return result
        actual_revision = int((current or {}).get("window_revision", 0) or 0)
        if expected_window_revision is not None and int(expected_window_revision) != actual_revision:
            raise PlanningControlError(
                "ROLLING_WINDOW_REVISION_CONFLICT",
                "滚动规划窗口已被其他操作更新，请刷新后重试。",
                {"expected_revision": int(expected_window_revision), "actual_revision": actual_revision},
            )
        previous = self._snapshot(data)
        prepared = copy.deepcopy(window)
        prepared["window_revision"] = actual_revision + 1
        prepared["updated_at"] = now()
        try:
            version = self.versions.create(self.project_id, event, previous)
        except DataWriteError as exc:
            raise PlanningControlError("PLANNING_CONTROL_WRITE_FAILED", str(exc)) from exc
        prepared.setdefault("anchor", {})["planning_control_version_id"] = version["version_id"]
        try:
            self.store.write_json(self.context.rolling_window_path, prepared)
        except DataWriteError as exc:
            raise PlanningControlError("PLANNING_CONTROL_WRITE_FAILED", str(exc)) from exc
        metadata.setdefault("schema_version", "1.0")
        metadata["project_id"] = self.project_id
        metadata["updated_at"] = now()
        audit = {"event_type": event, "project_id": self.project_id, "window_id": str(prepared.get("window_id", "")), "operation_id": operation_id, "operator": "user", "window_revision_before": actual_revision, "window_revision_after": prepared["window_revision"], "planning_control_version_id": version["version_id"], "affected_slot_ids": affected_slot_ids or [], "reason": reason or event, "created_at": now()}
        metadata.setdefault("rolling_lifecycle_audit", []).append(audit)
        if operation_id:
            operations.append({"operation_id": operation_id, "operation_type": event, "window_revision_before": actual_revision, "window_revision_after": prepared["window_revision"], "result_ref": version["version_id"], "result_window": copy.deepcopy(prepared), "completed_at": now()})
            metadata["rolling_operations"] = operations[-100:]
        try:
            self.store.write_json(self.context.planning_metadata_path, metadata)
        except DataWriteError:
            prepared["audit_pending"] = True
            prepared["warnings"] = ["窗口已保存，但审计记录待恢复；请稍后检查规划控制审计。"]
        return prepared

    def save_rolling_preview(self, preview: dict[str, Any]) -> dict[str, Any]:
        """Persist a bounded preview token without changing window revision."""
        data = self._read(); metadata = copy.deepcopy(data.get("metadata", {}))
        metadata.setdefault("schema_version", "1.0"); metadata["project_id"] = self.project_id; metadata["updated_at"] = now()
        previews = metadata.get("rolling_previews", []) if isinstance(metadata.get("rolling_previews"), list) else []
        previews.append(copy.deepcopy(preview)); metadata["rolling_previews"] = previews[-100:]
        try:
            self.store.write_json(self.context.planning_metadata_path, metadata)
        except DataWriteError as exc:
            raise PlanningControlError("PLANNING_CONTROL_WRITE_FAILED", str(exc)) from exc
        return preview

    def get_rolling_preview(self, preview_id: str) -> dict[str, Any] | None:
        metadata = self._read().get("metadata", {})
        return next((copy.deepcopy(item) for item in metadata.get("rolling_previews", []) if isinstance(item, dict) and item.get("preview_id") == preview_id), None)

    def get_rolling_operation(self, operation_id: str, event: str) -> dict[str, Any] | None:
        if not operation_id:
            return None
        metadata = self._read().get("metadata", {})
        return next((copy.deepcopy(item) for item in metadata.get("rolling_operations", []) if isinstance(item, dict) and item.get("operation_id") == operation_id and item.get("operation_type") == event), None)

    def _read(self) -> dict[str, Any]:
        def collection(path: Any) -> list[dict[str, Any]]:
            return self.store.read_json(path, default=[], expected_type=list) or []
        return {"strategy": self.store.read_json(self.context.planning_strategy_path, default=None, expected_type=dict), "milestones": collection(self.context.planning_milestones_path), "volume_contracts": collection(self.context.volume_contracts_path), "phase_contracts": collection(self.context.phase_contracts_path), "rolling_window": self.store.read_json(self.context.rolling_window_path, default=None, expected_type=dict), "dependencies": self.store.read_json(self.context.planning_dependencies_path, default=None, expected_type=dict), "locks": collection(self.context.planning_locks_path), "conflicts": collection(self.context.planning_conflicts_path), "metadata": self.store.read_json(self.context.planning_metadata_path, default={}, expected_type=dict) or {}}

    def _write(self, data: dict[str, Any], event: str, entity_type: str, entity_id: str, old: Any, new: Any, previous: dict[str, Any]) -> None:
        snapshot = self._snapshot(previous)
        try:
            if isinstance(data.get("rolling_window"), dict) and event in {"strategy_created", "strategy_updated", "milestone_created", "milestone_transitioned", "volume_contract_saved", "phase_contract_saved", "planning_conflict_resolved"}:
                data["rolling_window"]["status"] = "stale"
                data["rolling_window"]["status_reason"] = event
                data["rolling_window"]["window_revision"] = int(data["rolling_window"].get("window_revision", 0) or 0) + 1
            version = self.versions.create(self.project_id, event, snapshot)
            version_id = version["version_id"]
            if isinstance(data.get("rolling_window"), dict):
                data["rolling_window"].setdefault("anchor", {})["planning_control_version_id"] = version_id
                data["rolling_window"]["updated_at"] = now()
            for value in [data.get("strategy")] + data["milestones"] + data["volume_contracts"] + data["phase_contracts"] + data["locks"] + data["conflicts"]:
                if isinstance(value, dict):
                    value["version_id"] = version_id
            metadata = copy.deepcopy(data.get("metadata", {}))
            metadata.setdefault("schema_version", "1.0")
            metadata["project_id"] = self.project_id
            metadata["updated_at"] = now()
            metadata.setdefault("audit", []).append({"event": event, "project_id": self.project_id, "operator": "user", "entity_type": entity_type, "entity_id": entity_id, "old_value_hash": content_hash(old), "new_value_hash": content_hash(new), "created_at": now(), "reason": event})
            self.store.write_json(self.context.planning_strategy_path, data.get("strategy"))
            self.store.write_json(self.context.planning_milestones_path, data["milestones"])
            self.store.write_json(self.context.volume_contracts_path, data["volume_contracts"])
            self.store.write_json(self.context.phase_contracts_path, data["phase_contracts"])
            if data["rolling_window"] is not None or self.store.exists(self.context.rolling_window_path):
                self.store.write_json(self.context.rolling_window_path, data["rolling_window"])
            if data.get("dependencies") is not None or self.store.exists(self.context.planning_dependencies_path):
                self.store.write_json(self.context.planning_dependencies_path, data.get("dependencies"))
            self.store.write_json(self.context.planning_locks_path, data["locks"])
            self.store.write_json(self.context.planning_conflicts_path, data["conflicts"])
            self.store.write_json(self.context.planning_metadata_path, metadata)
        except DataWriteError as exc:
            raise PlanningControlError("PLANNING_CONTROL_WRITE_FAILED", str(exc)) from exc

    @staticmethod
    def _snapshot(data: dict[str, Any]) -> dict[str, Any]:
        return {key: copy.deepcopy(data.get(key)) for key in ("strategy", "milestones", "volume_contracts", "phase_contracts", "rolling_window", "dependencies", "locks", "conflicts", "metadata")}

    def _collection(self, collection: str) -> tuple[str, str]:
        if collection not in self.COLLECTIONS:
            raise PlanningControlError("PLANNING_CONTROL_NOT_FOUND")
        return self.COLLECTIONS[collection]

    @staticmethod
    def _not_found(collection: str) -> str:
        return {"milestones": "MILESTONE_NOT_FOUND", "volume_contracts": "VOLUME_CONTRACT_NOT_FOUND", "phase_contracts": "PHASE_CONTRACT_NOT_FOUND"}[collection]

    def _validate_entity(self, collection: str, item: dict[str, Any]) -> None:
        if collection == "milestones":
            item.setdefault("status", "planned")
            item.setdefault("milestone_type", "plot")
            item.setdefault("target_scope", {"volume_ref": None, "phase_ref": None, "target_chapter_min": None, "target_chapter_max": None})
            item.setdefault("prerequisite_refs", []); item.setdefault("related_plot_thread_refs", []); item.setdefault("related_character_refs", []); item.setdefault("related_foreshadow_refs", []); item.setdefault("payoff_requirements", []); item.setdefault("locked", False); item.setdefault("source_refs", [])
            if item["milestone_type"] not in MILESTONE_TYPES or item["status"] not in MILESTONE_STATUSES:
                raise PlanningControlError("MILESTONE_STATUS_INVALID")
            scope = item["target_scope"]
            low, high = scope.get("target_chapter_min"), scope.get("target_chapter_max")
            if low is not None and high is not None and int(low) > int(high):
                raise PlanningControlError("MILESTONE_STATUS_INVALID", "target chapter range is invalid")
        else:
            item.setdefault("source_refs", []); item.setdefault("locked_fields", []); item.setdefault("chapter_budget", {"min": None, "target": None, "max": None})
            if collection == "volume_contracts":
                for key, default in {"volume_ref": {}, "opening_state": "", "closing_state": "", "primary_goal": "", "central_conflict": "", "major_payoffs": [], "required_milestone_ids": [], "thread_requirements": [], "character_arc_requirements": [], "foreshadowing_requirements": [], "world_revelations": [], "climax_contract": "", "reader_promise": ""}.items():
                    item.setdefault(key, default)
            else:
                for key, default in {"phase_ref": {}, "entry_conditions": [], "exit_conditions": [], "primary_goal": "", "central_conflict": "", "required_state_changes": [], "plot_thread_requirements": [], "character_change_requirements": [], "required_turning_points": [], "payoff_requirements": [], "ending_hook": ""}.items():
                    item.setdefault(key, default)
            budget = item["chapter_budget"]
            if budget.get("min") is not None and budget.get("max") is not None and int(budget["min"]) > int(budget["max"]):
                raise PlanningControlError("PLANNING_CONTROL_NOT_FOUND", "chapter budget is invalid")
            reference = item.get("volume_ref" if collection == "volume_contracts" else "phase_ref", {})
            if reference and not isinstance(reference, dict):
                raise PlanningControlError("PLANNING_SOURCE_NOT_FOUND")

    @staticmethod
    def _validate_locked_change(entity_type: str, entity_id: str, old: dict[str, Any] | None, new: dict[str, Any], locks: list[dict[str, Any]]) -> None:
        if not old:
            return
        for lock in locks:
            if not lock.get("active") or lock.get("entity_type") != entity_type or lock.get("entity_id") != entity_id:
                continue
            field = lock.get("field")
            if field == "*" or old.get(field) != new.get(field):
                raise PlanningControlError("PLANNING_LOCK_CONFLICT")

    def _validate_restore_locks(self, current: dict[str, Any], restored: dict[str, Any]) -> None:
        maps = {"story_strategy": (current.get("strategy"), restored.get("strategy"), "strategy_id"), "narrative_milestone": (current.get("milestones", []), restored.get("milestones", []), "milestone_id"), "volume_contract": (current.get("volume_contracts", []), restored.get("volume_contracts", []), "contract_id"), "phase_contract": (current.get("phase_contracts", []), restored.get("phase_contracts", []), "contract_id")}
        for lock in current.get("locks", []):
            if not lock.get("active") or lock.get("entity_type") not in maps:
                continue
            before, after, key = maps[lock["entity_type"]]
            before_item = before if isinstance(before, dict) else next((item for item in before if item.get(key) == lock.get("entity_id")), None)
            after_item = after if isinstance(after, dict) else next((item for item in after if item.get(key) == lock.get("entity_id")), None)
            field = lock.get("field")
            if before_item and (not after_item or field == "*" or before_item.get(field) != after_item.get(field)):
                raise PlanningControlError("PLANNING_VERSION_RESTORE_CONFLICT")
        for lock in current.get("locks", []):
            if not lock.get("active") or lock.get("entity_type") not in {"planning_dependency", "custom_planning_node"}:
                continue
            collection = "dependencies" if lock["entity_type"] == "planning_dependency" else "custom_nodes"
            before_items = (current.get("dependencies") or {}).get(collection, [])
            after_items = (restored.get("dependencies") or {}).get(collection, [])
            before_item = next((item for item in before_items if item.get("dependency_id", item.get("node_id")) == lock.get("entity_id")), None)
            after_item = next((item for item in after_items if item.get("dependency_id", item.get("node_id")) == lock.get("entity_id")), None)
            if before_item and (not after_item or lock.get("field") == "*" or before_item.get(lock.get("field")) != after_item.get(lock.get("field"))):
                raise PlanningControlError("PLANNING_VERSION_RESTORE_CONFLICT")
        for lock in current.get("locks", []):
            if not lock.get("active") or lock.get("entity_type") not in {"rolling_window", "chapter_slot"}:
                continue
            field = lock.get("field")
            if lock["entity_type"] == "rolling_window":
                before_item, after_item = current.get("rolling_window"), restored.get("rolling_window")
            else:
                before_item = self._rolling_slot(current.get("rolling_window"), lock.get("entity_id"))
                after_item = self._rolling_slot(restored.get("rolling_window"), lock.get("entity_id"))
            if before_item and (not after_item or field == "*" or before_item.get(field) != after_item.get(field)):
                raise PlanningControlError("PLANNING_VERSION_RESTORE_CONFLICT")

    @staticmethod
    def _rolling_slot(window: dict[str, Any] | None, slot_id: str | None) -> dict[str, Any] | None:
        if not isinstance(window, dict):
            return None
        for key in ("near_slots", "mid_slots", "elapsed_slots"):
            for item in window.get(key, []):
                if isinstance(item, dict) and item.get("slot_id") == slot_id:
                    return item
        return None
