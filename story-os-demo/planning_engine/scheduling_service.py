"""Manual narrative scheduling.  This layer records intent; it never schedules automatically."""
from __future__ import annotations

import copy
from typing import Any

from core.project_context import ProjectContext, get_project_context
from system.data_store import DataWriteError
from system.planning_mutation_service import PlanningMutationError
from system.planning_service import load_planning

from .control_service import PlanningControlError, PlanningControlService
from .models import base_entity, new_id, now
from .scheduling_models import ACTION_ORDER, ACTIONS, PRIORITIES, SCHEDULE_STATUSES, SUBJECT_TYPES


class NarrativeSchedulingService:
    def __init__(self, context: ProjectContext | None = None) -> None:
        self.context = context or get_project_context()
        self.control = PlanningControlService(self.context)
        self.store = self.control.store
        self.project_id = self.context.root.resolve().as_posix()

    def _empty(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "project_id": self.project_id, "schedule_revision": 0, "schedules": [], "operations": [], "audit": []}

    def _document(self) -> dict[str, Any]:
        value = self.store.read_json(self.context.planning_schedules_path, default=None, expected_type=dict)
        if not isinstance(value, dict) or value.get("project_id") not in (None, self.project_id):
            return self._empty()
        document = copy.deepcopy(value); document["project_id"] = self.project_id
        for key, default in (("schema_version", "1.0"), ("schedule_revision", 0), ("schedules", []), ("operations", []), ("audit", [])):
            document.setdefault(key, default)
        return document

    @staticmethod
    def _integer(value: Any) -> int | None:
        if value is None: return None
        try: return int(value)
        except (TypeError, ValueError) as exc: raise PlanningControlError("NARRATIVE_SCHEDULE_REVISION_CONFLICT") from exc

    def _assert_revision(self, document: dict[str, Any], payload: dict[str, Any]) -> None:
        expected, actual = self._integer(payload.get("expected_schedule_revision")), int(document.get("schedule_revision", 0) or 0)
        if expected is not None and expected != actual:
            raise PlanningControlError("NARRATIVE_SCHEDULE_REVISION_CONFLICT", details={"expected_revision": expected, "actual_revision": actual})

    def _replay(self, document: dict[str, Any], payload: dict[str, Any], event: str) -> dict[str, Any] | None:
        operation_id = str(payload.get("operation_id", "") or "")
        row = next((item for item in document["operations"] if item.get("operation_id") == operation_id and item.get("event") == event), None) if operation_id else None
        return copy.deepcopy(row.get("result")) if row else None

    def _save(self, document: dict[str, Any], previous: dict[str, Any], event: str, schedule_id: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        before = int(previous.get("schedule_revision", 0) or 0); document["schedule_revision"] = before + 1; document["updated_at"] = now()
        snapshot = self.control._read(); snapshot["schedules"] = copy.deepcopy(previous) if self.store.exists(self.context.planning_schedules_path) else None
        try:
            version = self.control.versions.create(self.project_id, event, self.control._snapshot(snapshot))
            document["version_id"] = version["version_id"]
            document["audit"].append({"event": event, "project_id": self.project_id, "schedule_id": schedule_id, "operation_id": str(payload.get("operation_id", "") or ""), "revision_before": before, "revision_after": document["schedule_revision"], "operator": "user", "planning_control_version_id": version["version_id"], "created_at": now()})
            if payload.get("operation_id"):
                stored = copy.deepcopy(result); stored["schedule_revision"] = document["schedule_revision"]
                document["operations"].append({"operation_id": str(payload["operation_id"]), "event": event, "result": stored, "completed_at": now()}); document["operations"] = document["operations"][-100:]
            self.control.mutations.legacy_write("schedules", document, mutation_type=event, operation_id=str(payload.get("operation_id", "") or ""), reason=event)
        except (DataWriteError, PlanningMutationError) as exc:
            raise PlanningControlError("NARRATIVE_SCHEDULE_WRITE_FAILED", str(exc)) from exc
        saved = copy.deepcopy(result); saved["schedule_revision"] = document["schedule_revision"]
        return saved

    def _slots(self) -> dict[str, dict[str, Any]]:
        window = self.control._read().get("rolling_window") or {}; result: dict[str, dict[str, Any]] = {}
        for group in ("near_slots", "mid_slots", "elapsed_slots"):
            for item in window.get(group, []):
                if isinstance(item, dict) and item.get("slot_id"):
                    result[str(item["slot_id"])] = item
        return result

    def _subject(self, subject_type: str, subject_ref: Any) -> dict[str, Any]:
        if subject_type not in SUBJECT_TYPES or not isinstance(subject_ref, dict):
            raise PlanningControlError("NARRATIVE_SCHEDULE_INVALID_SUBJECT")
        subject_id = str(subject_ref.get("subject_id", subject_ref.get("entity_id", "")) or "")
        if subject_ref.get("project_id") not in (None, "", self.project_id):
            raise PlanningControlError("NARRATIVE_SCHEDULE_INVALID_SUBJECT")
        planning = load_planning(self.context); blueprint = self.store.read_json(self.context.data_dir / "story_blueprint.json", default={}, expected_type=dict) or {}
        choices: list[tuple[list[Any], tuple[str, ...], str]] = []
        if subject_type == "plot_thread": choices = [(planning.get("plot_threads", []), ("thread_id", "id"), "structured_planning"), (blueprint.get("plot_threads", []), ("thread_id", "id"), "story_blueprint")]
        elif subject_type == "character_arc": choices = [(planning.get("character_arcs", []), ("character_arc_id", "arc_id", "id"), "structured_planning"), (blueprint.get("character_arcs", []), ("character_arc_id", "arc_id", "id"), "story_blueprint")]
        else: choices = [(planning.get("foreshadowing", []), ("foreshadowing_id", "foreshadow_id", "id"), "structured_planning"), (blueprint.get("initial_foreshadow_pool", []), ("foreshadowing_id", "foreshadow_id", "id"), "story_blueprint")]
        for values, keys, source_type in choices:
            for index, item in enumerate(values if isinstance(values, list) else []):
                if isinstance(item, str) and subject_type == "foreshadowing":
                    item = {"title": item, "id": f"initial_foreshadow_{index + 1}"}
                if not isinstance(item, dict): continue
                identifier = next((str(item.get(key)) for key in keys if item.get(key) not in (None, "")), "")
                if subject_id and identifier == subject_id:
                    return {"subject_id": identifier, "title": str(item.get("title") or item.get("name") or item.get("content") or identifier), "source_type": source_type, "source_ref": {"source_type": source_type, "source_path": "data/story_planning.json" if source_type == "structured_planning" else "data/story_blueprint.json", "entity_type": subject_type, "entity_id": identifier}}
        if subject_ref.get("source_type") == "manual" and subject_ref.get("manual_scope") and subject_id:
            return {"subject_id": subject_id, "title": str(subject_ref.get("title") or subject_id), "source_type": "manual", "source_ref": copy.deepcopy(subject_ref)}
        raise PlanningControlError("NARRATIVE_SCHEDULE_INVALID_SUBJECT")

    def _slot(self, slot_id: str, chapter: Any) -> dict[str, Any]:
        slot = self._slots().get(str(slot_id))
        if not slot or slot.get("status") in {"cancelled", "elapsed"}: raise PlanningControlError("NARRATIVE_SCHEDULE_INVALID_SLOT")
        try: expected = int(chapter)
        except (TypeError, ValueError) as exc: raise PlanningControlError("NARRATIVE_SCHEDULE_INVALID_SLOT") from exc
        if expected != int(slot.get("planned_chapter_number", 0) or 0): raise PlanningControlError("NARRATIVE_SCHEDULE_INVALID_SLOT")
        current = int((self.store.read_json(self.context.data_dir / "state.json", default={}, expected_type=dict) or {}).get("current_chapter", 0) or 0)
        if expected <= current: raise PlanningControlError("NARRATIVE_SCHEDULE_SLOT_IN_PAST")
        return slot

    def _assert_unlocked(self, schedule_id: str, fields: set[str]) -> None:
        for lock in self.control._read().get("locks", []):
            if lock.get("active") and lock.get("entity_type") == "narrative_schedule" and lock.get("entity_id") == schedule_id and (lock.get("field") == "*" or lock.get("field") in fields):
                raise PlanningControlError("NARRATIVE_SCHEDULE_LOCK_CONFLICT")

    def _dependency_warnings(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        dependencies = (self.control._read().get("dependencies") or {}).get("dependencies", []); subject_nodes = {"plot_thread": "structured_plot_thread", "character_arc": "structured_character_arc", "foreshadowing": "blueprint_foreshadow"}
        target = int(record["target_chapter_number"]); node_type = subject_nodes[record["subject_type"]]; node_id = record["subject_ref"]["subject_id"]
        warnings: list[dict[str, Any]] = []
        referenced = {str(value.get("dependency_id", "")) if isinstance(value, dict) else str(value) for value in record.get("dependency_refs", []) if isinstance(value, (str, dict))}
        referenced.discard("")
        for dependency_id in referenced:
            edge = next((item for item in dependencies if str(item.get("dependency_id")) == dependency_id), None)
            if not edge:
                raise PlanningControlError("NARRATIVE_SCHEDULE_DEPENDENCY_CONFLICT", details={"code": "SCHEDULE_DEPENDENCY_REFERENCE_MISSING", "dependency_id": dependency_id})
            if edge.get("status") != "active":
                warnings.append({"code": "SCHEDULE_DEPENDENCY_DISABLED", "dependency_id": dependency_id})
            elif edge.get("strength") == "hard":
                warnings.append({"code": "SCHEDULE_DEPENDENCY_REFERENCED", "dependency_id": dependency_id})
        for edge in dependencies:
            if edge.get("status") != "active" or edge.get("dependency_type") not in {"requires", "precedes", "enables"}: continue
            end = edge.get("to_node", {}); start = edge.get("from_node", {})
            if end.get("node_type") == node_type and end.get("node_id") == node_id and start.get("node_type") == "chapter_slot":
                slot = self._slots().get(str(start.get("node_id"))); prior = int(slot.get("planned_chapter_number", 0) or 0) if slot else None
                if prior and target < prior:
                    detail = {"code": "SCHEDULE_DEPENDENCY_ORDER_CONFLICT", "dependency_id": edge.get("dependency_id"), "dependency_path": [f"chapter_slot:{start.get('node_id')}", f"{node_type}:{node_id}"], "required_chapter": prior, "target_chapter": target}
                    if edge.get("strength") == "hard": raise PlanningControlError("NARRATIVE_SCHEDULE_DEPENDENCY_CONFLICT", details=detail)
                    warnings.append(detail)
        return warnings

    def _order_warnings(self, document: dict[str, Any], record: dict[str, Any]) -> list[dict[str, Any]]:
        active = [item for item in document["schedules"] if item.get("status") in {"planned", "reviewed", "elapsed"} and item.get("subject_type") == record["subject_type"] and item.get("subject_ref", {}).get("subject_id") == record["subject_ref"]["subject_id"]]
        values = active + [record]; values.sort(key=lambda item: (int(item.get("target_chapter_number", 0) or 0), item.get("created_at", "")))
        warnings: list[dict[str, Any]] = []; last = -1
        for item in values:
            rank = ACTION_ORDER[item["subject_type"]].get(item.get("schedule_action"), 0)
            if rank < last:
                detail = {"code": "NARRATIVE_SCHEDULE_ORDER_CONFLICT", "subject_id": record["subject_ref"]["subject_id"], "previous_rank": last, "action": record["schedule_action"]}
                if record["subject_type"] == "foreshadowing": raise PlanningControlError("NARRATIVE_SCHEDULE_ORDER_CONFLICT", details=detail)
                warnings.append(detail)
            last = max(last, rank)
        return warnings

    def _validate(self, document: dict[str, Any], record: dict[str, Any]) -> list[dict[str, Any]]:
        if record["subject_type"] not in SUBJECT_TYPES or record["schedule_action"] not in ACTIONS[record["subject_type"]] or record.get("priority", "medium") not in PRIORITIES:
            raise PlanningControlError("NARRATIVE_SCHEDULE_INVALID_ACTION")
        self._subject(record["subject_type"], record["subject_ref"]); self._slot(record["target_slot_id"], record["target_chapter_number"])
        return self._dependency_warnings(record) + self._order_warnings(document, record)

    def describe(self) -> dict[str, Any]:
        document = self._document(); return {"materialized": self.store.exists(self.context.planning_schedules_path), "schedule_revision": document["schedule_revision"], "schedules": copy.deepcopy(document["schedules"]), "subjects": self.available_subjects(), "slots": self.available_slots(), "health": self.health(document)}

    def available_subjects(self) -> dict[str, list[dict[str, Any]]]:
        planning = load_planning(self.context); blueprint = self.store.read_json(self.context.data_dir / "story_blueprint.json", default={}, expected_type=dict) or {}
        def rows(values: Any, keys: tuple[str, ...], source: str, fallback_prefix: str = "") -> list[dict[str, Any]]:
            result=[]
            for index, item in enumerate(values if isinstance(values, list) else []):
                if isinstance(item, str): item={"title":item, "id":f"{fallback_prefix}{index+1}"}
                if isinstance(item, dict):
                    identity=next((str(item.get(key)) for key in keys if item.get(key) not in (None,"")), "")
                    if identity: result.append({"subject_id":identity,"title":str(item.get("title") or item.get("name") or item.get("content") or identity),"source_type":source})
            return result
        return {"plot_thread": rows(planning.get("plot_threads", []) or blueprint.get("plot_threads", []), ("thread_id", "id"), "structured_planning"), "character_arc": rows(planning.get("character_arcs", []) or blueprint.get("character_arcs", []), ("character_arc_id", "arc_id", "id"), "structured_planning"), "foreshadowing": rows(planning.get("foreshadowing", []) or blueprint.get("initial_foreshadow_pool", []), ("foreshadowing_id", "foreshadow_id", "id"), "structured_planning" if planning.get("foreshadowing") else "story_blueprint", "initial_foreshadow_")}

    def available_slots(self) -> list[dict[str, Any]]:
        return sorted([{key: row.get(key) for key in ("slot_id", "planned_chapter_number", "horizon", "status", "title_hint")} for row in self._slots().values() if row.get("status") not in {"cancelled", "elapsed"}], key=lambda row: int(row.get("planned_chapter_number", 0) or 0))

    def list(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        document = self._document(); values = document["schedules"]; filters = filters or {}
        for field in ("subject_type", "status"):
            if filters.get(field): values = [row for row in values if row.get(field) == filters[field]]
        if filters.get("subject_id"): values = [row for row in values if row.get("subject_ref", {}).get("subject_id") == filters["subject_id"]]
        if filters.get("slot_id"): values = [row for row in values if row.get("target_slot_id") == filters["slot_id"]]
        if filters.get("chapter_number"): values = [row for row in values if str(row.get("target_chapter_number")) == str(filters["chapter_number"])]
        return {"schedule_revision": document["schedule_revision"], "schedules": copy.deepcopy(values), "subjects": self.available_subjects(), "slots": self.available_slots(), "health": self.health(document)}

    def get(self, schedule_id: str) -> dict[str, Any]:
        item = next((row for row in self._document()["schedules"] if row.get("schedule_id") == schedule_id), None)
        if not item: raise PlanningControlError("NARRATIVE_SCHEDULE_NOT_FOUND")
        return copy.deepcopy(item)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        document = self._document(); replay = self._replay(document, payload, "narrative_schedule_created")
        if replay: replay["replayed"] = True; return replay
        self._assert_revision(document, payload); subject_type = str(payload.get("subject_type", "")); subject = self._subject(subject_type, payload.get("subject_ref", {}))
        record = base_entity(self.project_id, new_id("schedule")); record.update({"schedule_id":record["id"],"subject_type":subject_type,"subject_ref":subject,"schedule_action":str(payload.get("schedule_action", "")),"target_slot_id":str(payload.get("target_slot_id", "")),"target_chapter_number":payload.get("target_chapter_number"),"priority":str(payload.get("priority", "medium")),"status":"planned","dependency_refs":copy.deepcopy(payload.get("dependency_refs", [])),"requirements":copy.deepcopy(payload.get("requirements", [])),"expected_outcome":str(payload.get("expected_outcome", "")),"author_notes":str(payload.get("author_notes", "")),"locked":False,"source_refs":copy.deepcopy(payload.get("source_refs", [subject["source_ref"]])),"author_confirmed_at":now()})
        if any(item.get("status") in {"planned","reviewed"} and item.get("subject_type") == record["subject_type"] and item.get("subject_ref",{}).get("subject_id") == subject["subject_id"] and item.get("schedule_action") == record["schedule_action"] and item.get("target_slot_id") == record["target_slot_id"] for item in document["schedules"]): raise PlanningControlError("NARRATIVE_SCHEDULE_ALREADY_EXISTS")
        record["validation_warnings"] = self._validate(document, record); previous=copy.deepcopy(document); document["schedules"].append(record)
        return self._save(document, previous, "narrative_schedule_created", record["schedule_id"], payload, record)

    def update(self, schedule_id: str, payload: dict[str, Any], event: str = "narrative_schedule_updated") -> dict[str, Any]:
        document=self._document(); replay=self._replay(document,payload,event)
        if replay: replay["replayed"]=True; return replay
        self._assert_revision(document,payload); index=next((i for i,row in enumerate(document["schedules"]) if row.get("schedule_id")==schedule_id),None)
        if index is None: raise PlanningControlError("NARRATIVE_SCHEDULE_NOT_FOUND")
        self._assert_unlocked(schedule_id,set(payload)); previous=copy.deepcopy(document); record=copy.deepcopy(document["schedules"][index])
        for field in ("schedule_action","priority","requirements","expected_outcome","author_notes","dependency_refs","source_refs"):
            if field in payload: record[field]=copy.deepcopy(payload[field])
        if "subject_type" in payload: record["subject_type"]=str(payload["subject_type"])
        if "subject_ref" in payload: record["subject_ref"]=self._subject(record["subject_type"],payload["subject_ref"])
        if "target_slot_id" in payload: record["target_slot_id"]=str(payload["target_slot_id"])
        if "target_chapter_number" in payload: record["target_chapter_number"]=payload["target_chapter_number"]
        record["updated_at"]=now(); document["schedules"].pop(index); record["validation_warnings"]=self._validate(document,record); document["schedules"].insert(index,record)
        return self._save(document,previous,event,schedule_id,payload,record)

    def transition(self, schedule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        action=str(payload.get("action",payload.get("status", ""))); status={"review":"reviewed","cancel":"cancelled"}.get(action)
        if not status: raise PlanningControlError("NARRATIVE_SCHEDULE_INVALID_TRANSITION")
        event="narrative_schedule_reviewed" if status=="reviewed" else "narrative_schedule_cancelled"; document=self._document(); replay=self._replay(document,payload,event)
        if replay: replay["replayed"]=True; return replay
        self._assert_revision(document,payload); item=next((row for row in document["schedules"] if row.get("schedule_id")==schedule_id),None)
        if not item: raise PlanningControlError("NARRATIVE_SCHEDULE_NOT_FOUND")
        self._assert_unlocked(schedule_id,{"status"}); previous=copy.deepcopy(document); item["status"]=status; item["updated_at"]=now()
        return self._save(document,previous,event,schedule_id,payload,item)

    def rebind(self, schedule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload={**payload,"target_slot_id":payload.get("target_slot_id"),"target_chapter_number":payload.get("target_chapter_number")}; result=self.update(schedule_id,payload,"narrative_schedule_rebound")
        return result

    def timeline(self, subject_type: str, subject_id: str) -> dict[str, Any]:
        document=self._document(); values=[row for row in document["schedules"] if row.get("subject_type")==subject_type and row.get("subject_ref",{}).get("subject_id")==subject_id]
        return {"subject_type":subject_type,"subject_id":subject_id,"schedule_revision":document["schedule_revision"],"timeline":sorted(copy.deepcopy(values),key=lambda row:(int(row.get("target_chapter_number",0) or 0),row.get("created_at","")))}

    def by_slot(self, slot_id: str) -> dict[str, Any]:
        document=self._document(); values=[row for row in document["schedules"] if row.get("target_slot_id")==slot_id]
        count=len([row for row in values if row.get("status") in {"planned","reviewed"}]); warnings=[]
        if count >= 6: warnings.append({"code":"SCHEDULE_SLOT_OVERLOADED_HIGH","count":count})
        elif count >= 4: warnings.append({"code":"SCHEDULE_SLOT_OVERLOADED","count":count})
        return {"slot_id":slot_id,"schedule_count":count,"schedules":copy.deepcopy(values),"subjects":[f"{row.get('subject_type')}：{row.get('subject_ref',{}).get('title','')}" for row in values],"warnings":warnings,"schedule_revision":document["schedule_revision"]}

    def health(self, document: dict[str, Any] | None = None) -> dict[str, Any]:
        document=document or self._document(); issues=[]; invalid_subject=invalid_slot=dependency=order=0
        for row in document["schedules"]:
            if row.get("status") in {"cancelled","elapsed"}: continue
            try: self._subject(str(row.get("subject_type","")),row.get("subject_ref",{}))
            except PlanningControlError: invalid_subject+=1; issues.append({"code":"NARRATIVE_SCHEDULE_INVALID_SUBJECT","schedule_id":row.get("schedule_id")}); continue
            try: self._slot(str(row.get("target_slot_id","")),row.get("target_chapter_number"))
            except PlanningControlError: invalid_slot+=1; issues.append({"code":"NARRATIVE_SCHEDULE_INVALID_SLOT","schedule_id":row.get("schedule_id")})
            try: self._dependency_warnings(row)
            except PlanningControlError as error: dependency+=1; issues.append({"code":"SCHEDULE_DEPENDENCY_ORDER_CONFLICT","schedule_id":row.get("schedule_id"),"details":error.details})
            try: self._order_warnings({**document,"schedules":[item for item in document["schedules"] if item is not row]},row)
            except PlanningControlError: order+=1; issues.append({"code":"NARRATIVE_SCHEDULE_ORDER_CONFLICT","schedule_id":row.get("schedule_id")})
        for slot_id in {row.get("target_slot_id") for row in document["schedules"] if row.get("target_slot_id")}:
            summary=self.by_slot(str(slot_id)); issues.extend([{**item,"slot_id":slot_id} for item in summary["warnings"]])
        overloaded=sum(1 for item in issues if item["code"].startswith("SCHEDULE_SLOT_OVERLOADED")); status="invalid" if invalid_subject or invalid_slot or dependency else "warning" if issues else "healthy"
        return {"status":status,"schedule_count":len(document["schedules"]),"invalid_subject_count":invalid_subject,"invalid_slot_count":invalid_slot,"dependency_conflict_count":dependency,"order_conflict_count":order,"overloaded_slot_count":overloaded,"issues":issues,"schedule_revision":document["schedule_revision"]}

    def validate(self) -> dict[str, Any]: return self.health()

    def mark_elapsed_slots(self, slot_ids: list[str]) -> dict[str, Any]:
        if not self.store.exists(self.context.planning_schedules_path): return {"changed":0,"warnings":[]}
        document=self._document(); previous=copy.deepcopy(document); changed=[]
        for item in document["schedules"]:
            if item.get("target_slot_id") in set(slot_ids) and item.get("status") in {"planned","reviewed"}: item["status"]="elapsed"; item["updated_at"]=now(); changed.append(item["schedule_id"])
        if not changed: return {"changed":0,"warnings":[]}
        result={"changed":len(changed),"schedule_ids":changed}; self._save(document,previous,"narrative_schedule_elapsed","window_roll_forward",{},result); return result
