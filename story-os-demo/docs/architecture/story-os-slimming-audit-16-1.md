# Story OS 阶段 16.1：系统瘦身架构审计

> 范围：仅审计 Git 跟踪的代码与必要文档；未读取真实小说正文、正史、记忆、向量数据或事故工件。本文件是阶段 16.2 的设计输入，不授权任何迁移、删除或 API 变更。

## 1. 审计方法与当前规模

### 1.1 方法与边界

- 审计对象：`story-os-demo` 下的受跟踪 Python、Web、测试与结构定义；排除 `data/` 中的业务内容、`.venv/`、`node_modules/`、`.git/`、pytest 临时目录、Chroma 文件和事故备份。
- 证据方式：`git ls-files`、符号检索和路由/调用点检索；不以目录名称代替实际职责。
- 本阶段不运行模型、初始化、生成、浏览器验证、pytest、健康诊断或全量数据 SHA 扫描。

### 1.2 代码基线

| 指标 | 当前值 | 证据 |
| --- | ---: | --- |
| Python 源文件 | 286 | `git ls-files story-os-demo/**/*.py` |
| Python 源行 | 35,022 | 对受跟踪 Python 文件的只读统计 |
| 测试文件 | 112 | `story-os-demo/tests/test_*.py` |
| JavaScript 文件 | 21 | `story-os-demo/web/static/**/*.js` |
| CSS 文件 | 17 | `story-os-demo/web/static/*.css` |
| HTTP 路由装饰器 | 260 | `story-os-demo/web/**/*.py` 中的 `@router.*` |

该规模说明系统并非只有五个包；五个目标 Engine 应是未来的**领域边界和正式入口**，而不是要求立刻物理移动所有模块。

## 2. 当前架构概览

```text
CLI / HTTP API / 原生前端
          |
          v
commands.py、web/routes.py、专用 routers
          |
          +--> Planning / Evaluation / Revision / Version / Memory 领域服务
          |
          v
ProjectContext + DataStore + JobManager + ModelGateway + Diagnostics
          |
          v
项目作用域 data/、版本文件、审计记录、可选外部同步与向量索引
```

### 2.1 基础设施与边界

| 模块 | 当前职责 | 读取/写入 | 关键证据 | 审计判断 |
| --- | --- | --- | --- | --- |
| `core/project_context.py` | 解析活动项目、定义全部项目路径、用 `ContextVar` 绑定单次操作 | 读取配置；提供路径，不直接写业务数据 | `ProjectContext`、`get_project_context()`、`bind_project_context()` | **keep**：项目作用域的权威路径模型 |
| `system/data_store.py` | 项目内路径防穿越、UTF-8 读写、原子替换、有限 Windows 共享冲突重试 | 读/写任意项目内允许路径 | `DataStore.path()`、`write_json()`、`_atomic()` | **keep**：正式通用存储入口 |
| `system/job_manager.py` | 后台任务、串行冲突保护、恢复、取消、日志与持久化 | `data/jobs/` | `JobManager.startup()`、`create_job()`、`recover_stale_jobs()`、`_save()` | **keep**：唯一通用任务状态机 |
| `llm/model_gateway.py`、`llm/run_recorder.py` | 模型路由、调用记录、用量/成本 | `data/model_runs/` 等 | `ModelGateway`、`RunRecorder`；评估生产读模型使用它们 | **keep**：模型运行权威来源 |
| `system/diagnostics_service.py`、`system/health_checker.py`、`system/memory_health.py` | 系统和记忆健康诊断 | 主要读；报告/日志按各服务规则写 | `DiagnosticsService`、`HealthChecker`、`memory_health_command()` | **adapter/keep**：诊断语义可保留，入口需收束 |

`web/app.py::lifespan()` 启停 `JobManager`，并在 `bind_active_project_context()` 中为每个请求绑定 `ProjectContext`；这是 API 到基础设施的正确方向。`web/routes.py::api_save_or_plan_next_chapter()` 仍直接以 `Path.write_text()` 写规划和 state，是已确认的反例，不能作为新的标准。

