"""HTTP boundary for Stage 14.1 planning control operations."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.project_context import get_project_context
from planning_engine import PlanningControlError, PlanningControlService, PlanningDependencyService
from planning_engine.rolling_service import RollingWindowService
from web.view_models import api_error, api_ok

router = APIRouter(prefix="/api/planning-control", tags=["planning-control"])


def service() -> PlanningControlService:
    return PlanningControlService(get_project_context())


def rolling() -> RollingWindowService:
    return RollingWindowService(get_project_context())


def dependencies() -> PlanningDependencyService:
    return PlanningDependencyService(get_project_context())


def failure(error: PlanningControlError, status: int = 409) -> JSONResponse:
    if error.code.endswith("NOT_FOUND"):
        status = 404
    if error.code in {"ROLLING_WINDOW_REVISION_CONFLICT", "ROLLING_PREVIEW_STALE"}:
        status = 409
    return JSONResponse(api_error(str(error), [error.code], details=error.details), status_code=status)


async def body(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except ValueError:
        return {}
    if not isinstance(value, dict):
        raise PlanningControlError("PLANNING_CONTROL_NOT_FOUND", "JSON object is required")
    return value


def dependency_failure(error: PlanningControlError) -> JSONResponse:
    if error.code.endswith("NOT_FOUND") or error.code in {"PLANNING_DEPENDENCY_SOURCE_NOT_FOUND", "PLANNING_CUSTOM_NODE_NOT_FOUND"}:
        status = 404
    elif error.code in {"PLANNING_DEPENDENCY_SELF_REFERENCE", "PLANNING_DEPENDENCY_INVALID_NODE", "PLANNING_DEPENDENCY_INVALID_TYPE", "PLANNING_DEPENDENCY_INVALID_TRANSITION"}:
        status = 400
    else:
        status = 409
    return JSONResponse(api_error(str(error), [error.code], details=error.details), status_code=status)


@router.get("/dependencies")
def get_dependencies(request: Request) -> dict[str, Any]:
    return api_ok(result=dependencies().list_dependencies(dict(request.query_params)))


@router.get("/dependencies/health")
def dependency_health() -> dict[str, Any]:
    return api_ok(result=dependencies().health())


@router.post("/dependencies/validate")
def validate_dependencies() -> dict[str, Any]:
    return api_ok(result=dependencies().validate())


@router.get("/dependencies/upstream")
def dependency_upstream(node_type: str, node_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok(result=dependencies().related(node_type, node_id, "upstream")))
    except PlanningControlError as error:
        return dependency_failure(error)


@router.get("/dependencies/downstream")
def dependency_downstream(node_type: str, node_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok(result=dependencies().related(node_type, node_id, "downstream")))
    except PlanningControlError as error:
        return dependency_failure(error)


@router.post("/dependencies")
async def create_dependency(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("依赖关系已保存；它不会安排或移动章节。", {"dependency": dependencies().create_dependency(await body(request))}), status_code=201)
    except PlanningControlError as error:
        return dependency_failure(error)


@router.get("/dependencies/{dependency_id}")
def get_dependency(dependency_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok(result={"dependency": dependencies().get_dependency(dependency_id)}))
    except PlanningControlError as error:
        return dependency_failure(error)


@router.put("/dependencies/{dependency_id}")
async def update_dependency(dependency_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("依赖关系已更新。", {"dependency": dependencies().update_dependency(dependency_id, await body(request))}))
    except PlanningControlError as error:
        return dependency_failure(error)


@router.post("/dependencies/{dependency_id}/transition")
async def transition_dependency(dependency_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("依赖关系状态已更新。", {"dependency": dependencies().transition_dependency(dependency_id, await body(request))}))
    except PlanningControlError as error:
        return dependency_failure(error)


@router.get("/dependency-nodes")
def dependency_nodes() -> dict[str, Any]:
    return api_ok(result=dependencies().list_custom_nodes())


@router.post("/dependency-nodes")
async def create_dependency_node(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("自定义规划节点已创建。", {"node": dependencies().create_custom_node(await body(request))}), status_code=201)
    except PlanningControlError as error:
        return dependency_failure(error)


@router.put("/dependency-nodes/{node_id}")
async def update_dependency_node(node_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("自定义规划节点已更新。", {"node": dependencies().update_custom_node(node_id, await body(request))}))
    except PlanningControlError as error:
        return dependency_failure(error)


@router.post("/dependency-nodes/{node_id}/transition")
async def transition_dependency_node(node_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("自定义规划节点状态已更新。", {"node": dependencies().transition_custom_node(node_id, await body(request))}))
    except PlanningControlError as error:
        return dependency_failure(error)


@router.get("/rolling-window")
def rolling_window() -> dict[str, Any]:
    return api_ok(result=rolling().describe())


@router.get("/rolling-window/health")
def rolling_window_health() -> dict[str, Any]:
    return api_ok(result=rolling().check_window_health())


@router.post("/rolling-window/initialize")
async def initialize_rolling_window(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("滚动规划窗口已初始化；其中内容仅代表未来创作意图。", {"window": rolling().initialize(await body(request))}), status_code=201)
    except (PlanningControlError, ValueError) as error:
        return failure(error if isinstance(error, PlanningControlError) else PlanningControlError(str(error)), 422)


@router.put("/rolling-window/configuration")
async def update_rolling_configuration(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("滚动窗口配置已保存。", {"window": rolling().update_configuration(await body(request))}))
    except (PlanningControlError, ValueError) as error:
        return failure(error if isinstance(error, PlanningControlError) else PlanningControlError(str(error)), 422)


@router.post("/rolling-window/roll-forward")
def roll_forward_preview() -> JSONResponse:
    try:
        return JSONResponse(api_ok("滚动窗口前推预览已生成；尚未写入任何变更。", {"preview": rolling().roll_forward_preview(), "applied": False}))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/roll-forward/confirm")
async def confirm_roll_forward_v2(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("滚动窗口已由作者确认前推。", rolling().confirm_roll_forward(await body(request))))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/roll-forward/confirm/legacy")
def confirm_roll_forward() -> JSONResponse:
    try:
        return JSONResponse(api_ok("滚动窗口已由作者确认前推。", rolling().confirm_roll_forward()))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/roll-forward/legacy")
async def roll_forward(request: Request) -> JSONResponse:
    try:
        payload = await body(request)
        return JSONResponse(api_ok("滚动窗口预览已生成。" if not payload.get("author_confirm") else "滚动窗口已由作者确认前推。", rolling().roll_forward(payload)))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/reanchor")
async def reanchor_lifecycle(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("滚动窗口重新绑定预览或确认操作已完成。", rolling().reanchor(await body(request))))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/reanchor/legacy")
async def reanchor(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("滚动窗口已重新锚定。", {"window": rolling().reanchor(await body(request))}))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/refresh-far-horizon")
def refresh_far_horizon() -> JSONResponse:
    try:
        return JSONResponse(api_ok("远景摘要已刷新。", {"window": rolling().refresh_far_horizon()}))
    except PlanningControlError as error:
        return failure(error)


@router.post("/rolling-window/refresh")
async def refresh_rolling_sources_v2(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("滚动窗口来源与远景摘要已刷新；章节槽位未被改写。", {"window": rolling().refresh_sources(await body(request))}))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/refresh/legacy")
def refresh_rolling_sources() -> JSONResponse:
    try:
        return JSONResponse(api_ok("滚动窗口来源与远景摘要已刷新；章节槽位未被改写。", {"window": rolling().refresh_sources()}))
    except PlanningControlError as error:
        return failure(error, 422)


@router.get("/rolling-window/slots")
def list_rolling_slots() -> JSONResponse:
    try:
        return JSONResponse(api_ok(result=rolling().list_slots()))
    except PlanningControlError as error:
        return failure(error)


@router.post("/rolling-window/slots")
async def create_rolling_slot(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("未来章节槽位已创建；它不是当前执行计划。", {"slot": rolling().create_slot(await body(request))}), status_code=201)
    except PlanningControlError as error:
        return failure(error, 422)


@router.put("/rolling-window/slots/{slot_id}")
async def update_rolling_slot(slot_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("未来章节槽位已保存。", {"slot": rolling().update_slot(slot_id, await body(request))}))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/slots/{slot_id}/transition")
async def transition_rolling_slot(slot_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("槽位状态已更新。", {"slot": rolling().transition_slot(slot_id, str((await body(request)).get("status", "")))}))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/slots/{slot_id}/cancel")
async def cancel_rolling_slot_v2(slot_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("未来章节槽位已取消，历史记录已保留。", {"slot": rolling().cancel_slot(slot_id, await body(request))}))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/slots/{slot_id}/cancel/legacy")
def cancel_rolling_slot(slot_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok("未来章节槽位已取消，历史记录已保留。", {"slot": rolling().cancel_slot(slot_id)}))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/slots/{slot_id}/move")
async def move_rolling_slot(slot_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("槽位位置已更新。", {"slot": rolling().move_slot(slot_id, int((await body(request)).get("planned_chapter_number", 0) or 0))}))
    except (PlanningControlError, ValueError) as error:
        return failure(error if isinstance(error, PlanningControlError) else PlanningControlError("CHAPTER_SLOT_POSITION_CONFLICT"), 422)


@router.post("/rolling-window/slots/{slot_id}/adopt-blueprint")
async def adopt_blueprint_slot(slot_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("蓝图参考已由作者采用到未来槽位。", {"slot": rolling().adopt_blueprint_suggestion(slot_id, int((await body(request)).get("planned_chapter_number", 0) or 0))}))
    except (PlanningControlError, ValueError) as error:
        return failure(error if isinstance(error, PlanningControlError) else PlanningControlError("PLANNING_SOURCE_NOT_FOUND"), 422)


@router.post("/rolling-window/locks")
async def lock_rolling_entity(request: Request) -> JSONResponse:
    try:
        value = await body(request)
        return JSONResponse(api_ok("滚动窗口字段已锁定。", {"lock": rolling().lock(str(value.get("entity_type", "")), str(value.get("entity_id", "")), str(value.get("field", "*")), str(value.get("reason", "")))}), status_code=201)
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/rolling-window/locks/{lock_id}/release")
def release_rolling_lock(lock_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok("滚动窗口字段已解锁。", {"lock": rolling().release_lock(lock_id)}))
    except PlanningControlError as error:
        return failure(error)


@router.get("/overview")
def overview() -> dict[str, Any]:
    return api_ok(result=service().overview())


@router.get("/strategy")
def get_strategy() -> dict[str, Any]:
    return api_ok(result={"strategy": service().get_strategy()})


@router.put("/strategy")
async def save_strategy(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("长期战略已保存。", {"strategy": service().save_strategy(await body(request))}))
    except PlanningControlError as error:
        return failure(error)


@router.get("/milestones")
def list_milestones() -> dict[str, Any]:
    return api_ok(result={"milestones": service().list("milestones")})


@router.post("/milestones")
async def create_milestone(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("里程碑已创建。", {"milestone": service().create("milestones", await body(request))}), status_code=201)
    except PlanningControlError as error:
        return failure(error, 422)


@router.get("/milestones/{milestone_id}")
def get_milestone(milestone_id: str) -> JSONResponse:
    value = service().get("milestones", milestone_id)
    return JSONResponse(api_ok(result={"milestone": value})) if value else failure(PlanningControlError("MILESTONE_NOT_FOUND"))


@router.put("/milestones/{milestone_id}")
async def update_milestone(milestone_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("里程碑已保存。", {"milestone": service().update("milestones", milestone_id, await body(request))}))
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/milestones/{milestone_id}/transition")
async def transition_milestone(milestone_id: str, request: Request) -> JSONResponse:
    try:
        payload = await body(request)
        return JSONResponse(api_ok("里程碑状态已由作者确认。", {"milestone": service().update("milestones", milestone_id, {"status": payload.get("status"), **({"replacement_milestone_id": payload["replacement_milestone_id"]} if "replacement_milestone_id" in payload else {})})}))
    except PlanningControlError as error:
        return failure(error, 422)


@router.delete("/milestones/{milestone_id}")
def cancel_milestone(milestone_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok("里程碑已取消，历史记录保留。", {"milestone": service().delete_milestone(milestone_id)}))
    except PlanningControlError as error:
        return failure(error)


def _contracts(path: str, collection: str, result_key: str) -> None:
    @router.get(f"/{path}")
    def list_contracts() -> dict[str, Any]:
        return api_ok(result={result_key: service().list(collection)})

    @router.post(f"/{path}")
    async def create_contract(request: Request) -> JSONResponse:
        try:
            return JSONResponse(api_ok("契约已保存。", {result_key[:-1] if result_key.endswith("s") else "contract": service().create(collection, await body(request))}), status_code=201)
        except PlanningControlError as error:
            return failure(error, 422)

    @router.get(f"/{path}/{{contract_id}}")
    def get_contract(contract_id: str) -> JSONResponse:
        value = service().get(collection, contract_id)
        return JSONResponse(api_ok(result={"contract": value})) if value else failure(PlanningControlError("VOLUME_CONTRACT_NOT_FOUND" if collection == "volume_contracts" else "PHASE_CONTRACT_NOT_FOUND"))

    @router.put(f"/{path}/{{contract_id}}")
    async def update_contract(contract_id: str, request: Request) -> JSONResponse:
        try:
            return JSONResponse(api_ok("契约已保存。", {"contract": service().update(collection, contract_id, await body(request))}))
        except PlanningControlError as error:
            return failure(error, 422)


_contracts("volume-contracts", "volume_contracts", "volume_contracts")
_contracts("phase-contracts", "phase_contracts", "phase_contracts")


@router.get("/locks")
def list_locks() -> dict[str, Any]:
    return api_ok(result={"locks": service().overview()["locks"]})


@router.post("/locks")
async def create_lock(request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("规划字段已锁定。", {"lock": service().lock(await body(request))}), status_code=201)
    except PlanningControlError as error:
        return failure(error, 422)


@router.post("/locks/{lock_id}/release")
def release_lock(lock_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok("规划字段已解锁。", {"lock": service().release_lock(lock_id)}))
    except PlanningControlError as error:
        return failure(error)


@router.get("/conflicts")
def list_conflicts() -> dict[str, Any]:
    return api_ok(result={"conflicts": service().overview()["conflicts"]})


@router.post("/conflicts/scan")
def scan_conflicts() -> JSONResponse:
    try:
        return JSONResponse(api_ok("已完成低风险来源冲突扫描。", {"conflicts": service().scan_conflicts()}))
    except PlanningControlError as error:
        return failure(error)


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(conflict_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("冲突已按作者选择处理。", {"conflict": service().resolve_conflict(conflict_id, await body(request))}))
    except PlanningControlError as error:
        return failure(error, 422)


@router.get("/versions")
def list_versions() -> dict[str, Any]:
    return api_ok(result={"versions": service().list_versions()})


@router.get("/versions/{version_id}")
def get_version(version_id: str) -> JSONResponse:
    value = service().get_version(version_id)
    return JSONResponse(api_ok(result={"version": value})) if value else failure(PlanningControlError("PLANNING_VERSION_NOT_FOUND"))


@router.post("/versions/{version_id}/restore")
async def restore_version_v2(version_id: str, request: Request) -> JSONResponse:
    try:
        return JSONResponse(api_ok("规划控制层已恢复；窗口 Health 已按当前项目重新计算。", service().restore_version(version_id, await body(request))))
    except PlanningControlError as error:
        return failure(error)


@router.post("/versions/{version_id}/restore/legacy")
def restore_version(version_id: str) -> JSONResponse:
    try:
        return JSONResponse(api_ok("规划控制层已恢复；蓝图与章节计划未改动。", {"overview": service().restore_version(version_id)}))
    except PlanningControlError as error:
        return failure(error)
