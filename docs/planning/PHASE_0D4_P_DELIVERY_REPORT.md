# Phase 0D4-P Delivery Report — Simulator Narrative Turn Loop Preflight & Architecture Map

## 1. 阶段结论

```text
Phase 0D4-P: PASSED
Simulator Narrative Turn Architecture: READY FOR OWNER REVIEW
Production implementation: NOT STARTED
Phase 0D4-A: NOT ENTERED
```

依据：基于真实仓库只读审计，已完整映射 Project / Timeline / Canon / Chapter /
Planning / Evaluation / Memory 架构；明确 Narrative Turn 权威对象与三层边界
（preview / confirmed branch-local / committed canonical）；明确分支隔离与
Chroma 过滤策略；明确 Turn 如何进入章节整理而不绕过既有 commit；输出状态机、
API 草案、错误码、实施切片与风险矩阵。本阶段未修改任何生产代码。

## 2. Owner Decision 上下文

```text
Phase 0D3C4-B1 sealed.
Continue Provider B2: NOT AUTHORIZED.
Production Live: DEFAULT-OFF.
Canary: NOT AUTHORIZED.
Real Provider calls: PROHIBITED.
Real Token / Cost: 0.
Next product direction: SIMULATOR CORE LOOP.
```

本阶段为只读审计 + 设计输出，未实现 Narrative Turn，未增加生产写接口，
未调用 Provider。

## 3. 冲突检查

启动前搜索 `docs/planning/PHASE_0D4*.md`，确认仓库无既有 `0D4` 阶段文档。
本阶段为首个 `0D4` 阶段，无编号冲突，未覆盖任何已有文档。

## 4. 当前架构地图（真实文件、类、函数、接口、数据路径）

### 4.1 项目与时间线