## 3. 模块与服务盘点

### 3.1 领域与服务清单

| 领域 | 主要模块/核心类或函数 | 当前职责 | 主要数据 | API/前端入口 | 关联测试（示例） | 分类 |
| --- | --- | --- | --- | --- | --- | --- |
| Planning | `planning_engine/control_service.py::PlanningControlService` | 战略、里程碑、契约、锁、冲突、快照 | `data/planning_control/*` | `/api/planning-control/*`；`planning-control.js` | `test_planning_control.py` | keep |
| Planning | `rolling_service.py::RollingWindowService` | 滚动窗口、章节槽位、推进、锚定 | `rolling_window.json` | `/api/planning-control/rolling-window/*`；`rolling-window.js` | `test_planning_rolling_*` | keep |
| Planning | `dependency_service.py::PlanningDependencyService`、`dependency_graph.py` | 图依赖、校验、上/下游查询 | `dependencies.json` | `/dependencies*`；`dependencies.js` | `test_planning_dependencies.py` | keep |
| Planning | `scheduling_service.py::NarrativeSchedulingService` | 叙事调度、状态转换、重绑定、审计 | `schedules.json` | `/schedules*`；`schedules.js` | `test_planning_schedules.py` | keep |
| Planning | `source_service.py`、`version_service.py`、`conflict_service.py` | 来源投影、控制层版本、冲突扫描 | 蓝图/控制层快照 | planning-control 路由 | `test_planning_control.py` | adapter |
| Evaluation | `evaluation_engine/service.py::EvaluationService` | 章节草稿统一评估、报告索引与过期判定 | `data/evaluations/` | `/api/evaluations*` | `test_evaluation_engine.py`、`test_evaluation_api.py` | keep |
| Evaluation | `planning_evaluation.py::PlanningEvaluationService` | 近期窗口/卷/全书规划评估 | `data/evaluations/` | `/api/evaluations/planning*` | `test_planning_evaluation_*` | keep |
| Evaluation | `planning_comparison.py::PlanningEvaluationComparisonService` | 同范围历史比较与作者建议 | 既有规划评估报告 | 比较、proposal API；`narrative-evaluation.js` | `test_planning_comparison_*` | keep |
| Evaluation | `production_service.py::EvaluationProductionService` | 使用量、分页、导出、维护预览/清理、健康读模型 | `evaluations`、模型运行记录 | usage/export/maintenance API | `test_evaluation_production*` | keep |
| Evaluation | `adapters/*.py` | 将质量、连贯性、读者、规划健康等既有证据转换为统一证据 | 上游报告只读 | 被 `EvaluationService` / `PlanningEvaluationService` 调用 | `test_evaluation_engine.py` | adapter |
| Revision | `evaluation_engine/improvement_service.py::ImprovementService` | 从评估问题生成修订计划、候选、再评估和比较 | `data/evaluations/improvements/` | improvements API；叙事评估中心 | `test_evaluation_improvement_*` | adapter |
| Revision | `system/revision_service.py::RevisionService` | 正史修订、候选、审查、影响分析、归档恢复 | `data/revisions/`、canon/archive | `/api/revisions*`；`revision-center.js` | `test_revision_service.py`、`test_revision_api.py` | keep |
| Version & Adoption | `system/version_manager.py` | draft/edited/manual 版本索引、选择、归档 | `data/versions/`、draft/edited/manual | `/api/versions*`；`app.js` | `test_version_manager*.py` | keep |
| Version & Adoption | `candidate_adoption_service.py`、`candidate_partial_adoption_service.py` | 候选预览、整包/部分采用、幂等和审计 | versions/evaluations/audit | adoption API | `test_candidate_*` | merge |
| Memory & Context | `system/context_builder.py` | 三层工作上下文、近期章节、摘要检索 | context、summaries、state | CLI/写作流程 | `test_context_builder.py` | keep |
| Memory & Context | `narrative_memory_service.py::NarrativeMemoryService` | 正史事件、时间线、投影、快照、冲突、检索历史 | `data/narrative_memory/` | `/api/narrative-memory/*`；`narrative-memory-view.js` | `test_memory_*` | keep |
| Memory & Context | `vector_memory.py`、`obsidian_sync.py` | 向量索引/检索与外部同步 | Chroma、Obsidian | 状态/修复入口 | `test_obsidian_sync.py`、`test_memory_health.py` | adapter |

