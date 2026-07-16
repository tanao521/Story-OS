"""Small, static ownership map for public HTTP routes.

This is intentionally not a gateway and does not register routes.  It makes
the compatibility obligations explicit while the existing FastAPI handlers
remain the transport layer.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteOwnership:
    path: str
    capability: str
    handler: str
    read_or_write: str
    status: str = "canonical"
    canonical_path: str = ""
    response_mapper: str = ""
    deprecation_note: str = ""
    frontend_callers: tuple[str, ...] = ()
    removal_ready: bool = False


CANONICAL_ROUTES: tuple[RouteOwnership, ...] = (
    RouteOwnership("/api/planning/overview", "planning.read", "PlanningService", "read"),
    RouteOwnership("/api/planning/{kind}", "planning.mutate", "PlanningMutationService", "write"),
    RouteOwnership("/api/evaluations", "evaluation.report", "EvaluationService", "read_or_write"),
    RouteOwnership("/api/evaluations/planning", "evaluation.planning", "PlanningEvaluationService", "read_or_write"),
    RouteOwnership("/api/revisions", "revision.request", "RevisionService", "read_or_write"),
    RouteOwnership("/api/versions", "version.read", "VersionManager compatibility reader", "read"),
    RouteOwnership("/api/versions/select", "version.selection", "VersionWriterFacade compatibility path", "write"),
    RouteOwnership("/api/narrative-memory/context-preview", "context.preview", "ContextAssemblyService", "read"),
)

COMPATIBILITY_ROUTES: tuple[RouteOwnership, ...] = (
    RouteOwnership(
        "/api/quality-report", "evaluation.legacy_quality_read", "LegacyEvaluationAdapter", "read",
        status="compatibility", canonical_path="/api/evaluations", response_mapper="legacy_quality_view",
        deprecation_note="Legacy report view only; no report or index is written.", frontend_callers=("web/static/app.js",),
    ),
    RouteOwnership(
        "/api/continuity-report", "evaluation.legacy_continuity_read", "LegacyEvaluationAdapter", "read",
        status="compatibility", canonical_path="/api/evaluations", response_mapper="legacy_continuity_view",
        deprecation_note="Legacy report view only; no report or index is written.", frontend_callers=("web/static/app.js",),
    ),
    RouteOwnership(
        "/api/planning/next-chapter", "planning.next_chapter_legacy", "PlanningMutationService", "read_or_write",
        status="compatibility", canonical_path="/api/planning/overview", response_mapper="legacy_next_chapter_view",
        deprecation_note="Retains the existing next-chapter payload while routing writes through PlanningMutationService.", frontend_callers=("web/static/app.js",),
    ),
    RouteOwnership(
        "/api/quality-check", "evaluation.legacy_quality_analyzer", "quality_check_command analyzer adapter", "write",
        status="deprecated_internal", canonical_path="/api/evaluations", response_mapper="legacy_quality_check_response",
        deprecation_note="Existing analyzer producer retained for old report compatibility; hidden from primary evaluation workflow.", frontend_callers=(),
    ),
    RouteOwnership(
        "/api/continuity-check", "evaluation.legacy_continuity_analyzer", "continuity analyzer adapter", "write",
        status="deprecated_internal", canonical_path="/api/evaluations", response_mapper="legacy_continuity_check_response",
        deprecation_note="Existing analyzer producer retained for old report compatibility; hidden from primary evaluation workflow.", frontend_callers=(),
    ),
)


def compatibility_route(path: str) -> RouteOwnership | None:
    return next((item for item in COMPATIBILITY_ROUTES if item.path == path), None)


def compatibility_headers(path: str) -> dict[str, str]:
    item = compatibility_route(path)
    if item is None:
        return {}
    return {
        "X-StoryOS-Compatibility": item.status,
        "X-StoryOS-Canonical-Endpoint": item.canonical_path,
    }