| 能力 | 当前状态 | 文件 |
| --- | --- | --- |
| `ProjectContext` | frozen dataclass；**项目隔离，无 `timeline_id` 字段** | [core/project_context.py](file:///d:/novel/StoryOS/story-os-demo/core/project_context.py) |
| 活动项目解析 | explicit root → `.story_os/config.json` `active_project` → cwd | [core/project_context.py](file:///d:/novel/StoryOS/story-os-demo/core/project_context.py) |
| Timeline 概念 | **仅元数据**；UI 暴露 `timeline_id="main"`，无 create/switch/archive API | [web/static/simulator-context-navigator.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-context-navigator.js) |
| Branch 概念 | **不存在**（grep `branch_id` / `create_branch` 无生产命中） | — |
| Canon revision | append-only 按章节 `data/canon_versions/chapter_NNN/`，带 `active` 标记 | [system/revision_service.py](file:///d:/novel/StoryOS/story-os-demo/system/revision_service.py) |
| 记录中的 project/timeline 字段 | panel run、live audit、reconciliation 已有 `project_id` + `timeline_id` | [core/contracts/model_persona_panel_execution.py](file:///d:/novel/StoryOS/story-os-demo/core/contracts/model_persona_panel_execution.py), [system/provider_usage_reconciliation.py](file:///d:/novel/StoryOS/story-os-demo/system/provider_usage_reconciliation.py) |

**关键缺口：** `ProjectContext` 不携带 `timeline_id`，`data/` 下所有路径为
project-scoped 而非 timeline-scoped。真实分支模型需要 timeline-scoped 子目录
或在每条记录加 `timeline_id` / `branch_id` 字段并强制查询过滤。

### 4.2 章节与版本

| 概念 | 当前状态 | 文件 |
| --- | --- | --- |
| Source 类型 | `manual`、`edited`、`draft`、`selected` 枚举 | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py) |
| 版本文件 | `data/{manual,edited,draft}/chapter_NNN_*.json`；选中指针在 `data/versions/chapter_NNN_versions.json` | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py) |
| 正式章节 | `data/chapters/chapter_NNN.md` | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py) |
| Commit 入口 | `ChapterCommitService.commit_chapter()`，带 idempotency key、snapshot、rollback、post-commit tasks | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py) |
| 幂等性 | `commit_key = sha256(project_id:chapter_id:source_hash:source_version_id:commit)`；`CommitRunStore` 跨进程 | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py) |
| Canon 更新 | `RevisionService.create_and_apply_revision()` 在 commit 事务内 | [system/chapter_commit_service.py](file:///d:/novel/StoryOS/story-os-demo/system/chapter_commit_service.py) |
| 原子写入 | `DataStore.write_json(backup=True)`；`safe_write` 模块 | [system/data_store.py](file:///d:/novel/StoryOS/story-os-demo/system/data_store.py), [system/safe_write.py](file:///d:/novel/StoryOS/story-os-demo/system/safe_write.py) |

**复用判定：** commit pipeline 是章节最终化的**唯一正式入口**。Narrative
Turn 章节整理 MUST 经由 `ChapterCommitService`，绝不绕过。

### 4.3 规划系统

| 对象 | 用途 | Turn 复用 |
| --- | --- | --- |
| `story_planning.json` (v2.0) | volumes、phases、chapters、plot_threads、character_arcs、foreshadowing、conflicts、climaxes | chapters/plot_threads/foreshadowing 为 Turn context 的**读取输入** |
| `next_chapter_plan.json` | 下一章 goal、conflict、climax、characters、world rules | Turn context binding 的**读取输入** |
| `data/planning_control/rolling_window.json` | near/mid/far horizon slots，**preview → confirm → operation_id** 模式 | Turn preview/confirm 的**直接模式复用** |
| `data/planning_control/dependencies.json` | 依赖图、循环检测 | feasibility 的**读取输入**（阻断依赖） |
| `data/planning_control/narrative_schedules.json` | 手动调度、revision conflict、replay | **读取输入**；scheduling service 模式复用 |
| `PlanningControlService` | `save_rolling_window(expected_window_revision, operation_id)`、preview 过期、replay | Turn idempotency/recovery 的**直接复用** |

**关键发现：** `RollingWindowService` 已实现
`preview → confirm → operation_id → revision conflict → replay` 模式。Narrative
Turn 应复用该模式，不另起炉灶。

### 4.4 评估系统

| 能力 | 只读？ | 权威 | 文件 |
| --- | --- | --- | --- |
| `EvaluationService` | 仅写 `data/evaluations/` | 确定性聚合器 | [evaluation_engine/service.py](file:///d:/novel/StoryOS/story-os-demo/evaluation_engine/service.py) |
| `ReaderSimulatorService` | 写 run record | 确定性规则，`EVALUATOR_VERSION="reader-rule-v1"` | [system/reader_simulator.py](file:///d:/novel/StoryOS/story-os-demo/system/reader_simulator.py) |
| `ModelPersonaPanelReviewService` | 只读聚合 | 确定性；model supplement 非权威 | [system/model_persona_panel_review_service.py](file:///d:/novel/StoryOS/story-os-demo/system/model_persona_panel_review_service.py) |
| Quality report | source hash 变化即 stale | 确定性 | [system/quality_checker.py](file:///d:/novel/StoryOS/story-os-demo/system/quality_checker.py) |

**权威边界：**
- **确定性**评估结果（continuity、canon conflict、dependency blocker、来自 `characters.json` 的角色能力、来自 `world_bible.json` 的世界规则）→ 可作为 feasibility **证据**。
- **Reader Persona** 主观反馈 → **不得**作为世界状态权威，仅 advisory。
- **Model supplement**（panel run model 输出）→ **不得**绕过确定性规则。

### 4.5 记忆与检索

| 能力 | Timeline 隔离 | 文件 |
| --- | --- | --- |
| `vector_index_lifecycle.index_chapter()` | **是** — 接受 `timeline_id`、`canon_revision_id`、`project_id`；manifest 强制 | [system/vector_index_lifecycle.py](file:///d:/novel/StoryOS/story-os-demo/system/vector_index_lifecycle.py) |
| `vector_memory.build_or_update_index()` (legacy) | **否** — 无 `timeline_id` / `project_id` 过滤；索引 `data/chapters/` 下全部 | [system/vector_memory.py](file:///d:/novel/StoryOS/story-os-demo/system/vector_memory.py) |
| `NarrativeMemoryService` | 仅 project-scoped；event 按 `chapter_id` 键化，无 `timeline_id` | [system/narrative_memory_service.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_memory_service.py) |
| `NarrativeMemoryService.extract()` | 读取 `active_canon(chapter_id)`；产出 `unreviewed` 候选 | [system/narrative_memory_service.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_memory_service.py) |
| `NarrativeMemoryService.project()` | 聚合 `confirmed` / `corrected` 事件为状态桶 | [system/narrative_memory_service.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_memory_service.py) |
| `NarrativeMemoryService.invalidate_from(chapter)` | 自 chapter 起标记事件 `active=False` | [system/narrative_memory_service.py](file:///d:/novel/StoryOS/story-os-demo/system/narrative_memory_service.py) |

**关键风险：** `memory_repair_service.py` 仍调用 legacy
`vector_memory.build_or_update_index()`，无 timeline 过滤。这是 Chroma 过滤
绕过向量 — 见风险矩阵。

**复用判定：** `NarrativeMemoryService` 已提供
event/state/snapshot/conflict/invalidate 语义。confirmed Turn 应产出
`NarrativeMemoryService` 兼容的 event record（branch-local），chapter commit
应触发既有 `extract()` → `project()` 流程。

### 4.6 Web 模拟器 UI

| 元素 | 当前状态 | 文件 |
| --- | --- | --- |
| Shell | 单页 `index.html`，mode buttons（`data-storyos-mode="simulator"`） | [web/templates/index.html](file:///d:/novel/StoryOS/story-os-demo/web/templates/index.html) |
| Simulator section | `#simulator-panel-review`，含 context navigator、panel run planner、live consent | [web/templates/index.html](file:///d:/novel/StoryOS/story-os-demo/web/templates/index.html) |
| Context navigator | project/timeline/chapter/source/run selects；URL state；AbortController；stale-response guard | [web/static/simulator-context-navigator.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-context-navigator.js) |
| Panel run planner | Mock-only drawer；Plan → Confirm → Run；duplicate-submit disabled | [web/static/simulator-panel-run.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-panel-run.js) |
| Live consent | dialog；default-off capability；仅 ticket creation | [web/static/simulator-live-consent.js](file:///d:/novel/StoryOS/story-os-demo/web/static/simulator-live-consent.js) |
| API helper | `storyosApiGet` / `storyosApiPost`，带 `AbortController`、generation counter | [web/static/app.js](file:///d:/novel/StoryOS/story-os-demo/web/static/app.js) |

**复用判定：** Narrative Turn UI 应为**现有 Simulator Shell 内的新工作区**
（非新页面），复用 context navigator、`storyosApiGet/Post`、AbortController、
generation-counter 模式。推荐新挂载点为 `simulator-narrative-turn.js`。

## 5. 可复用能力

| 能力 | Turn 复用 | 条件 |
| --- | --- | --- |
| `ProjectContext` + `bind_project_context` | 请求级 project binding | 须为 branch isolation 扩展 `timeline_id` |
| `ChapterCommitService` | 章节整理入口 | Turn compile MUST 经由此 |
| `RevisionService` | canon revision 创建 | 仅经由 commit |
| `RollingWindowService` preview/confirm/operation_id | Turn preview/confirm/idempotency | 直接模式复用 |
| `PlanningControlService` | operation log、revision conflict、replay | 直接复用 |
| `NarrativeMemoryService` | event record、state projection、invalidate | 扩展 `branch_id` / `timeline_id` |
| `vector_index_lifecycle` | 带 timeline 过滤的 Chroma 索引 | 仅此 API；**绝不** legacy `vector_memory.build_or_update_index` |
| `ModelPersonaPanelReviewService` | 只读 review 聚合 | advisory only，非权威 |
| `ReaderSimulatorService` | 确定性 reader feedback | advisory only |
| `DataStore` + `safe_write` | 原子 JSON 写入 | 直接复用 |
| `storyosApiGet/Post` + AbortController + generation | 前端请求保护 | 直接复用 |

## 6. Narrative Turn Loop 缺口

| 缺口 | 严重度 | 备注 |
| --- | --- | --- |
| `ProjectContext` 无 `timeline_id` | **blocking** | 无此字段分支隔离不可实现 |
| 无 branch create/switch/archive API | **blocking** | 0D4-E 必须新增 |
| 无 `NarrativeTurn` / `NarrativeActionOption` / `NarrativeTurnResult` 契约 | **blocking** | 0D4-A 必须新增 |
| 无确定性 action feasibility engine | **blocking** | 0D4-B 必须新增；规则来自 `world_bible.json` / `characters.json` / `world_rules.json` |
| 无 branch-local event log | **blocking** | `NarrativeMemoryService` 仅 project-scoped |
| Legacy `vector_memory.build_or_update_index` 无 timeline 过滤 | **high** | 分支场景须弃用/阻断 |
| 无 Turn → chapter compile 接线 | **blocking** | 0D4-F 必须接至 `ChapterCommitService` |
| 无 Turn UI 工作区 | **blocking** | 0D4-C 须新增（须先经 frontend-design skill） |
| 无 `NarrativeTurnPlan` store | **blocking** | 0D4-A 须新增 append-only store |

## 7. 权威边界

| 层 | 权威 | 可写 Canon？ | 可写 branch-local 状态？ |
| --- | --- | --- | --- |
| 确定性规则（world bible、characters、world rules、canon revisions、dependency graph） | **authority** | 仅经由 `ChapterCommitService` | 否 |
| Reader Persona panel | **advisory** | 否 | 否 |
| Model supplement（panel run） | **advisory** | 否 | 否 |
| 用户确认 | **decision** | 否（用户确认 Turn，非 Canon） | 是（创建 branch-local Turn record） |
| Branch-local Turn result | **proposed delta** | 否 | 是（append-only event log） |
| Chapter commit | **canonical** | 是（经由 `RevisionService`） | 否（Canon 为全局） |

## 8. 数据流（完整文本流程图）

```text
Context (project + timeline + chapter + source + canon revision)
  ↓
NarrativeTurnPlan (deterministic, binds context fingerprint)
  ↓
3 recommended actions (deterministic, from planning + world rules + character state)
  + 1 custom action entry
  ↓
Custom action feasibility pipeline (deterministic rules → classification)
  ↓
Preview (read-only; risk/cost projection; no state write)
  ↓
User confirmation (explicit; operation_id; idempotency)
  ↓
Confirmed Turn record (immutable; branch-local event log)
  ↓
Proposed state delta (NarrativeMemoryService-compatible; branch-scoped)
  ↓
... more Turns ...
  ↓
Chapter compilation (reads confirmed Turns in branch)
  ↓
ChapterCommitService.commit_chapter() (existing entry; no bypass)
  ↓
RevisionService.create_and_apply_revision() (Canon update; global)
  ↓
vector_index_lifecycle.index_chapter() (timeline-scoped; only after commit)
```

三层状态语义：

| 层 | 行为 |
| --- | --- |
| **Preview** | 严格只读；不创建正式事件；不修改状态；可生成风险与预计后果 |
| **Confirmed Turn** | 创建不可变 Turn record；写入当前 branch-local event log；产出 proposed state delta；不直接修改正式 Canon |
| **Chapter Commit** | 汇总已确认 Turn；生成或接受正式正文；通过既有 commit 入口；Canon 与长期状态在既有事务边界内更新 |

## 9. 分支与检索隔离方案

### 9.1 存储分区

```text
data/
├── chapters/                          ← 全局 Canon（仅 committed 章节）
├── summaries/                         ← 全局 Canon 摘要
├── canon_versions/                    ← 全局 Canon revisions
├── narrative_memory/
│   ├── events/
│   │   └── {timeline_id}/
│   │       └── {branch_id}/
│   │           └── chapter_NNN.json   ← branch-local 事件
│   ├── state/
│   │   └── {timeline_id}/
│   │       └── {branch_id}/
│   │           └── current.json       ← branch-local 投影状态
│   └── snapshots/
│       └── {timeline_id}/
│           └── {branch_id}/
│               └── chapter_NNN.json   ← branch-local 快照
├── narrative_turns/
│   └── {timeline_id}/
│       └── {branch_id}/
│           ├── plans/{turn_id}.json
│           ├── previews/{preview_id}.json
│           └── turns/{turn_id}.json
├── branches/
│   └── {timeline_id}/
│       └── branches.json              ← branch registry（active/archived）
└── chroma/                            ← 向量索引（manifest 强制）
```

**关键规则：** `data/chapters/`、`data/summaries/`、`data/canon_versions/`
保持**全局 Canon** — 仅由 `ChapterCommitService` 写入。Branch 内容位于
`narrative_turns/` 与 `narrative_memory/events/{timeline_id}/{branch_id}/`。

### 9.2 查询过滤规则

每次读/写 MUST 过滤：
1. `project_id`（来自 `ProjectContext`）
2. `timeline_id`（来自 context binding）
3. `branch_id`（来自 active branch 或显式目标）

**无跨分支读取**，除：
- Branch registry 本身（列出全部分支用于 switch/archive）。
- 显式 branch comparison view（未来；0D4 第一版不含）。

### 9.3 Chroma 隔离

| 操作 | API | 过滤 |
| --- | --- | --- |
| Index chapter | `vector_index_lifecycle.index_chapter()` | `project_id`、`timeline_id`、`canon_revision_id` |
| Index summary | `vector_index_lifecycle.index_summary()` | 同上 |
| Query | `vector_index_lifecycle.query()`（须新增 branch_id 参数） | `project_id`、`timeline_id`、`branch_id`（用于 branch-local 事件） |
| Legacy `vector_memory.build_or_update_index()` | **DEPRECATED — 分支场景禁用** | 无（不安全） |

**迁移计划：** `memory_repair_service.py` 须在 0D4-E 前迁移至
`vector_index_lifecycle`。本阶段记录为风险，不修复。

### 9.4 分支操作

| 操作 | 效果 | 可逆性 |
| --- | --- | --- |
| Create branch | 新 `branch_id`；拷贝 `parent_branch_id` 与 `created_from_turn_id`；父分支至分支点的 Turn 只读继承 | 不可逆（但可 archive） |
| Switch active branch | 更改 registry `active_branch_id`；后续读写指向新分支 | 可逆（切回） |
| Archive branch | `status="archived"`；无新写；读保留 | 可逆（restore） |
| Restore branch | `status="active"`；仅当同 timeline 无其他 active 分支 | 可逆 |
| Merge branch | **第一版不支持** | n/a |

### 9.5 分支切换

切换分支时：
1. URL 更新 `branch_id` 参数。
2. Context navigator 以新分支重载。
3. 旧分支所有在途 Turn plan **abandoned**（非 superseded — 留为只读历史）。
4. 新分支 Turn 历史载入。
5. Chroma 查询以新 `branch_id` 过滤重新发起。

**无静默 active-timeline 变更。** 分支切换始终显式且 URL 可见。

## 10. 契约与状态机

### 10.1 建议对象

#### NarrativeTurnPlan

```python
@dataclass(frozen=True)
class NarrativeTurnPlan:
    schema_version: str                    # "1.0"
    turn_id: str                           # deterministic id
    project_id: str
    timeline_id: str
    branch_id: str
    chapter_id: int
    source_version_id: str | None
    parent_turn_id: str | None             # None for first turn in chapter
    context_fingerprint: str               # sha256 of bound context
    planning_revision: str                 # story_planning.json version
    canon_revision: str | None             # active canon revision at plan time
    created_at: str                        # ISO8601 UTC
    status: str                            # see state machine
    recommended_actions: tuple["NarrativeActionOption", ...]
    custom_action_policy: "NarrativeCustomActionPolicy"
```

#### NarrativeActionOption

```python
@dataclass(frozen=True)
class NarrativeActionOption:
    action_id: str                         # deterministic, stable
    action_type: str                       # "advance"|"investigate"|"retreat"|"negotiate"|"sacrifice"|"custom_entry"
    display_text: str                      # user-facing, no prompt injection
    intent: str                            # short deterministic description
    expected_costs: dict[str, str]         # qualitative: {"time":"high","resource":"medium"}
    expected_risks: dict[str, str]         # qualitative: {"relationship":"low","safety":"high"}
    required_conditions: tuple[str, ...]   # deterministic condition ids
    unavailable_reasons: tuple[str, ...]   # empty if available
    provenance: str                        # "deterministic-planner"
    deterministic_order: int               # 1, 2, 3
```

#### NarrativeCustomActionPolicy

```python
@dataclass(frozen=True)
class NarrativeCustomActionPolicy:
    max_length: int                        # e.g. 200
    forbidden_patterns: tuple[str, ...]    # regex, e.g. no prompt injection
    feasibility_pipeline: tuple[str, ...]  # ordered check names
```

#### NarrativeActionValidation

```python
@dataclass(frozen=True)
class NarrativeActionValidation:
    validation_id: str
    turn_id: str
    action_source: str                     # "recommended"|"custom"
    selected_action_id: str | None         # None for custom
    custom_action_text_hash: str | None    # sha256 of normalized custom text
    status: str                            # "allowed"|"allowed_with_cost"|"requires_clarification"|"blocked"
    blocking_reasons: tuple[str, ...]      # deterministic reason codes
    cost_explanation: dict[str, str]       # qualitative
    risk_explanation: dict[str, str]       # qualitative
    checked_at: str
```

#### NarrativeTurnResult

```python
@dataclass(frozen=True)
class NarrativeTurnResult:
    turn_id: str
    project_id: str
    timeline_id: str
    branch_id: str
    chapter_id: int
    selected_action_id: str | None
    custom_action_text_hash: str | None
    result_status: str                     # "success"|"failure"|"partial"|"blocked"
    event_summary: str                     # short narrative summary (deterministic)
    state_delta_proposal: dict[str, Any]   # NarrativeMemoryService-compatible
    consequence_flags: tuple[str, ...]     # e.g. ("relationship_worsened","resource_lost")
    next_context_fingerprint: str
    execution_revision: str                # branch-local event log revision
    source_fingerprint: str                # bound to source at confirm time
    confirmed_at: str
    operation_id: str                      # idempotency key
```

#### NarrativeBranch

```python
@dataclass(frozen=True)
class NarrativeBranch:
    branch_id: str
    project_id: str
    timeline_id: str
    parent_branch_id: str | None           # None for root branch
    created_from_turn_id: str | None       # branch point
    display_name: str
    status: str                            # "active"|"archived"
    created_at: str
    archived_at: str | None
```

### 10.2 不新增的对象

- **不新增** `NarrativeTurnRun` — Turn 非 "run"；run 概念保留给 Panel Run。
- **不新增** `NarrativeStateDelta` 独立对象 — 作为 `NarrativeTurnResult` 字段，shape 与 `NarrativeMemoryService` event record 兼容。
- **不新增** `NarrativeScene` — scene 级编译为未来关注点；0D4 在 Turn 粒度操作。

### 10.3 字段绑定矩阵

| 字段 | Plan 必需 | Validation 必需 | Result 必需 | 备注 |
| --- | --- | --- | --- | --- |
| `turn_id` | 是 | 是 | 是 | deterministic, immutable |
| `project_id` | 是 | 是 | 是 | 须匹配 active context |
| `timeline_id` | 是 | 是 | 是 | 须匹配 active context |
| `branch_id` | 是 | 是 | 是 | 须匹配 active context |
| `chapter_id` | 是 | 是 | 是 | 须匹配选定章节 |
| `source_version_id` | 是 | 否 | 否 | plan 时绑定 |
| `parent_turn_id` | 是（或 None） | 否 | 否 | 分支内链 |
| `context_fingerprint` | 是 | 否 | 否 | 读取时重算 |
| `canon_revision` | 是（或 None） | 否 | 否 | plan 时 active canon |
| `source_fingerprint` | 否 | 否 | 是 | confirm 时绑定 |
| `operation_id` | 否 | 否 | 是 | 幂等键 |
| `selected_action_id` | 否 | 是（或 None） | 是（或 None） | custom 时 None |
| `custom_action_text_hash` | 否 | 是（或 None） | 是（或 None） | recommended 时 None |

### 10.4 不得存储的内容

- 完整 provider prompt 或 response 文本。
- 凭证、API key、endpoint。
- 绝对文件系统路径（仅 project-relative）。
- 原始内部异常。
- Reader Persona 自由文本反馈（存于 panel run store，不进 Turn store）。
- Model supplement 文本（存于 panel run store）。

### 10.5 状态机

```text
                                  ┌─────────────┐
                                  │   planned   │ ← TurnPlan created (read-only)
                                  └──────┬──────┘
                                         │ user selects/enters action
                                         ▼
                                  ┌─────────────┐
                  ┌───────────────│awaiting_action│
                  │               └──────┬──────┘
                  │                      │ submit action
                  ▼                      ▼
            ┌──────────┐           ┌───────────┐
            │ superseded│           │ validating │
            └──────────┘           └─────┬─────┘
                                          │
                          ┌───────────────┼───────────────┐
                          │               │               │
                          ▼               ▼               ▼
                   ┌─────────┐    ┌─────────────┐   ┌─────────┐
                   │ blocked │    │validated    │   │requires_│
                   └─────────┘    └──────┬──────┘   │clarify  │
                      (terminal)         │           └─────────┘
                                         │ preview requested
                                         ▼
                                  ┌───────────┐
                                  │ previewed  │ (read-only; no state write)
                                  └──────┬────┘
                                         │ user confirms (operation_id)
                                         ▼
                                  ┌───────────┐
                                  │ confirmed  │ ← immutable Turn record written
                                  └──────┬────┘
                                         │ branch-local event log appended
                                         ▼
                                  ┌──────────────────┐
                                  │applied_to_branch  │ ← state delta proposed
                                  └──────┬───────────┘
                                         │ chapter compile includes this Turn
                                         ▼
                                  ┌──────────────────────┐
                                  │included_in_chapter    │
                                  └──────┬───────────────┘
                                         │ ChapterCommitService.commit_chapter()
                                         ▼
                                  ┌───────────┐
                                  │ committed │ (terminal; Canon updated globally)
                                  └───────────┘
```

合法转换、非法转换、recovery、cancellation、superseded 详见
[docs/design/simulator_narrative_turn_state_machine.md](file:///d:/novel/StoryOS/docs/design/simulator_narrative_turn_state_machine.md)。

## 11. API 草案

### 11.1 第一版必需接口

| Method | Path | 输入 | 输出 | 只读？ | 幂等 | scope binding | Provider？ | 第一版需要？ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GET | `/api/simulator/narrative-turn/context` | project/timeline/branch/chapter query | bound context + fingerprint | 是 | n/a | project + timeline + branch + chapter | 否 | 是（0D4-B） |
| POST | `/api/simulator/narrative-turn/plans` | context binding | `NarrativeTurnPlan` + 3 actions | 是（创建 plan record，无状态写） | same context → same `turn_id` | project + timeline + branch + chapter + source | 否 | 是（0D4-B） |
| POST | `/api/simulator/narrative-turn/validate-action` | turn_id + action | `NarrativeActionValidation` | 是 | same input → same validation | turn_id scope | 否 | 是（0D4-B） |
| POST | `/api/simulator/narrative-turn/preview` | turn_id + validated action | preview (risk/cost) | 是 | same input → same preview（带过期） | turn_id scope | 否 | 是（0D4-B） |
| POST | `/api/simulator/narrative-turn/confirm` | turn_id + operation_id + action | `NarrativeTurnResult` | 否（写 branch-local） | same operation_id → replay | turn_id + operation_id | 否 | 是（0D4-D） |
| GET | `/api/simulator/narrative-turns` | branch/chapter query | list of Turn records | 是 | n/a | project + timeline + branch | 否 | 是（0D4-D） |
| GET | `/api/simulator/narrative-turns/{turn_id}` | turn_id | Turn record | 是 | n/a | turn_id scope | 否 | 是（0D4-D） |

### 11.2 未来接口

| Method | Path | 输入 | 输出 | 只读？ | 幂等 | scope binding | Provider？ | 第一版需要？ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| POST | `/api/simulator/branches` | parent_branch_id + created_from_turn_id + display_name | `NarrativeBranch` | 否 | idempotency key | project + timeline | 否 | 否（0D4-E） |
| POST | `/api/simulator/branches/{branch_id}/switch` | branch_id | updated registry | 否 | idempotency key | project + timeline + branch | 否 | 否（0D4-E） |
| POST | `/api/simulator/branches/{branch_id}/archive` | branch_id | updated registry | 否 | idempotency key | project + timeline + branch | 否 | 否（0D4-E） |
| POST | `/api/simulator/chapters/{chapter_id}/compile` | branch_id | candidate version | 否（写 candidate version） | idempotency key | project + timeline + branch + chapter | 否 | 否（0D4-F） |

### 11.3 错误码

```text
TURN_CONTEXT_NOT_READY
TURN_SOURCE_MISSING
TURN_SOURCE_CHANGED
TURN_TIMELINE_CHANGED
TURN_CANON_REVISION_CHANGED
ACTION_INVALID
ACTION_BLOCKED_BY_CANON
ACTION_BLOCKED_BY_CAPABILITY
ACTION_REQUIRES_RESOURCE
ACTION_REQUIRES_CLARIFICATION
TURN_ALREADY_CONFIRMED
TURN_ALREADY_COMMITTED
TURN_NOT_FOUND
TURN_NOT_PREVIEWED
TURN_OPERATION_ID_MISMATCH
TURN_OPERATION_ID_COLLISION
BRANCH_NOT_ACTIVE
BRANCH_SCOPE_MISMATCH
STATE_DELTA_CONFLICT
CHAPTER_NOT_READY_TO_COMPILE
```

不将内部异常字符串直接返回前端。

## 12. 实施阶段

### Phase 0D4-A — Narrative Turn contracts, state machine, append-only store

- **目标：** 数据契约 + 确定性、离线、append-only Turn store，无 UI、无 Canon 写。
- **修改范围：**
  - `core/contracts/narrative_turn.py` — 全部契约
  - `system/narrative_turn_store.py` — append-only store，路径 containment，原子写入（复用 `ProviderUsageReconciliationStore` 模式），幂等
  - `system/narrative_branch_store.py` — branch registry create/switch/archive/restore
  - store 层状态机强制
  - 临时项目测试
- **推荐模型：** GPT-5.6 Luna
- **推理强度：** medium
- **生产代码：** 允许（contracts + stores）
- **Provider：** 禁止
- **测试 Gate：** 契约校验；store 路径 containment（复用 B1-FIX 模板）；原子写入 + 幂等；状态机合法/非法转换；branch registry 操作
- **停止条件：** focused 测试全通过；无 Provider/network/token；无 Canon 写；compile clean

### Phase 0D4-B — Context binding, 3 deterministic recommended actions, custom action feasibility

- **目标：** 确定性 Turn plan 创建，3 推荐行动，custom action feasibility pipeline。仅 preview，无 confirm。
- **修改范围：**
  - `system/narrative_turn_planner.py` — 绑定 context 为 `NarrativeTurnPlan` 含 `context_fingerprint`
  - `system/narrative_action_feasibility.py` — 确定性规则引擎，读取 `world_bible.json`、`characters.json`、`world_rules.json`、planning dependencies、branch-local state
  - 3 推荐行动（确定性、稳定 id）
  - custom action feasibility pipeline：normalize → length/safety → world/canon check → character capability → resource/location/time → branch-state → classify
  - preview endpoint（只读）
- **推荐模型：** GPT-5.6 Luna
- **推理强度：** medium-high
- **生产代码：** 允许（planner + feasibility）
- **Provider：** 禁止
- **测试 Gate：** context binding（mismatch 检测）；恰好 3 推荐行动、稳定 id、确定性顺序；unavailable option 保留带 reason；custom action 全场景；分类为 allowed / allowed_with_cost / requires_clarification / blocked；同输入同输出
- **停止条件：** focused 测试全通过；feasibility 永不返回 fuzzy "maybe"；无 Provider；无 Canon 写

### Phase 0D4-C — Production Simulator UI

- **目标：** 现有 Simulator Shell 内新增 Narrative Turn workspace。
- **强制前置：** 调用 `frontend-design` skill 产出正式交互与视觉规范，方允许 UI 代码。
- **修改范围：**
  - `web/static/simulator-narrative-turn.js` — 新模块
  - `web/templates/index.html` — Simulator Shell 内新 workspace section
  - `web/static/simulator-narrative-turn.css`
  - 复用 `storyosApiGet/Post`、`AbortController`、generation counter、context navigator
  - URL state：`mode=simulator&view=narrative-turn&branch_id=...&turn_id=...`
- **UI 流：** 情境 → 3 推荐行动（cards）→ custom action input → feasibility 结果（inline）→ 后果预览（inline）→ 单一明确确认按钮
- **推荐模型：** GPT-5.6 Luna
- **推理强度：** medium
- **生产代码：** 允许（UI）
- **Provider：** 禁止
- **测试 Gate：** JavaScript syntax；DOM contract（复用 0D3B1/0D3C1 模式）；stale-response guard；AbortController on parent context change
- **停止条件：** UI 渲染流程；无 Provider；无 Canon 写；遵循 frontend-design 规范

### Phase 0D4-D — Turn confirm, branch-local event log, state delta, recovery

- **目标：** confirmation 接至不可变 Turn record + branch-local event log + state delta proposal，含幂等与恢复。
- **修改范围：**
  - `system/narrative_turn_service.py` — confirm endpoint with `operation_id`、原子写入、幂等 replay
  - branch-local event log append（复用 `ProviderUsageReconciliationStore` 原子模式）
  - state delta projection（扩展 `NarrativeMemoryService` branch awareness）
  - recovery：检测部分写入、重投影确定性 state delta
- **推荐模型：** GPT-5.6 Terra
- **推理强度：** medium-high
- **生产代码：** 允许（branch-local writes）
- **Provider：** 禁止
- **测试 Gate：** duplicate POST（同 operation_id）→ 幂等；concurrent POST（不同 operation_id）→ first wins；stale context/source/canon/branch → 正确错误码；部分写入恢复；state delta reproducibility
- **停止条件：** focused 测试全通过；无 Canon 写；无 Provider

### Phase 0D4-E — Branch create/switch/archive, retrieval isolation

- **目标：** 完整 branch lifecycle 与 Chroma 检索隔离。
- **修改范围：**
  - branch create/switch/archive/restore endpoints
  - `NarrativeMemoryService` 迁移至 branch-aware 路径
  - `memory_repair_service.py` 从 legacy `vector_memory.build_or_update_index` 迁移至 `vector_index_lifecycle`
  - 静态 guard 测试禁止新代码使用 legacy vector API
  - branch-aware Chroma query filter
- **推荐模型：** GPT-5.6 Terra
- **推理强度：** high
- **生产代码：** 允许（branch registry + 迁移）
- **Provider：** 禁止
- **测试 Gate：** branch A 事件不在 B；inactive branch 不入检索；archived branch 不入 active state；switch 保留旧分支；restore 重索引正确；未 commit Turn 不入长期 Canon memory；legacy vector API guard
- **停止条件：** focused 测试全通过；无跨分支泄漏；无 Canon 写

### Phase 0D4-F — Chapter compilation wiring

- **目标：** confirmed Turn → chapter compilation candidate → 既有 `ChapterCommitService`（不绕过）。
- **修改范围：**
  - `system/narrative_chapter_compiler.py` — 读取 branch 内 confirmed Turn，产出 chapter candidate version（非 commit）
  - candidate version 经由既有 `VersionManager` / manual version path 写入
  - `ChapterCommitService.commit_chapter()` 以 candidate `source_version_id` 调用（既有入口，无新 commit channel）
  - Turn record 标记 `included_in_chapter` → `committed`
- **推荐模型：** GPT-5.6 Luna
- **推理强度：** medium
- **生产代码：** 允许（compiler + 接线）
- **Provider：** 禁止
- **测试 Gate：** compile 仅读 confirmed Turn；blocked/cancelled/superseded Turn 忽略；顺序稳定；source changed → compile 阻塞；compile ≠ commit；commit 经既有入口；Canon 仅经由 `RevisionService` 更新
- **停止条件：** focused 测试全通过；无新 commit channel；Canon 仅经由既有 `ChapterCommitService` 更新

### 跨阶段测试矩阵（累计）

| 测试类别 | 0D4-A | 0D4-B | 0D4-C | 0D4-D | 0D4-E | 0D4-F |
| --- | --- | --- | --- | --- | --- | --- |
| Context binding | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Recommended actions (3, stable, deterministic) | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Custom action feasibility | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Preview (read-only) | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Confirmation idempotency | — | — | — | ✓ | ✓ | ✓ |
| Branch isolation | — | — | — | — | ✓ | ✓ |
| Chapter compile (no bypass) | — | — | — | — | — | ✓ |
| Path containment (B1-FIX pattern) | ✓ | — | — | ✓ | ✓ | — |
| Atomic write (B1-FIX pattern) | ✓ | — | — | ✓ | ✓ | — |
| State machine transitions | ✓ | — | — | ✓ | — | ✓ |

## 13. 风险矩阵

| 风险 | 严重度 | 缓解 | 阶段 |
| --- | --- | --- | --- |
| Canon 污染（未 commit Turn 写入 Canon） | **critical** | Turn 仅写 branch-local；Canon 仅经 `ChapterCommitService` | 0D4-D / 0D4-F |
| Branch 泄漏（分支数据进入主 timeline 检索） | **critical** | 强制 `timeline_id` + `branch_id` 过滤；禁用 legacy vector API | 0D4-E |
| Stale source（plan 与 confirm 间 source 变更） | high | `context_fingerprint` 重算；mismatch = `TURN_SOURCE_CHANGED` | 0D4-D |
| Timeline drift（plan 与 confirm 间 timeline 切换） | high | `timeline_id` mismatch 检测；`TURN_TIMELINE_CHANGED` | 0D4-D |
| Duplicate confirm（同 turn 多次 POST） | high | `operation_id` 幂等 replay | 0D4-D |
| State delta conflict（分支状态投影冲突） | high | append-only event log；确定性重投影 | 0D4-D |
| Model authority escalation（model 输出被当作权威） | high | 确定性规则 = authority；model = advisory | 全阶段 |
| Custom action injection（用户输入注入 prompt） | high | `forbidden_patterns`；`display_text` 永不经 provider；custom text 仅存 hash | 0D4-B |
| Chapter compile 绕过（不经 `ChapterCommitService`） | **critical** | compile 仅产 candidate version；commit 经既有入口 | 0D4-F |
| Chroma 过滤绕过（legacy `vector_memory`） | **critical** | 0D4-E 迁移；静态 guard 测试 | 0D4-E |
| Recovery 不完整（crash 后部分写入） | high | 原子写入 + operation_id replay + 确定性重投影 | 0D4-D |
| UI 状态误导（多同等权重按钮） | medium | 单一明确"下一步"；frontend-design skill 强制 | 0D4-C |

## 14. Git 与安全边界

### 14.1 修改文件

本阶段仅新增以下文档（未跟踪）：

```text
docs/design/simulator_narrative_turn_architecture.md
docs/design/simulator_narrative_turn_contract_map.md
docs/design/simulator_narrative_turn_state_machine.md
docs/design/simulator_branch_isolation_map.md
docs/planning/PHASE_0D4_IMPLEMENTATION_BRIEF.md
docs/planning/PHASE_0D4_P.md
docs/planning/PHASE_0D4_P_DELIVERY_REPORT.md
```

### 14.2 未跟踪文件

仅上述 7 个新增文档。无生产代码新增或修改。

### 14.3 既有 dirty worktree

仓库存在既有 dirty 状态（来自先前阶段，非本阶段产生）：

- 多个 `M` 修改文件（生产代码 + 文档），均来自 0D3C4-B1-FIX 等先前阶段。
- 多个 `??` 未跟踪文件（先前阶段产出）。

本阶段**未触碰**任何已修改或既有未跟踪文件。本阶段产出仅限上述 7 个新增文档。

### 14.4 Provider / network / token / cost

```text
Provider calls: 0
Network: 0
Token / cost: 0
Real project writes: 0
Chroma writes: 0
Canon writes: 0
```

### 14.5 Git 操作

```text
git add: 0
git commit: 0
git push: 0
git reset: 0
git clean: 0
git stash: 0
git rebase: 0
```

### 14.6 受保护数据

未读取或输出 credential。未修改用户真实正文、Canon、Timeline。未创建真实分支
或 Turn。未写 Chroma。未执行 memory repair。未执行 chapter commit。

## 15. 验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 文档路径引用 | 手动 | 所有 file:/// 链接解析至真实审计文件 |
| 现有 contract import | 不适用（无代码变更） | n/a |
| Python compileall | 不适用（无代码变更） | n/a |
| 只读静态扫描 | 不适用（无代码变更） | n/a |
| focused 测试 | 不适用（无新增测试） | n/a |
| Git status | `git status --short` | 仅新增 docs 未跟踪；无生产文件修改 |
| protected-data 只读检查 | 未触碰 | n/a |
| Provider/network/token/cost | 0 | n/a |
| 真实项目写入 | 0 | n/a |

## 16. 开放问题（须在 0D4-A 前回答）

1. **Timeline 模型：** `timeline_id` 加入 `ProjectContext`（影响所有调用方），还是作为独立 `TimelineContext` 与 `ProjectContext` 并行绑定？推荐后者以避免触碰既有调用点。
2. **Branch scope：** 分支共享 `data/chapters/`（branch-scoped canon revision）还是独立 `data/branches/{branch_id}/chapters/`？推荐后者以隔离。
3. **Custom action LLM assist：** 是否允许 model 建议 custom action 措辞（advisory only，非权威）？默认：0D4-A/B **否**；B1 provider pairing 解封后再议。
4. **Failure persistence：** "bad ending" Turn 产永久 branch chapter 还是仅 Turn record？推荐：仅 Turn record；chapter compilation 始终为显式用户操作。

这些问题不阻塞 0D4-P PASSED；须在 0D4-A 前回答。

## 17. 停止规则

不进入 Phase 0D4-A。每个子阶段须经由 implementation brief 单独 OWNER 授权。

## 18. 最终结论

```text
Phase 0D4-P: PASSED
Simulator Narrative Turn Architecture: READY FOR OWNER REVIEW
Production implementation: NOT STARTED
Phase 0D4-A: NOT ENTERED
```

完成报告。立即停止。不进入 Phase 0D4-A。