### 3.2 其他已跟踪模块

- `core/`：项目建立、蓝图/角色/世界构建、章节规划、草稿写作与编辑，是写作工作流实现；未来通过 Planning、Revision、Version 与 Memory Engine 协同，不应在 16.2 被整体移动。
- `llm/`：模型提供方、重试、定价、提示词与运行记录；属于共享基础设施而非五个业务 Engine 之一。
- `agents/`、`creative_loop/`、`analytics/`、`author_memory/`：独立的辅助能力和 UI/API 领域。尚未证明无运行时引用、无前端调用、无数据兼容责任，**没有模块满足 remove 条件**。
- `system/`：包含存储、任务、诊断、质量、连续性、归档、管线、项目管理等基础设施/旧工作流。其中文件职责相近并不等于可直接合并；应先经统一协议和兼容层收束。

## 4. 数据模型与生命周期

### 4.1 主要模型

| 模型族 | 当前载体 | 生命周期与重叠判断 | 未来权威 |
| --- | --- | --- | --- |
| `EvaluationReport`、`EvaluationIssue`、`EvaluationEvidence`、`DimensionScore` | `evaluation_engine/models.py` dataclass；JSON report | 统一外部评估合同；章节与规划报告共享部分字段 | Evaluation Engine |
| `EvaluationComparison`、`PlanningImprovementProposal` | `planning_comparison.py` 返回 JSON | 只读派生模型；不应拥有独立写入口 | Evaluation Engine |
| `ImprovementRequest`、`CandidateDraft`、`CandidatePatch` | `improvement_service.py` 与 improvements 数据目录 | 与 `RevisionService` 的 candidate 概念重叠，但源不同（草稿 vs 正史） | Revision Engine + Version & Adoption Engine |
| `AdoptionPreview`、`PartialAdoptionPreview`、adoption audit | candidate adoption 服务 | 预览、source hash、operation id、采用审计是可泛化协议 | Version & Adoption Engine |
| `RollingPlanningWindow`、`ChapterSlot` | `rolling_models.py`、`rolling_service.py` | 窗口和槽位是规划域模型；不得与 next chapter plan 混同 | Planning Engine |
| `Dependency`、`NarrativeSchedule`、Milestone/Volume/Phase contract | dependency/scheduling/control 服务 | 都带来源、状态、锁/版本或审计；可共享协议，不宜强制同一 JSON schema | Planning Engine |
| draft/edited/manual 版本、CanonVersion | `version_manager.py`、`revision_service.py` | 都是版本，但正文工作版本和正史版本的权限/回滚语义不同 | Version & Adoption Engine（两个子模型） |
| `StoryState`、Canon、ChapterSummary、WorkingContext | `core/project_context.py`、`context_builder.py`、revision/memory 服务 | 上下文投影、正史和状态来源不同；不得简化为一份“大 memory JSON” | Memory & Context Engine |
| `VectorMemoryRecord`、外部同步记录 | `vector_memory.py`、`obsidian_sync.py` | 检索索引和人类可读外部副本不是权威正史 | Memory & Context Engine 的 adapter |

### 4.2 已确认的字段/协议重复

