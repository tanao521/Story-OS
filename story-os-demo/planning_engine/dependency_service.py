"""Author-operated planning dependency graph.  It never schedules or mutates story sources."""
from __future__ import annotations

import copy
import re
from typing import Any

from core.project_context import ProjectContext, get_project_context
from system.data_store import DataWriteError

from .control_service import PlanningControlError, PlanningControlService
from .dependency_graph import PREREQUISITE_TYPES, adjacency, cycle_for_edge, first_cycle, mutual_blocks, node_key
from .models import base_entity, new_id, now

NODE_TYPES = {
    "story_strategy", "milestone", "volume_contract", "phase_contract", "chapter_slot",
    "blueprint_phase", "blueprint_foreshadow", "structured_plot_thread",
    "structured_character_arc", "custom_planning_node",
}
DEPENDENCY_TYPES = {"requires", "precedes", "enables", "blocks", "reveals", "resolves", "pays_off", "contradicts"}
DEPENDENCY_STRENGTHS = {"hard", "soft", "advisory"}
DEPENDENCY_STATUSES = {"active", "disabled", "cancelled", "invalid"}
CUSTOM_NODE_STATUSES = {"planned", "cancelled"}


class PlanningDependencyService:
    """Small persistent graph with lazy materialization and project-local revisions."""

    def __init__(self, context: ProjectContext | None = None) -> None:
        self.context = context or get_project_context()
        self.control = PlanningControlService(self.context)
        self.store = self.control.store
        self.project_id = self.context.root.resolve().as_posix()

    def _empty(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "project_id": self.project_id, "dependency_revision": 0, "dependencies": [], "custom_nodes": [], "operations": [], "audit": []}

    def _document(self) -> dict[str, Any]:
        document = self.store.read_json(self.context.planning_dependencies_path, default=None, expected_type=dict)
        if not isinstance(document, dict):
            return self._empty()
        if document.get("project_id") not in (None, self.project_id):
            return self._empty()
        result = copy.deepcopy(document)
        result.setdefault("schema_version", "1.0"); result["project_id"] = self.project_id
        result.setdefault("dependency_revision", 0); result.setdefault("dependencies", []); result.setdefault("custom_nodes", [])
        result.setdefault("operations", []); result.setdefault("audit", [])
        return result

    @staticmethod
    def _int(value: Any, code: str = "PLANNING_DEPENDENCY_REVISION_CONFLICT") -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise PlanningControlError(code) from exc

    def _assert_revision(self, document: dict[str, Any], payload: dict[str, Any]) -> None:
        expected = self._int(payload.get("expected_dependency_revision"))
        actual = int(document.get("dependency_revision", 0) or 0)
        if expected is not None and expected != actual:
            raise PlanningControlError("PLANNING_DEPENDENCY_REVISION_CONFLICT", details={"expected_revision": expected, "actual_revision": actual})

    def _replay(self, document: dict[str, Any], payload: dict[str, Any], operation: str) -> dict[str, Any] | None:
        operation_id = str(payload.get("operation_id", "") or "")
        if not operation_id:
            return None
        item = next((row for row in document["operations"] if row.get("operation_id") == operation_id and row.get("operation") == operation), None)
        return copy.deepcopy(item.get("result")) if item else None

    def _save(self, document: dict[str, Any], *, previous: dict[str, Any], event: str, entity_type: str, entity_id: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        actual = int(previous.get("dependency_revision", 0) or 0)
        document["dependency_revision"] = actual + 1
        document["updated_at"] = now()
        snapshot_data = self.control._read()
        snapshot_data["dependencies"] = copy.deepcopy(previous) if self.store.exists(self.context.planning_dependencies_path) else None
        try:
            version = self.control.versions.create(self.project_id, event, self.control._snapshot(snapshot_data))
            document["version_id"] = version["version_id"]
            document["audit"].append({"event": event, "entity_type": entity_type, "entity_id": entity_id, "project_id": self.project_id, "dependency_revision_before": actual, "dependency_revision_after": document["dependency_revision"], "planning_control_version_id": version["version_id"], "created_at": now()})
            operation_id = str(payload.get("operation_id", "") or "")
            if operation_id:
                stored_result = copy.deepcopy(result); stored_result["dependency_revision"] = document["dependency_revision"]
                document["operations"].append({"operation_id": operation_id, "operation": event, "result": stored_result, "dependency_revision": document["dependency_revision"], "completed_at": now()})
                document["operations"] = document["operations"][-100:]
            self.store.write_json(self.context.planning_dependencies_path, document)
        except DataWriteError as exc:
            raise PlanningControlError("PLANNING_CONTROL_WRITE_FAILED", str(exc)) from exc
        saved = copy.deepcopy(result)
        saved["dependency_revision"] = document["dependency_revision"]
        return saved

    @staticmethod
    def _source_refs(value: Any) -> list[dict[str, Any]]:
        if value in (None, ""):
            return []
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise PlanningControlError("PLANNING_DEPENDENCY_INVALID_NODE")
        for item in value:
            source_path = str(item.get("source_path", ""))
            if source_path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", source_path):
                raise PlanningControlError("PLANNING_DEPENDENCY_INVALID_NODE")
        return copy.deepcopy(value)

    def _assert_unlocked(self, entity_type: str, entity_id: str, fields: set[str]) -> None:
        for lock in self.control._read().get("locks", []):
            if lock.get("active") and lock.get("entity_type") == entity_type and lock.get("entity_id") == entity_id and (lock.get("field") == "*" or lock.get("field") in fields):
                raise PlanningControlError("PLANNING_LOCK_CONFLICT")

    def _node(self, node_type: str, node_id: str, document: dict[str, Any] | None = None) -> dict[str, Any] | None:
        document = document or self._document()
        data = self.control._read()
        if node_type == "story_strategy":
            item = data.get("strategy")
            if item and str(item.get("strategy_id")) == node_id:
                return self._summary(node_type, node_id, item, "active")
        collections = {"milestone": (data.get("milestones", []), "milestone_id"), "volume_contract": (data.get("volume_contracts", []), "contract_id"), "phase_contract": (data.get("phase_contracts", []), "contract_id")}
        if node_type in collections:
            items, identity = collections[node_type]
            item = next((row for row in items if str(row.get(identity)) == node_id), None)
            if item:
                return self._summary(node_type, node_id, item, str(item.get("status", "planned")))
        if node_type == "chapter_slot":
            window = data.get("rolling_window") or {}
            for key in ("near_slots", "mid_slots", "elapsed_slots"):
                item = next((row for row in window.get(key, []) if str(row.get("slot_id")) == node_id), None)
                if item:
                    return self._summary(node_type, node_id, item, str(item.get("status", "planned")))
        blueprint = self.control.sources.blueprint_projection()
        blueprint_lists = {
            "blueprint_phase": (blueprint.get("story_phases", []), ("phase_id", "id")),
            "blueprint_foreshadow": ((self.store.read_json(self.context.data_dir / "story_blueprint.json", default={}, expected_type=dict) or {}).get("foreshadowing", []), ("foreshadow_id", "id")),
            "structured_plot_thread": ((self.store.read_json(self.context.data_dir / "story_blueprint.json", default={}, expected_type=dict) or {}).get("plot_threads", []), ("thread_id", "id")),
            "structured_character_arc": ((self.store.read_json(self.context.data_dir / "story_blueprint.json", default={}, expected_type=dict) or {}).get("character_arcs", []), ("arc_id", "id")),
        }
        if node_type in blueprint_lists:
            items, identities = blueprint_lists[node_type]
            item = next((row for row in items if isinstance(row, dict) and any(str(row.get(key, "")) == node_id for key in identities)), None)
            if item:
                return self._summary(node_type, node_id, item, "reference")
        if node_type == "custom_planning_node":
            item = next((row for row in document["custom_nodes"] if str(row.get("node_id")) == node_id), None)
            if item:
                return self._summary(node_type, node_id, item, str(item.get("status", "planned")))
        return None

    @staticmethod
    def _summary(node_type: str, node_id: str, item: dict[str, Any], status: str) -> dict[str, Any]:
        title = item.get("title") or item.get("name") or item.get("label") or item.get("summary") or node_id
        result = {"node_type": node_type, "node_id": str(node_id), "title": str(title), "status": status}
        scope = item.get("target_scope", {}) if isinstance(item.get("target_scope"), dict) else {}
        for field in ("planned_chapter_number", "chapter_start", "chapter_end"):
            if item.get(field) is not None:
                result[field] = item[field]
        if scope.get("target_chapter_min") is not None: result["chapter_start"] = scope["target_chapter_min"]
        if scope.get("target_chapter_max") is not None: result["chapter_end"] = scope["target_chapter_max"]
        return result

    def _ref(self, value: Any, document: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise PlanningControlError("PLANNING_DEPENDENCY_INVALID_NODE")
        node_type, node_id = str(value.get("node_type", "")), str(value.get("node_id", ""))
        if node_type not in NODE_TYPES or not node_id:
            raise PlanningControlError("PLANNING_DEPENDENCY_INVALID_NODE")
        if value.get("project_id") not in (None, "", self.project_id):
            raise PlanningControlError("PLANNING_DEPENDENCY_INVALID_NODE")
        summary = self._node(node_type, node_id, document)
        if not summary:
            raise PlanningControlError("PLANNING_DEPENDENCY_SOURCE_NOT_FOUND", details={"node_type": node_type, "node_id": node_id})
        return {"node_type": node_type, "node_id": node_id, "project_id": self.project_id, "title": summary["title"]}

    @staticmethod
    def _chapter(node: dict[str, Any] | None) -> int | None:
        if not node: return None
        for field in ("planned_chapter_number", "chapter_start", "chapter_end"):
            value = node.get(field)
            if value is not None:
                try: return int(value)
                except (TypeError, ValueError): pass
        return None

    def _validate_edge(self, document: dict[str, Any], edge: dict[str, Any], *, force_with_reason: bool = False) -> list[dict[str, Any]]:
        start, end = edge["from_node"], edge["to_node"]
        if node_key(start) == node_key(end):
            raise PlanningControlError("PLANNING_DEPENDENCY_SELF_REFERENCE")
        if edge["dependency_type"] not in DEPENDENCY_TYPES or edge["strength"] not in DEPENDENCY_STRENGTHS:
            raise PlanningControlError("PLANNING_DEPENDENCY_INVALID_TYPE")
        if edge["dependency_type"] in PREREQUISITE_TYPES:
            cycle = cycle_for_edge(document["dependencies"], start, end)
            if cycle:
                raise PlanningControlError("PLANNING_DEPENDENCY_CYCLE", details={"cycle_path": cycle})
        warnings: list[dict[str, Any]] = []
        if edge["dependency_type"] == "blocks":
            candidates = document["dependencies"] + [edge]
            matches = mutual_blocks(candidates)
            if matches:
                warnings.append({"code": "PLANNING_MUTUAL_BLOCK", "pairs": matches})
        if edge["dependency_type"] == "precedes":
            before, after = self._chapter(self._node(start["node_type"], start["node_id"], document)), self._chapter(self._node(end["node_type"], end["node_id"], document))
            if before is not None and after is not None and before > after:
                detail = {"code": "PLANNING_DEPENDENCY_ORDER_CONFLICT", "from_chapter": before, "to_chapter": after}
                if edge["strength"] == "hard" and (not force_with_reason or not str(edge.get("force_reason", "")).strip()):
                    raise PlanningControlError("PLANNING_DEPENDENCY_ORDER_CONFLICT", details=detail)
                if edge["strength"] != "hard" or force_with_reason:
                    warnings.append(detail)
        return warnings

    def describe(self) -> dict[str, Any]:
        document = self._document()
        return {"materialized": self.store.exists(self.context.planning_dependencies_path), "project_id": self.project_id, "dependency_revision": int(document["dependency_revision"]), "dependencies": document["dependencies"], "custom_nodes": document["custom_nodes"], "available_nodes": self.available_nodes(document), "health": self.health(document)}

    def available_nodes(self, document: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        document = document or self._document(); data = self.control._read(); rows: list[dict[str, Any]] = []
        if data.get("strategy"): rows.append(self._summary("story_strategy", str(data["strategy"].get("strategy_id")), data["strategy"], "active"))
        for node_type, collection, identity in (("milestone", data.get("milestones", []), "milestone_id"), ("volume_contract", data.get("volume_contracts", []), "contract_id"), ("phase_contract", data.get("phase_contracts", []), "contract_id")):
            rows.extend(self._summary(node_type, str(row.get(identity)), row, str(row.get("status", "planned"))) for row in collection)
        for key in ("near_slots", "mid_slots", "elapsed_slots"):
            rows.extend(self._summary("chapter_slot", str(row.get("slot_id")), row, str(row.get("status", "planned"))) for row in (data.get("rolling_window") or {}).get(key, []))
        for node_type, values, identities in (("blueprint_phase", self.control.sources.blueprint_projection().get("story_phases", []), ("phase_id", "id")), ("blueprint_foreshadow", (self.store.read_json(self.context.data_dir / "story_blueprint.json", default={}, expected_type=dict) or {}).get("foreshadowing", []), ("foreshadow_id", "id")), ("structured_plot_thread", (self.store.read_json(self.context.data_dir / "story_blueprint.json", default={}, expected_type=dict) or {}).get("plot_threads", []), ("thread_id", "id")), ("structured_character_arc", (self.store.read_json(self.context.data_dir / "story_blueprint.json", default={}, expected_type=dict) or {}).get("character_arcs", []), ("arc_id", "id"))):
            rows.extend(self._summary(node_type, str(next((row.get(key) for key in identities if row.get(key) is not None), "")), row, "reference") for row in values if isinstance(row, dict))
        rows.extend(self._summary("custom_planning_node", str(row.get("node_id")), row, str(row.get("status", "planned"))) for row in document["custom_nodes"])
        return sorted(rows, key=lambda row: (row["node_type"], row["title"], row["node_id"]))

    def list_dependencies(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        document = self._document(); filters = filters or {}; values = document["dependencies"]
        for field in ("dependency_type", "status"):
            if filters.get(field): values = [row for row in values if row.get(field) == filters[field]]
        if filters.get("node_type") or filters.get("node_id"):
            values = [row for row in values if any((not filters.get("node_type") or point.get("node_type") == filters["node_type"]) and (not filters.get("node_id") or point.get("node_id") == filters["node_id"]) for point in (row.get("from_node", {}), row.get("to_node", {})))]
        return {"dependency_revision": document["dependency_revision"], "dependencies": copy.deepcopy(values), "available_nodes": self.available_nodes(document), "health": self.health(document)}

    def get_dependency(self, dependency_id: str) -> dict[str, Any]:
        item = next((row for row in self._document()["dependencies"] if row.get("dependency_id") == dependency_id), None)
        if not item: raise PlanningControlError("PLANNING_DEPENDENCY_NOT_FOUND")
        return copy.deepcopy(item)

    def create_dependency(self, payload: dict[str, Any]) -> dict[str, Any]:
        document = self._document(); replay = self._replay(document, payload, "planning_dependency_created")
        if replay: replay["replayed"] = True; return replay
        self._assert_revision(document, payload)
        edge = base_entity(self.project_id, new_id("dependency")); edge.update({"dependency_id": edge["id"], "from_node": self._ref(payload.get("from_node"), document), "to_node": self._ref(payload.get("to_node"), document), "dependency_type": str(payload.get("dependency_type", "requires")), "strength": str(payload.get("strength", "hard")), "description": str(payload.get("description", "")), "condition": str(payload.get("condition", "")), "status": "active", "notes": str(payload.get("notes", "")), "source_refs": self._source_refs(payload.get("source_refs", [])), "force_reason": str(payload.get("force_reason", "")), "author_confirmed_at": now()})
        if any(row.get("status") == "active" and row.get("from_node", {}).get("node_type") == edge["from_node"]["node_type"] and row.get("from_node", {}).get("node_id") == edge["from_node"]["node_id"] and row.get("to_node", {}).get("node_type") == edge["to_node"]["node_type"] and row.get("to_node", {}).get("node_id") == edge["to_node"]["node_id"] and row.get("dependency_type") == edge["dependency_type"] for row in document["dependencies"]):
            raise PlanningControlError("PLANNING_DEPENDENCY_ALREADY_EXISTS")
        warnings = self._validate_edge(document, edge, force_with_reason=bool(payload.get("force_with_reason")))
        edge["validation_warnings"] = warnings; previous = copy.deepcopy(document); document["dependencies"].append(edge)
        return self._save(document, previous=previous, event="planning_dependency_created", entity_type="planning_dependency", entity_id=edge["dependency_id"], payload=payload, result=edge)

    def update_dependency(self, dependency_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        document = self._document(); replay = self._replay(document, payload, "planning_dependency_updated")
        if replay: replay["replayed"] = True; return replay
        self._assert_revision(document, payload); index = next((i for i, row in enumerate(document["dependencies"]) if row.get("dependency_id") == dependency_id), None)
        if index is None: raise PlanningControlError("PLANNING_DEPENDENCY_NOT_FOUND")
        self._assert_unlocked("planning_dependency", dependency_id, set(payload))
        old = copy.deepcopy(document["dependencies"][index]); edge = copy.deepcopy(old)
        for field in ("dependency_type", "strength", "description", "condition", "notes", "force_reason"):
            if field in payload: edge[field] = copy.deepcopy(payload[field])
        if "source_refs" in payload: edge["source_refs"] = self._source_refs(payload["source_refs"])
        if "from_node" in payload: edge["from_node"] = self._ref(payload["from_node"], document)
        if "to_node" in payload: edge["to_node"] = self._ref(payload["to_node"], document)
        edge["updated_at"] = now(); document["dependencies"].pop(index)
        warnings = self._validate_edge(document, edge, force_with_reason=bool(payload.get("force_with_reason"))); edge["validation_warnings"] = warnings
        document["dependencies"].insert(index, edge); previous = self._document(); previous["dependencies"][index] = old
        return self._save(document, previous=previous, event="planning_dependency_updated", entity_type="planning_dependency", entity_id=dependency_id, payload=payload, result=edge)

    def transition_dependency(self, dependency_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action", payload.get("status", "")))
        status = {"disable": "disabled", "disabled": "disabled", "enable": "active", "active": "active", "cancel": "cancelled", "cancelled": "cancelled"}.get(action)
        if not status: raise PlanningControlError("PLANNING_DEPENDENCY_INVALID_TRANSITION")
        document = self._document(); event = f"planning_dependency_{status}"; replay = self._replay(document, payload, event)
        if replay: replay["replayed"] = True; return replay
        self._assert_revision(document, payload); index = next((i for i, row in enumerate(document["dependencies"]) if row.get("dependency_id") == dependency_id), None)
        if index is None: raise PlanningControlError("PLANNING_DEPENDENCY_NOT_FOUND")
        self._assert_unlocked("planning_dependency", dependency_id, {"status"}); previous = copy.deepcopy(document); row = document["dependencies"][index]
        if row.get("status") == "cancelled" and status == "active": raise PlanningControlError("PLANNING_DEPENDENCY_INVALID_TRANSITION")
        if status == "active":
            trial = copy.deepcopy(row); trial["status"] = "active"; document["dependencies"].pop(index); self._validate_edge(document, trial, force_with_reason=bool(payload.get("force_with_reason"))); document["dependencies"].insert(index, trial); row = trial
        row["status"] = status; row["updated_at"] = now()
        return self._save(document, previous=previous, event=event, entity_type="planning_dependency", entity_id=dependency_id, payload=payload, result=row)

    def health(self, document: dict[str, Any] | None = None) -> dict[str, Any]:
        document = document or self._document(); issues: list[dict[str, Any]] = []
        for edge in document["dependencies"]:
            if edge.get("status") == "cancelled": continue
            for role in ("from_node", "to_node"):
                point = edge.get(role, {})
                current = self._node(str(point.get("node_type", "")), str(point.get("node_id", "")), document)
                if not current: issues.append({"code": "PLANNING_DEPENDENCY_SOURCE_MISSING", "dependency_id": edge.get("dependency_id"), "role": role})
                elif current.get("status") == "cancelled": issues.append({"code": "PLANNING_DEPENDENCY_SOURCE_CANCELLED", "dependency_id": edge.get("dependency_id"), "role": role})
        forward, _ = adjacency(document["dependencies"], prerequisite_only=True)
        loop = first_cycle(forward)
        if loop:
            issues.append({"code": "PLANNING_DEPENDENCY_CYCLE", "cycle_path": loop})
        for pair in mutual_blocks(document["dependencies"]): issues.append({"code": "PLANNING_MUTUAL_BLOCK", "nodes": pair})
        return {"valid": not any(item["code"] in {"PLANNING_DEPENDENCY_CYCLE", "PLANNING_DEPENDENCY_SOURCE_MISSING"} for item in issues), "dependency_revision": document["dependency_revision"], "issues": issues, "active_count": sum(row.get("status") == "active" for row in document["dependencies"])}

    def validate(self) -> dict[str, Any]:
        return self.health()

    def related(self, node_type: str, node_id: str, direction: str) -> dict[str, Any]:
        document = self._document(); ref = self._ref({"node_type": node_type, "node_id": node_id}, document); forward, reverse = adjacency(document["dependencies"]); graph = reverse if direction == "upstream" else forward
        key = node_key(ref); queue = [key]; seen = {key}; rows: list[dict[str, Any]] = []
        while queue:
            current = queue.pop(0)
            for next_key in sorted(graph.get(current, ())):
                if next_key not in seen:
                    seen.add(next_key); queue.append(next_key); kind, identity = next_key.split(":", 1); summary = self._node(kind, identity, document)
                    if summary: rows.append(summary)
        return {"node": ref, direction: rows, "dependency_revision": document["dependency_revision"]}

    def list_custom_nodes(self) -> dict[str, Any]:
        document = self._document(); return {"dependency_revision": document["dependency_revision"], "nodes": copy.deepcopy(document["custom_nodes"])}

    def create_custom_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        document = self._document(); replay = self._replay(document, payload, "custom_planning_node_created")
        if replay: replay["replayed"] = True; return replay
        self._assert_revision(document, payload)
        title = str(payload.get("title", "")).strip()
        if not title: raise PlanningControlError("PLANNING_DEPENDENCY_INVALID_NODE")
        item = base_entity(self.project_id, new_id("dependency_node")); item.update({"node_id": item["id"], "title": title, "description": str(payload.get("description", "")), "category": str(payload.get("category", "condition")), "status": "planned", "source_refs": self._source_refs(payload.get("source_refs", [])), "locked": bool(payload.get("locked", False)), "author_confirmed_at": now()})
        previous = copy.deepcopy(document); document["custom_nodes"].append(item)
        return self._save(document, previous=previous, event="custom_planning_node_created", entity_type="custom_planning_node", entity_id=item["node_id"], payload=payload, result=item)

    def update_custom_node(self, node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        document = self._document(); replay = self._replay(document, payload, "custom_planning_node_updated")
        if replay: replay["replayed"] = True; return replay
        self._assert_revision(document, payload); index = next((i for i, row in enumerate(document["custom_nodes"]) if row.get("node_id") == node_id), None)
        if index is None: raise PlanningControlError("PLANNING_CUSTOM_NODE_NOT_FOUND")
        self._assert_unlocked("custom_planning_node", node_id, set(payload)); previous = copy.deepcopy(document); item = document["custom_nodes"][index]
        for field in ("title", "description", "category", "locked"):
            if field in payload: item[field] = copy.deepcopy(payload[field])
        if "source_refs" in payload: item["source_refs"] = self._source_refs(payload["source_refs"])
        if not str(item.get("title", "")).strip(): raise PlanningControlError("PLANNING_DEPENDENCY_INVALID_NODE")
        item["updated_at"] = now()
        return self._save(document, previous=previous, event="custom_planning_node_updated", entity_type="custom_planning_node", entity_id=node_id, payload=payload, result=item)

    def transition_custom_node(self, node_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        status = str(payload.get("status", payload.get("action", ""))); status = {"cancel": "cancelled", "enable": "planned"}.get(status, status)
        if status not in CUSTOM_NODE_STATUSES: raise PlanningControlError("PLANNING_DEPENDENCY_INVALID_TRANSITION")
        document = self._document(); event = f"custom_planning_node_{status}"; replay = self._replay(document, payload, event)
        if replay: replay["replayed"] = True; return replay
        self._assert_revision(document, payload); item = next((row for row in document["custom_nodes"] if row.get("node_id") == node_id), None)
        if not item: raise PlanningControlError("PLANNING_CUSTOM_NODE_NOT_FOUND")
        self._assert_unlocked("custom_planning_node", node_id, {"status"}); previous = copy.deepcopy(document); item["status"] = status; item["updated_at"] = now()
        return self._save(document, previous=previous, event=event, entity_type="custom_planning_node", entity_id=node_id, payload=payload, result=item)
