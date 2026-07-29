"""Read-only narrative turn context binder.

Phase 0D4-B-FIX-RC: builds a deterministic, fingerprinted snapshot of all
authoritative and advisory narrative context needed by the Planner,
Feasibility Engine, and Preview Service.

All reads are pure read — no writes to any store, no Provider calls,
no network. The context_fingerprint is derived from strict canonical
serialization (no default=str fallback).

Cold-start safety: bind() never creates, modifies, or repairs any file.
All loader calls use read-only paths that return structured missing/error
on absent data rather than auto-initializing.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

from core.contracts.narrative_turn import (
    NarrativeScope,
    NarrativeTurnError,
    TimelineContext,
)
from core.project_context import ProjectContext


SCHEMA_VERSION = "1.0"
PLANNER_REVISION = "narrative-turn-planner-v1"

# Maximum nesting depth for recursive freeze / canonical serialization.
_MAX_DEPTH = 64
# Maximum elements in a single list/tuple.
_MAX_LIST_LEN = 10_000


# ---------------------------------------------------------------------------
# Strict canonical serialization (no default=str)
# ---------------------------------------------------------------------------

class ContextValueInvalid(Exception):
    """Raised when a value cannot be canonically serialized."""

    def __init__(self, path: str, value_type: str) -> None:
        self.path = path
        self.value_type = value_type
        super().__init__(f"CONTEXT_VALUE_INVALID at {path}: type={value_type}")


def _canonical_json(data: Any) -> str:
    """Strict canonical JSON serialization.

    Allows: None, bool, int, finite float, str, frozen sequence, frozen object.
    Rejects: NaN, Infinity, Path, datetime, set, bytes, custom objects.
    """
    return json.dumps(_canonicalize(data, "$"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _canonicalize(value: Any, path: str, depth: int = 0) -> Any:
    if depth > _MAX_DEPTH:
        raise ContextValueInvalid(path, f"max_depth_exceeded")

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ContextValueInvalid(path, f"float:{value}")
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_LIST_LEN:
            raise ContextValueInvalid(path, f"list_too_long:{len(value)}")
        return [_canonicalize(v, f"{path}[{i}]", depth + 1) for i, v in enumerate(value)]
    if isinstance(value, dict):
        # All keys must be strings.
        result: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise ContextValueInvalid(f"{path}.<key>", f"key_type:{type(k).__name__}")
            result[k] = _canonicalize(v, f"{path}.{k}", depth + 1)
        return result
    # Reject everything else: Path, datetime, set, bytes, custom objects.
    raise ContextValueInvalid(path, type(value).__name__)


def _stable_fingerprint(data: Any) -> str:
    """SHA-256 of strict canonical JSON. Same input → same output."""
    return sha256(_canonical_json(data).encode("utf-8")).hexdigest()


_BRANCH_STATE_REVISION_EXCLUDED_FIELDS = {
    "revision",
    "updated_at",
    "last_applied_turn_id",
    "last_event_sequence",
    "last_result_fingerprint",
    "applied_result_fingerprints",
}


def branch_state_content_revision(state: dict[str, Any]) -> str:
    """Canonical revision for authoritative narrative-state content."""
    return _stable_fingerprint(
        {
            key: value
            for key, value in state.items()
            if key not in _BRANCH_STATE_REVISION_EXCLUDED_FIELDS
        }
    )


def context_fingerprint_for(
    snapshot: "NarrativeTurnContextSnapshot",
    *,
    branch_state_revision: str | None,
) -> str:
    """Recompute the Binder fingerprint with one authoritative state revision."""
    return _stable_fingerprint(
        {
            "planner_revision": snapshot.planner_revision,
            "project_id": snapshot.scope.project_id,
            "timeline_id": snapshot.scope.timeline_id,
            "branch_id": snapshot.scope.branch_id,
            "chapter_id": snapshot.chapter_id,
            "source_version_id": snapshot.source_version_id,
            "source_fingerprint": snapshot.source_fingerprint,
            "canon_revision": snapshot.canon_revision,
            "planning_revision": snapshot.planning_revision,
            "chapter_plan_revision": snapshot.chapter_plan_revision,
            "dependency_revision": snapshot.dependency_revision,
            "branch_state_revision": branch_state_revision,
            "world_revision": snapshot.world_revision,
            "character_revision": snapshot.character_revision,
            "location_revision": snapshot.location_revision,
            "resource_revision": snapshot.resource_revision,
            "relationship_revision": snapshot.relationship_revision,
            "time_state_revision": snapshot.time_state_revision,
        }
    )


# ---------------------------------------------------------------------------
# Recursive freeze — deep immutability
# ---------------------------------------------------------------------------

class FrozenValue:
    """Marker for an unrecognized type that was rejected during freeze."""


def _freeze(value: Any, depth: int = 0) -> Any:
    """Recursively freeze a value into an immutable representation.

    - dict → frozen dict (sorted-key tuple of (str, frozen_value))
    - list/tuple → tuple of frozen values
    - None/bool/int/finite-float/str → as-is
    - Everything else → fail-closed (raise)
    """
    if depth > _MAX_DEPTH:
        raise ValueError(f"freeze max_depth_exceeded at depth {depth}")

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("freeze rejected NaN/Infinity")
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_LIST_LEN:
            raise ValueError(f"freeze list_too_long: {len(value)}")
        return tuple(_freeze(v, depth + 1) for v in value)
    if isinstance(value, dict):
        items = []
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError(f"freeze rejected non-str key: {type(k).__name__}")
            items.append((k, _freeze(v, depth + 1)))
        # Return as sorted tuple of pairs — immutable and ordered.
        items.sort(key=lambda kv: kv[0])
        return tuple(items)
    # Reject Path, datetime, set, bytes, custom objects.
    raise ValueError(f"freeze rejected type: {type(value).__name__}")


def _unfreeze(value: Any) -> Any:
    """Convert a frozen value back to a mutable dict/list representation.

    This is used to provide dict/list accessors on the snapshot without
    exposing the internal frozen representation. The returned value is a
    fresh deep copy — modifying it does not affect the snapshot.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, tuple):
        # Check if it's a frozen dict (tuple of (str, value) pairs).
        if value and isinstance(value[0], tuple) and len(value[0]) == 2 and isinstance(value[0][0], str):
            result: dict[str, Any] = {}
            for k, v in value:
                result[k] = _unfreeze(v)
            return result
        # Otherwise it's a frozen list.
        return [_unfreeze(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Snapshot DTO
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NarrativeTurnContextSnapshot:
    """Immutable, fingerprinted snapshot of narrative turn context.

    All dict/list fields are recursively frozen at construction time.
    Mutation of the original input data after bind() has no effect on
    the snapshot or its fingerprint.
    """

    schema_version: str
    scope: NarrativeScope
    chapter_id: int
    source_version_id: str | None
    source_fingerprint: str
    canon_revision: str | None
    planning_revision: str
    chapter_plan_revision: str | None
    dependency_revision: str | None
    branch_state_revision: str | None
    world_revision: str | None
    character_revision: str | None
    location_revision: str | None
    resource_revision: str | None
    relationship_revision: str | None
    time_state_revision: str | None
    planner_revision: str
    context_fingerprint: str

    branch_open: bool
    branch_is_active: bool

    # Advisory / evidence data — recursively frozen as immutable tuples.
    planning_data: tuple = field(default_factory=tuple)
    chapter_plan: tuple = field(default_factory=tuple)
    world_data: tuple = field(default_factory=tuple)
    character_data: tuple = field(default_factory=tuple)
    narrative_state: tuple = field(default_factory=tuple)
    rolling_window: tuple = field(default_factory=tuple)
    dependencies: tuple = field(default_factory=tuple)
    evidence_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    # --- Dict accessors (return fresh deep copies, safe to mutate) ---

    def planning_data_dict(self) -> dict[str, Any]:
        return _unfreeze(self.planning_data) or {}

    def chapter_plan_dict(self) -> dict[str, Any]:
        return _unfreeze(self.chapter_plan) or {}

    def world_data_dict(self) -> dict[str, Any]:
        return _unfreeze(self.world_data) or {}

    def character_data_dict(self) -> dict[str, Any]:
        return _unfreeze(self.character_data) or {}

    def narrative_state_dict(self) -> dict[str, Any]:
        return _unfreeze(self.narrative_state) or {}

    def rolling_window_dict(self) -> dict[str, Any]:
        return _unfreeze(self.rolling_window) or {}

    def dependencies_dict(self) -> dict[str, Any]:
        return _unfreeze(self.dependencies) or {}


# ---------------------------------------------------------------------------
# Read-only file helpers (no writes, no auto-creation)
# ---------------------------------------------------------------------------

def _read_json_file(path: Path) -> dict[str, Any] | None:
    """Read a JSON file. Return None if missing or invalid. Never writes.

    DEPRECATED for authority inputs: use _read_json_strict() instead,
    which distinguishes missing from invalid so that malformed data is
    not silently treated as missing.
    """
    try:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


# Read status codes for strict JSON reading.
_READ_OK = "ok"
_READ_MISSING = "missing"
_READ_INVALID = "invalid"


def _read_json_strict(path: Path) -> tuple[str, dict[str, Any] | None]:
    """Read a JSON file, distinguishing missing from invalid.

    Returns (status, data):
    - ("ok", dict) if file exists and parses as a dict
    - ("missing", None) if file does not exist
    - ("invalid", None) if file exists but cannot be parsed or is not a dict

    Never writes. Never repairs. Never auto-creates.
    """
    try:
        if not path.exists():
            return (_READ_MISSING, None)
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict):
            return (_READ_OK, data)
        return (_READ_INVALID, None)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return (_READ_INVALID, None)


def _read_text_file(path: Path) -> str | None:
    """Read a text file. Return None if missing. Never writes."""
    try:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Context Binder
# ---------------------------------------------------------------------------

class NarrativeTurnContextBinder:
    """Binds project + timeline + branch + chapter + planning data
    into an immutable, fingerprinted snapshot.

    Strictly read-only. No writes to any store. No Provider calls.
    No auto-initialization. No auto-repair. No directory creation.
    """

    def __init__(self, project_context: ProjectContext) -> None:
        self._project_context = project_context
        self._project_id = project_context.root.name
        # We do NOT instantiate DataStore, RevisionService, or
        # NarrativeBranchStore here because their constructors or
        # methods may trigger writes. We read files directly.

    def bind(
        self,
        scope: NarrativeScope,
        chapter_id: int,
        *,
        source_version_id: str | None = None,
        parent_turn_id: str | None = None,
    ) -> NarrativeTurnContextSnapshot:
        if scope.project_id != self._project_id:
            raise NarrativeTurnError(
                NarrativeTurnError.SCOPE_MISMATCH,
                f"Scope project_id {scope.project_id!r} does not match current project",
            )

        timeline_ctx = TimelineContext(
            project_id=scope.project_id,
            timeline_id=scope.timeline_id,
        )

        # --- Branch status (read-only) ---
        branch_info = self._read_branch_info(timeline_ctx, scope.branch_id)
        if branch_info is None:
            raise NarrativeTurnError(
                NarrativeTurnError.MISSING_PARENT_BRANCH,
                f"Branch not found: {scope.branch_id}",
            )

        from core.contracts.narrative_turn import BranchLifecycleStatus

        if branch_info["lifecycle_status"] == BranchLifecycleStatus.ARCHIVED:
            raise NarrativeTurnError(
                NarrativeTurnError.BRANCH_LIFECYCLE_CONFLICT,
                f"Branch is archived: {scope.branch_id}",
            )

        branch_is_active = branch_info["active_branch_id"] == scope.branch_id
        branch_open = branch_info["lifecycle_status"] == BranchLifecycleStatus.OPEN

        # --- Source (read-only) ---
        source_fingerprint, source_vid = self._read_source(chapter_id)

        # --- Canon revision (read-only, no auto-init) ---
        canon_rev = self._read_canon_revision(chapter_id)

        # --- Planning (read-only raw JSON, no _normalize) ---
        planning_data, planning_read_status = self._read_planning_raw()
        planning_rev = _stable_fingerprint(planning_data) if planning_data else "empty"

        # --- Chapter plan (extracted from planning data) ---
        chapter_plan = self._find_chapter_plan(planning_data, chapter_id)
        chapter_plan_rev = _stable_fingerprint(chapter_plan) if chapter_plan else None

        # --- World (read-only) ---
        world_data, world_read_status = self._read_world()
        world_rev = _stable_fingerprint(world_data) if world_data else None

        # --- Characters (read-only) ---
        character_data, char_read_status = self._read_characters()
        char_rev = _stable_fingerprint(character_data) if character_data else None

        # --- Location (extracted from world) ---
        locations = world_data.get("locations", []) if world_data else []
        location_rev = _stable_fingerprint(locations) if locations else None

        # --- Resources (extracted from world) ---
        resources = world_data.get("resources", {}) if world_data else {}
        resource_rev = _stable_fingerprint(resources) if resources else None

        # --- Relationships (extracted from characters) ---
        relationships = self._extract_relationships(character_data)
        relationship_rev = _stable_fingerprint(relationships) if relationships else None

        # --- Rolling window / time state (read-only) ---
        rolling_window, rolling_read_status = self._read_rolling_window()
        time_state_rev = _stable_fingerprint(rolling_window) if rolling_window else None

        # --- Dependencies (read-only) ---
        dependencies, deps_read_status = self._read_dependencies()
        dependency_rev = _stable_fingerprint(dependencies) if dependencies else None

        # --- Branch state (read-only, branch-scoped only) ---
        branch_state_rev, branch_state_data, branch_state_limitation = self._read_branch_state(
            timeline_ctx, scope.branch_id
        )

        # --- Evidence and limitations ---
        evidence: list[str] = []
        limitations: list[str] = []

        if source_vid:
            evidence.append("SOURCE_VERSION_BOUND")
        else:
            limitations.append("SOURCE_VERSION_MISSING")

        if canon_rev:
            evidence.append("CANON_REVISION_BOUND")
        else:
            limitations.append("CANON_REVISION_MISSING")

        # Planning: distinguish missing from invalid from empty
        if planning_read_status == _READ_MISSING:
            limitations.append("PLANNING_DATA_MISSING")
        elif planning_read_status == _READ_INVALID:
            limitations.append("PLANNING_DATA_INVALID")
        elif planning_data.get("chapters"):
            evidence.append("PLANNING_DATA_PRESENT")
        else:
            limitations.append("PLANNING_DATA_EMPTY")

        if chapter_plan:
            evidence.append("CHAPTER_PLAN_BOUND")
        else:
            limitations.append("CHAPTER_PLAN_MISSING")

        # World: distinguish missing from invalid from sparse
        if world_read_status == _READ_MISSING:
            limitations.append("WORLD_DATA_MISSING")
        elif world_read_status == _READ_INVALID:
            limitations.append("WORLD_DATA_INVALID")
        elif world_data.get("core_rules") or world_data.get("locations"):
            evidence.append("WORLD_DATA_PRESENT")
        else:
            limitations.append("WORLD_DATA_SPARSE")

        # Characters: distinguish missing from invalid from sparse
        if char_read_status == _READ_MISSING:
            limitations.append("CHARACTER_DATA_MISSING")
        elif char_read_status == _READ_INVALID:
            limitations.append("CHARACTER_DATA_INVALID")
        elif character_data.get("main_characters"):
            evidence.append("CHARACTER_DATA_PRESENT")
        else:
            limitations.append("CHARACTER_DATA_SPARSE")

        # Rolling window: distinguish missing from invalid
        if rolling_read_status == _READ_MISSING:
            limitations.append("ROLLING_WINDOW_MISSING")
        elif rolling_read_status == _READ_INVALID:
            limitations.append("ROLLING_WINDOW_INVALID")

        # Dependencies: distinguish missing from invalid
        if deps_read_status == _READ_MISSING:
            limitations.append("DEPENDENCIES_MISSING")
        elif deps_read_status == _READ_INVALID:
            limitations.append("DEPENDENCIES_INVALID")

        if branch_state_limitation:
            limitations.append(branch_state_limitation)

        # --- Context fingerprint (all authority inputs) ---
        fingerprint_data = {
            "planner_revision": PLANNER_REVISION,
            "project_id": scope.project_id,
            "timeline_id": scope.timeline_id,
            "branch_id": scope.branch_id,
            "chapter_id": chapter_id,
            "source_version_id": source_vid,
            "source_fingerprint": source_fingerprint,
            "canon_revision": canon_rev,
            "planning_revision": planning_rev,
            "chapter_plan_revision": chapter_plan_rev,
            "dependency_revision": dependency_rev,
            "branch_state_revision": branch_state_rev,
            "world_revision": world_rev,
            "character_revision": char_rev,
            "location_revision": location_rev,
            "resource_revision": resource_rev,
            "relationship_revision": relationship_rev,
            "time_state_revision": time_state_rev,
        }
        context_fingerprint = _stable_fingerprint(fingerprint_data)

        # --- Freeze all advisory data recursively ---
        frozen_planning = _freeze(planning_data) if planning_data else ()
        frozen_chapter_plan = _freeze(chapter_plan) if chapter_plan else ()
        frozen_world = _freeze(world_data) if world_data else ()
        frozen_chars = _freeze(character_data) if character_data else ()
        frozen_state = _freeze(branch_state_data) if branch_state_data else ()
        frozen_window = _freeze(rolling_window) if rolling_window else ()
        frozen_deps = _freeze(dependencies) if dependencies else ()

        return NarrativeTurnContextSnapshot(
            schema_version=SCHEMA_VERSION,
            scope=scope,
            chapter_id=chapter_id,
            source_version_id=source_vid,
            source_fingerprint=source_fingerprint,
            canon_revision=canon_rev,
            planning_revision=planning_rev,
            chapter_plan_revision=chapter_plan_rev,
            dependency_revision=dependency_rev,
            branch_state_revision=branch_state_rev,
            world_revision=world_rev,
            character_revision=char_rev,
            location_revision=location_rev,
            resource_revision=resource_rev,
            relationship_revision=relationship_rev,
            time_state_revision=time_state_rev,
            planner_revision=PLANNER_REVISION,
            context_fingerprint=context_fingerprint,
            branch_open=branch_open,
            branch_is_active=branch_is_active,
            planning_data=frozen_planning,
            chapter_plan=frozen_chapter_plan,
            world_data=frozen_world,
            character_data=frozen_chars,
            narrative_state=frozen_state,
            rolling_window=frozen_window,
            dependencies=frozen_deps,
            evidence_codes=tuple(sorted(evidence)),
            limitations=tuple(sorted(limitations)),
        )

    # ------------------------------------------------------------------
    # Branch info (read-only — never calls _create_registry_if_missing)
    # ------------------------------------------------------------------
    def _read_branch_info(
        self, timeline_ctx: TimelineContext, branch_id: str
    ) -> dict[str, Any] | None:
        """Read branch identity and registry without writing.

        Uses _rebuild_registry_from_journal pattern: read events directly,
        compute active branch, without calling get_active_branch_id().
        """
        from system.narrative_branch_store import NarrativeBranchStore

        store = NarrativeBranchStore(self._project_context)

        # get_branch is safe (read-only, returns None on missing).
        branch = store.get_branch(timeline_ctx, branch_id)
        if branch is None:
            return None

        # Rebuild registry from journal events (read-only, no writes).
        # This avoids _create_registry_if_missing which auto-creates.
        registry = self._read_registry_read_only(store, timeline_ctx)

        return {
            "lifecycle_status": branch.lifecycle_status,
            "active_branch_id": registry.get("active_branch_id"),
            "revision": registry.get("revision"),
        }

    def _read_registry_read_only(
        self, store: Any, timeline_ctx: TimelineContext
    ) -> dict[str, Any]:
        """Read registry without auto-creation.

        Try direct file read first; if missing, rebuild from journal events.
        """
        # Try reading registry.json directly.
        registry_path = (
            self._project_context.data_dir
            / "branches"
            / timeline_ctx.timeline_id
            / "registry.json"
        )
        data = _read_json_file(registry_path)
        if data is not None:
            return data

        # Try rebuilding from journal events (read-only).
        try:
            rebuilt = store._rebuild_registry_from_journal(timeline_ctx)
            if rebuilt:
                return rebuilt
        except Exception:
            pass

        # No registry at all — return empty.
        return {"active_branch_id": None, "revision": "0"}

    # ------------------------------------------------------------------
    # Source (read-only — never calls load_versions_index which writes)
    # ------------------------------------------------------------------
    def _read_source(
        self, chapter_id: int
    ) -> tuple[str, str | None]:
        """Read the selected source text and return (fingerprint, version_id).

        Uses list_versions (read-only) instead of get_selected_version (which
        calls load_versions_index → save_versions_index, writing on every call).
        """
        versions_index_path = (
            self._project_context.data_dir
            / "versions"
            / f"chapter_{chapter_id:03d}_versions.json"
        )
        index_data = _read_json_file(versions_index_path)

        if index_data and isinstance(index_data.get("versions"), list):
            versions = index_data["versions"]
            selected_vid = index_data.get("selected_version_id")
            selected_entry = None

            if selected_vid:
                for v in versions:
                    if v.get("version_id") == selected_vid:
                        selected_entry = v
                        break

            if selected_entry is None and versions:
                # Fallback: use the last version.
                selected_entry = versions[-1]

            if selected_entry:
                content = self._read_version_content(chapter_id, selected_entry)
                version_id = str(
                    selected_entry.get("version_label")
                    or f"{selected_entry.get('source_type')}_v{selected_entry.get('version', 0):03d}"
                )
                return _stable_fingerprint(content), version_id

        # No version index — try reading the canonical chapter file.
        content = self._read_chapter_raw(chapter_id)
        return _stable_fingerprint(content), None

    def _read_version_content(
        self, chapter_id: int, version_entry: dict[str, Any]
    ) -> str:
        """Read version payload without writing."""
        source_type = version_entry.get("source_type", "manual")
        version_num = version_entry.get("version", 0)
        base_dir = self._project_context.data_dir / source_type
        filename = f"chapter_{chapter_id:03d}_{source_type}_v{version_num:03d}.json"
        path = base_dir / filename
        data = _read_json_file(path)
        if data is None:
            return ""
        return str(
            data.get("manual_text")
            or data.get("edited_text")
            or data.get("draft_text")
            or ""
        )

    def _read_chapter_raw(self, chapter_id: int) -> str:
        path = self._project_context.chapters_dir / f"chapter_{chapter_id:03d}.md"
        text = _read_text_file(path)
        return text if text is not None else ""

    # ------------------------------------------------------------------
    # Canon revision (read-only — never calls _canon_index which writes)
    # ------------------------------------------------------------------
    def _read_canon_revision(self, chapter_id: int) -> str | None:
        """Read the active canon revision ID without auto-initialization.

        Reads data/canon_versions/chapter_NNN/index.json directly.
        Does NOT call RevisionService.active_canon() which may create files.
        """
        canon_index_path = (
            self._project_context.data_dir
            / "canon_versions"
            / f"chapter_{chapter_id:03d}"
            / "index.json"
        )
        data = _read_json_file(canon_index_path)
        if data is None:
            return None

        versions = data.get("versions")
        if not isinstance(versions, list):
            return None

        for v in versions:
            if isinstance(v, dict) and v.get("active"):
                canon_id = v.get("canon_version_id") or v.get("version_id")
                if canon_id:
                    return str(canon_id)

        # No active version — return the last one if any.
        if versions:
            last = versions[-1]
            if isinstance(last, dict):
                canon_id = last.get("canon_version_id") or last.get("version_id")
                if canon_id:
                    return str(canon_id)

        return None

    # ------------------------------------------------------------------
    # Planning (read-only raw JSON — no _normalize, no _now, no _id)
    # ------------------------------------------------------------------
    def _read_planning_raw(self) -> tuple[dict[str, Any], str]:
        """Read story_planning.json directly without _normalize().

        _normalize() calls _now() and _id() which are non-deterministic.
        We read the raw JSON file instead.

        Returns (data, status) where status is "ok", "missing", or "invalid".
        Missing and invalid both yield data={} but different status, so
        the binder can emit distinct limitations.
        """
        path = self._project_context.data_dir / "story_planning.json"
        status, data = _read_json_strict(path)
        return (data if data is not None else {}, status)

    def _find_chapter_plan(
        self, planning_data: dict[str, Any], chapter_id: int
    ) -> dict[str, Any]:
        chapters = planning_data.get("chapters", [])
        if not isinstance(chapters, list):
            return {}
        for ch in chapters:
            if not isinstance(ch, dict):
                continue
            num = ch.get("chapter_number", ch.get("chapter_id"))
            try:
                if int(num) == chapter_id:
                    return dict(ch)
            except (TypeError, ValueError):
                continue
        return {}

    # ------------------------------------------------------------------
    # World / characters (read-only)
    # ------------------------------------------------------------------
    def _read_world(self) -> tuple[dict[str, Any], str]:
        path = self._project_context.data_dir / "world_bible.json"
        status, data = _read_json_strict(path)
        return (data if data is not None else {}, status)

    def _read_characters(self) -> tuple[dict[str, Any], str]:
        path = self._project_context.data_dir / "characters.json"
        status, data = _read_json_strict(path)
        return (data if data is not None else {}, status)

    def _extract_relationships(self, character_data: dict[str, Any]) -> list[Any]:
        """Extract relationship data from character data."""
        rels: list[Any] = []
        for key in ("main_characters", "supporting_characters"):
            chars = character_data.get(key, [])
            if not isinstance(chars, list):
                continue
            for ch in chars:
                if not isinstance(ch, dict):
                    continue
                rel = ch.get("relationships") or ch.get("relations")
                if rel:
                    rels.append(rel)
        return rels

    # ------------------------------------------------------------------
    # Rolling window / dependencies (read-only)
    # ------------------------------------------------------------------
    def _read_rolling_window(self) -> tuple[dict[str, Any], str]:
        path = self._project_context.rolling_window_path
        status, data = _read_json_strict(path)
        return (data if data is not None else {}, status)

    def _read_dependencies(self) -> tuple[dict[str, Any], str]:
        path = self._project_context.planning_dependencies_path
        status, data = _read_json_strict(path)
        return (data if data is not None else {}, status)

    # ------------------------------------------------------------------
    # Branch state (read-only, branch-scoped only — no legacy flat path)
    # ------------------------------------------------------------------
    def _read_branch_state(
        self, timeline_ctx: TimelineContext, branch_id: str
    ) -> tuple[str | None, dict[str, Any] | None, str | None]:
        """Read branch-scoped narrative state.

        Reads ONLY:
            data/narrative_memory/state/{timeline_id}/{branch_id}/current.json

        Does NOT read the legacy flat path:
            data/narrative_memory/state/current.json

        Returns (revision, state_data, limitation_code).
        """
        # Branch-scoped state path (the only authorized path).
        state_path = (
            self._project_context.narrative_state_dir
            / timeline_ctx.timeline_id
            / branch_id
            / "current.json"
        )
        data = _read_json_file(state_path)

        if data is None:
            return None, None, "BRANCH_STATE_UNAVAILABLE"

        # Verify scope fields in the record.
        rec_project = data.get("project_id")
        rec_timeline = data.get("timeline_id")
        rec_branch = data.get("branch_id")

        if rec_project and rec_project != self._project_id:
            return None, None, "BRANCH_STATE_PROJECT_MISMATCH"
        if rec_timeline and rec_timeline != timeline_ctx.timeline_id:
            return None, None, "BRANCH_STATE_TIMELINE_MISMATCH"
        if rec_branch and rec_branch != branch_id:
            return None, None, "BRANCH_STATE_BRANCH_MISMATCH"

        revision_value = data.get("revision")
        if data.get("schema_version") == SCHEMA_VERSION:
            if (
                rec_project != self._project_id
                or rec_timeline != timeline_ctx.timeline_id
                or rec_branch != branch_id
                or not isinstance(revision_value, str)
                or not revision_value
                or not isinstance(data.get("applied_result_fingerprints"), list)
                or revision_value != branch_state_content_revision(data)
            ):
                return None, None, "BRANCH_STATE_INVALID"
        revision = revision_value if isinstance(revision_value, str) and revision_value else _stable_fingerprint(data)
        return revision, data, None