| 重复主题 | 证据 | 判断 | 16.2 处理方向 |
| --- | --- | --- | --- |
| `project_id` | `planning_engine/models.py::base_entity()`、评估/改进/采用/修订服务 | 多数新服务已写入，但格式有 `root.name` 与绝对 POSIX 路径两种表达 | 定义 `ProjectRef` 兼容视图；先读兼容，后统一新写入 |
| `source_hash` / `content_hash` | `improvement_service.py`、`candidate_adoption_service.py`、`revision_service.py`、`planning_engine/models.py` | 都用于陈旧性/来源保护，散布的摘要函数不同 | 提取共享 hash 协议；保留各领域的对象含义 |
| `operation_id` | Planning scheduling、Evaluation、Improvement、Adoption、Maintenance | 皆用于幂等或重放，验证规则不完全相同 | 统一 `OperationEnvelope` 校验和审计格式 |
| `created_at` / `updated_at` / `schema_version` | 控制层 base entity、job、revision、evaluation | 元数据重复但可安全标准化 | 先提供兼容 view/serializer |
| report `status` | `EvaluationService._status()`、规划比较、质量/连续性旧报告 | `current/stale/superseded/invalid` 与旧质量报告语义不是同一状态机 | Evaluation Engine 统一评估生命周期；旧报告仅作 evidence adapter |
| candidate | 质量改进候选与正史修订候选 | 二者的审批/应用对象不同 | 统一 Candidate/Preview/Adoption 协议，保留 `chapter_revision` 与 `canon_revision` 分型 |

## 5. 状态机盘点

| 状态机 | 状态 | 权威实现 | 重叠/边界 |
| --- | --- | --- | --- |
| Job | `queued`、`running`、`cancel_requested`、`completed`、`completed_with_warnings`、`failed`、`cancelled`、`interrupted`、`recoverable_failed`、`waiting_for_review` | `system/job_models.py`、`JobManager` | 应是后台任务唯一通用状态机；不等同于业务审批状态 |
| Evaluation report | `current`、`stale`、`superseded`、`invalid` | `EvaluationService._status()`；规划评估同类逻辑 | 统一到 Evaluation Engine；旧质量/连续性报告作为输入证据 |
| Evaluation gate | `attention` 等 gate 结论 | `evaluation_engine/gates.py::evaluate_gates()` | 是报告结果，不应与 job/status 混用 |
| Improvement | `created/generating/evaluating/qualified/review_required/rejected/cancelled`（由请求状态和 recommendation 组合） | `ImprovementService.create/run/_compare/_cancel` | 与 Candidate adoption 的采用状态相关但不同 |
| Adoption | preview、adopted、partially adopted、discarded，以及幂等 operation | `CandidateAdoptionService`、`CandidatePartialAdoptionService` | 将成为 Version & Adoption 的统一采用协议 |
| Revision | `editing`、`review_required`、`applying`、`completed`、`cancelled`、`stale` 等 | `RevisionService` | 正史修订必须保留自身审批和影响分析语义 |
| Planning milestone | `planned`、`prepared`、`achieved`、`delayed`、`cancelled`、`replaced` | `planning_engine/models.py` | 领域状态，不与 ChapterSlot 合并 |
| Rolling window | `draft`、`active`、`needs_roll_forward`、`stale`、`reanchor_required`、`archived`、`invalid` | `rolling_models.py` | 规划窗口生命周期 |
| Chapter slot | `open`、`outlined`、`reviewed`、`elapsed`、`archived`、`cancelled` | `rolling_models.py` | 单章节意图，不是章节版本状态 |

结论：应统一**状态机框架、事件和错误模型**，但不能把 job、评估、采用、修订、规划实体硬塞进一个枚举。最容易造成退化的是把同名 `cancelled`、`stale` 误判为相同业务状态。

## 6. 正式写入入口盘点

| 写入入口 | 调用方/目标 | 原子/校验/审计 | 审计结论 |
| --- | --- | --- | --- |
| `DataStore.write_json/write_text/write_markdown` | 新领域服务、JobManager、叙事记忆、评估、规划控制 | 原子替换；项目根校验；可选 `.bak` | 正式基础设施入口 |
| `PlanningControlService` 与 subservices | strategy、contracts、locks、rolling、dependencies、schedules | `project_id`、来源引用、版本/操作审计；由 DataStore 写入 | Planning Engine 正式入口 |
| `EvaluationService._save`、`PlanningEvaluationService._save` | evaluation report 与 index | 目标快照、operation id、current/superseded 处理 | Evaluation Engine 正式入口 |
| `EvaluationProductionService.cleanup` | 预览清理/维护审计 | preview id、expected item ids、operation id | 受限维护写入口 |
| `ImprovementService._save` | improvement request/index | source hash、operation id、候选/比较状态 | Revision adapter；未来收束 |
| `CandidateAdoptionService` / partial service | versions、评估状态、采用审计 | preview、source hash、operation id、回滚路径 | Version & Adoption 的核心候选 |
| `RevisionService` | canon version、revision、candidate、report、archive、audit | DataStore；章节/基线/状态检查 | 正史修订正式入口 |
| `version_manager.py` | versions index、归档移动 | 有本地 `_write_json_atomic()`，但仍有直接 `Path.write_text()` | 需迁移为 DataStore adapter |
| `web/routes.py::api_save_or_plan_next_chapter` | `next_chapter_plan.json/.md`、`state.json` | 直接 `Path.write_text()`；缺少 DataStore 一致入口 | 高优先级收束对象；本阶段不改 |
| `commands.py` 旧工作流写入函数 | draft/edited、chapter、context 等 | 多为流程级逻辑，部分自有路径/原子规则 | 通过 Engine facade 收束，不做大重写 |

### 6.1 写入协议结论

未来任何新写入入口必须至少明确：项目作用域、目标路径、原子性、source hash（适用时）、operation id（可重放操作）、预览/确认边界、审计记录、失败后的回滚信息。已有入口并非全部具备这些字段，因此“统一写入入口”应先是协议和 adapter，不能一次性替换所有持久化。

## 7. API 与前端入口

### 7.1 API 分组

| 分组 | 当前路径/控制器 | 读写 | 前端入口 | 兼容判断 |
| --- | --- | --- | --- |
| 叙事评估 | `web/routes.py` 的 `/api/evaluations*` | 报告生成、读、比较、导出、采用和维护 | `narrative-evaluation.js` | 作为 Evaluation/Version 边界主入口 |
| 规划控制 | `web/planning_control_routes.py`，prefix `/api/planning-control` | strategy/contract、window、dependency、schedule、lock/version | `planning-control*.js` | 是新规划 API；`/legacy` 路径需 compatibility 标记 |
| 旧规划/写作 | `web/routes.py` 的 `/api/planning/*`、`/api/run-chapter`、`/api/quality-check` 等 | 混合读写 | `app.js`、planning studio | 保持兼容，逐步转发到 Engine |
| 版本与正文 | `/api/versions*`、`/api/manual/*`、review 路径 | 读写 | `app.js` | 过渡至 Version & Adoption facade |
| 正史修订 | `/api/revisions*`、canon/archive 路径 | 读写 | `revision-center.js` | Revision Engine 主入口 |
| 记忆与向量 | `/api/narrative-memory/*`、`/api/memory-health`、`/api/vector-index/*` | 读与受控修复写 | `app.js`、`narrative-memory-view.js` | 收束为 Memory & Context API 家族 |
| 系统/模型/任务 | `/api/system/*`、`/api/models/*`、`/api/jobs*` | 运维读写 | operations/model center | 保持基础设施边界 |

`web/app.py` 当前同时 include 主路由、analytics、author、creative-loop 和 planning-control router。260 条路由证明路线收束必须按 API 家族进行，而不是一次修改 `web/routes.py`。

### 7.2 前端入口

主导航可见入口为：工作台、故事蓝图、章节管理、大纲编辑、AI 写作约束、叙事评估、版本记录、运行日志、项目设置、手动改稿、本地知识库、记忆与向量库、作品分析中心、作者中心、创作进化中心（`web/templates/index.html` 第 33–49 行）。

| 入口/残留能力 | 当前可见性 | 证据 | 处理 |
| --- | --- | --- | --- |
| 叙事评估中心 | 主导航 | `index.html#narrative-evaluation-center`、`narrative-evaluation.js::loadNarrativeEvaluationCenter` | keep；质量/连贯性/读者/规划健康在此聚合 |
| 质量报告、连续性 | 内嵌工作台面板 | `index.html#quality-panel/#continuity-panel`、`app.js::loadQualityReport/loadContinuityReport` | adapter 到 Evaluation Engine，不新增独立顶级中心 |
| Reader Simulation | API/评估输入，非主导航 | `web/routes.py::p_reader_simulate`、reader adapter | adapter，保留领域算法 |
| 候选采用 | 评估改善流程，不是顶级导航 | adoption API、`narrative-evaluation.js` | 收束至 Version & Adoption workflow |
| 规划风险/冲突/调度 | planning-control 内嵌页面 | `planning-control-panel` 与 submodule JS | keep；不要另造“风险中心” |
| 正史修订 | 页面存在但不在主导航 | `revision-center-panel`、`revision-center.js` | keep；16.2 可考虑从版本入口显式链接 |
| 成本/usage | 叙事评估中心卡片 + 模型 API | `narrative-evaluation.js::renderEvaluationUsage`、`/api/models/usage` | 共享 usage read model，避免第二个成本中心 |

## 8. 重复能力矩阵

| 能力 | 当前实现位置 | 重复数 | 当前权威实现 | 目标 Engine | 处理方式 | 风险 |
| --- | --- | ---: | --- | --- | --- | --- |
| 项目隔离 | ProjectContext、DataStore、web middleware、部分直接 Path | 4 | `ProjectContext + DataStore` | Core Infrastructure | merge direct-path call sites behind adapter | 高 |
| 原子写入 | DataStore、version manager、直接 `Path.write_text` | 3 | `DataStore._atomic` | Core Infrastructure | merge | 高 |
| 任务状态 | JobManager 与领域 request 状态 | 2 类 | JobManager（执行） | Core Infrastructure | adapter，不合并业务状态 | 中 |
| 候选状态 | improvement、revision candidate、adoption | 3 | 尚无单一协议 | Revision + Version & Adoption | merge protocol | 高 |
| 报告生命周期 | quality/continuity 旧报告、EvaluationReport、PlanningEvaluation | 3 | `EvaluationService` 评估报告 | Evaluation | adapter old reports | 中 |
| 版本编号 | version manager、revision canon、planning control snapshots | 3 | 各域各自编号 | Version & Adoption | shared identity protocol，保留域编号 | 中 |
| Hash 校验 | improvement/adoption/revision/planning | 4 | 尚无共享 helper | Core + Version & Adoption | merge shared protocol | 高 |
| `operation_id` 幂等 | planning/evaluation/improvement/adoption/maintenance | 5 | 尚无共享 envelope | Core Infrastructure | merge protocol | 高 |
| Diff | versions、improvement、revision | 3 | `system/text_diff.py` 的候选基础 | Revision | adapter callers | 中 |
| 整包/部分采用 | candidate adoption 与 revision apply | 2 | adoption services（草稿候选） | Version & Adoption | merge common preview/confirm/audit | 高 |
| 历史查询/分页 | evaluation production、model runs、jobs、versions | 4 | 各 domain read model | 各 Engine | compatibility view，避免通用万能列表 | 低 |
| 错误响应 | `api_response`、`api_ok/api_error`、`_ok/_fail`、异常处理器 | 4 | `web/view_models.py` 应成为目标 | API boundary | merge serializers | 中 |
| Usage/成本 | `RunRecorder`、`EvaluationProductionService`、models API | 3 | `RunRecorder` 原始记录 | Core + Evaluation read model | adapter | 低 |
| 审计 | adoption、planning schedule/control、revision、job/log | 4 | 各域记录 | Core protocol + domain stores | common envelope | 中 |
| 上下文构建 | `context_builder`、draft writer/editor 的压缩辅助、narrative memory | 3 | `build_working_context()` | Memory & Context | adapter | 高 |
| 规划范围定位 | control/rolling/projection/evaluation scope | 4 | Planning control + rolling window | Planning | shared `PlanningScope` view | 中 |
| 规划锁定 | locks、milestone/slot lock、review/author confirmation | 3 | planning locks | Planning | retain domain distinction | 中 |
| 冲突检测 | planning conflicts、continuity、revision impact、memory conflicts | 4 | 无单一算法 | 各 Engine | 不强并；统一 finding contract | 中 |

## 9. 风险登记

| 风险 | 等级 | 证据/触发条件 | 缓解策略 | 建议批次 |
| --- | --- | --- | --- | --- |
| 真实数据 schema 被误迁移 | 高 | `ProjectContext` 覆盖多个历史数据目录；存在 user-approved baseline 恢复测试 | 先兼容读、显式迁移、预览和备份；不批量重写 | 16.2 前置协议 |
| 旧 API 仍被前端调用 | 高 | `app.js` 与多个专用 JS 直接调用旧 `/api/*` | 先增加 forwarding compatibility；前端契约测试覆盖 | 每个合并批次 |
| 旧写入口未停用 | 高 | `web/routes.py::api_save_or_plan_next_chapter`、`version_manager.py` 直接写文件 | 将所有新写入接到 DataStore，旧路径改 adapter 后再废弃 | 第一批 |
| 双写导致不一致 | 高 | 评估索引/报告、版本 index、控制层版本、审计各自写入 | 一次操作只设置一个 authority writer；其余派生或审计 | 第一、二批 |
| 状态语义变形 | 高 | Job、评估、采用、修订、窗口均有 `stale/cancelled/completed` 等 | 类型化状态机和状态转换测试；禁止全局枚举替换 | 各领域批次 |
| 候选采用退化 | 高 | 草稿候选与正史修订均需 source hash、preview、人工确认 | 先定义 Candidate/Preview/Adoption 协议，保留 domain policy | 第二批 |
| 项目隔离/Hash 丢失 | 高 | `project_id` 表达形式不一致，局部直接 Path 写入 | ProjectRef + DataStore + source snapshot 作为强制 precondition | 第一批 |
| 测试 fixture 掩盖真实依赖 | 中 | 112 测试中存在多种临时项目/客户端 helper | 16.1 只盘点；16.2 先抽共享 fixture，保留 real-data protection | 后续测试批次 |
| 循环 import | 中 | Engine 收束会改变 import 图 | API 仅依赖服务 facade；基础设施不依赖 web/engine | 每批 import 测试 |
| 过度抽象 | 中 | analytics/creative/author 等模块未证明属于五引擎 | 只抽取重复协议；不搬迁不相关业务模块 | 全程 |

## 10. Post-Slimming Backlog

| 分类 | 条目 | 不进入当前瘦身实施的原因 |
| --- | --- | --- |
| 功能缺失 | 给正史修订中心增加显式主导航入口 | 体验改进，不是重复能力收束 |
| 体验优化 | 在版本页面统一展示草稿候选与正史修订候选的关联 | 需要先完成 Candidate 协议 |
| 性能优化 | 为历史列表建立一致的 cursor/filter 体验 | 不影响权威写入与架构边界 |
| 测试优化 | 合并临时项目、TestClient、评估报告 fixture | 本阶段仅记录，避免重构测试 |
| 文档优化 | 生成 API 兼容清单与弃用时间线 | 应随每个 16.2 批次的真实变更更新 |
| 未来 Agent 能力 | 将创作进化、作者记忆与分析结果以受控证据接入规划/评估 | 新业务范围，不能作为瘦身顺手实现 |

## 11. 审计结论

1. 五个目标 Engine 与现有代码匹配，但应以**服务 facade、共享协议、兼容 adapter**逐步建立，不能把现有目录机械改名。
2. `ProjectContext`、`DataStore`、`JobManager`、`ModelGateway/RunRecorder` 已是可保留的基础设施权威实现。
3. 最需要优先收束的不是评估算法，而是直接文件写入、候选/采用协议、`project_id`/hash/operation id 的通用约束。
4. `quality`、`continuity`、Reader Simulation、Planning Health 应继续作为 Evaluation Engine 的适配证据；它们不需要各自再发展顶级中心。
5. 当前没有任何模块在“无运行时引用、无前端调用、无测试依赖、无数据兼容责任、无正式写入职责”五项条件上被证明满足，因此本审计不标记 remove。
