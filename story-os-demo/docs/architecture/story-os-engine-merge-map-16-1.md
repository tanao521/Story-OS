# Story OS 阶段 16.1：Engine 合并地图

> 本地图基于 `story-os-slimming-audit-16-1.md` 的只读证据。它定义阶段 16.2 的边界、顺序与验证策略；不改变当前 API、schema、状态机、数据或模块位置。

## 1. 目标架构与依赖方向

```text
CLI / HTTP controller / Frontend
              |
              v
  Planning | Evaluation | Revision | Version & Adoption | Memory & Context
              |
              v
ProjectContext | DataStore | JobManager | ModelGateway/RunRecorder | Diagnostics
```

规则：API、CLI 和前端只能调用领域 Engine 的明确接口；Engine 只能依赖核心基础设施或另一 Engine 的显式只读/命令接口。禁止 Evaluation 直接写 Planning 文件、Revision 复制版本写入逻辑、前端承担业务判断、adapter 绕过 Engine 写入。

## 2. 五个目标 Engine

| Engine | 未来职责 | 当前权威实现与证据 | 边界/禁止事项 |
| --- | --- | --- | --- |
| Planning Engine | 战略、契约、滚动窗口、ChapterSlot、依赖、叙事调度、冲突、规划版本 | `PlanningControlService`、`RollingWindowService`、`PlanningDependencyService`、`NarrativeSchedulingService`、`planning_engine/models.py` | 不改写 story blueprint、next plan、正文或正史；这些仅是来源/投影或经明确命令处理 |
| Evaluation Engine | 章节与规划评估、证据归一、评分、报告生命周期、历史比较、优先建议、evaluation health/usage read model | `EvaluationService`、`PlanningEvaluationService`、`PlanningEvaluationComparisonService`、`EvaluationProductionService`、`adapters/` | 不自动修复正文或规划；只产生报告、建议、可审计的受控维护 |
| Revision Engine | 修订请求、计划、候选生成、重新评估、review、影响分析、正史修订 | `ImprovementService`、`RevisionService`、`candidate_evaluator.py`、`system/text_diff.py` | 不拥有版本索引/采用原子写入；将候选交给 Version & Adoption |
| Version & Adoption Engine | draft/edited/manual/canon 版本身份、选择、diff、preview、整包/部分采用、hash、operation id、审计、回滚信息 | `system/version_manager.py`、`CandidateAdoptionService`、`CandidatePartialAdoptionService`、`RevisionService` canon 分支 | 正文工作版本与 canon 版本保持分型；不把 review 策略抹平 |
| Memory & Context Engine | Working Context、state/canon/summary 视图、叙事记忆、检索、向量/Obsidian adapter、memory health | `context_builder.py`、`NarrativeMemoryService`、`vector_memory.py`、`obsidian_sync.py` | 不直接采用候选正文；向量和外部同步不是权威正史 |

## 3. 权威所有权地图

| 业务概念 | 当前所有者 | 未来权威 Engine | 兼容入口/边界 |
| --- | --- | --- | --- |
| Project scope / path | `ProjectContext`、`DataStore` | Core Infrastructure | legacy `Path` 写入改为 adapter |
| EvaluationReport | `EvaluationService`、`PlanningEvaluationService` | Evaluation | 旧 quality/continuity/reader/health report 转 evidence adapter |
| EvaluationComparison / proposal | `PlanningEvaluationComparisonService` | Evaluation | 只读 API 和导出保留 |
| ImprovementRequest | `ImprovementService` | Revision | 采用前通过 Version & Adoption |
| Chapter revision / canon candidate | `RevisionService` | Revision | Candidate identity、预览、采用协议由 Version & Adoption 提供 |
| Candidate adoption | candidate adoption services | Version & Adoption | 保持整包/部分采用和人工确认 |
| Draft/Edited/Manual version | `version_manager.py` | Version & Adoption | `/api/versions*` 先兼容转发 |
| CanonVersion | `RevisionService` | Version & Adoption（canon 子模型） | revision 保留 review/impact policy |
| StoryStrategy / contracts / milestone / locks | `PlanningControlService` | Planning | `/api/planning-control/*` 为主入口 |
| RollingPlanningWindow / ChapterSlot | rolling services | Planning | next chapter plan 仅为相邻工作流对象，不与槽位混合 |
| Dependency / NarrativeSchedule | dependency/scheduling services | Planning | 保留来源、状态和审计细节 |
| StoryState | 写作/提交流程与 ProjectContext 相关服务 | Memory & Context（读取投影） | `commit-chapter` 仍是正常推进 chapter 的唯一流程 |
| Canon / narrative memory | `RevisionService`、`NarrativeMemoryService` | Memory & Context（读取/投影） | canon 写入仍通过 Revision/Version 授权路径 |
| WorkingContext | `context_builder.py` | Memory & Context | draft writer/editor 使用 facade，不复制截断逻辑 |
| Vector retrieval / Obsidian | vector/obsidian 服务 | Memory & Context adapter | 不作为数据权威来源 |
| Job / model run / audit envelope | `JobManager`、`RunRecorder`、各域 audit | Core Infrastructure | 领域记录可扩展，公共字段统一 |

同一概念在目标状态只能有一个**权威写入者**。例如 Candidate 由 Revision 产生，但采用版本变更只能由 Version & Adoption 写；Evaluation 可以判断候选，不可修改正文或规划。

## 4. 模块分类

### 4.1 keep：继续作为权威实现

- `core/project_context.py::ProjectContext` 与 `system/data_store.py::DataStore`：项目隔离和原子存储。
- `system/job_manager.py::JobManager`、`system/job_models.py`：后台作业状态和恢复。
- `planning_engine/control_service.py`、`rolling_service.py`、`dependency_service.py`、`scheduling_service.py`：规划控制层。
- `evaluation_engine/service.py`、`planning_evaluation.py`、`planning_comparison.py`、`production_service.py`：统一评估、历史与生产读模型。
- `system/revision_service.py::RevisionService`：正史修订、影响分析和归档恢复。
- `system/context_builder.py`、`system/narrative_memory_service.py`：上下文与叙事记忆。

### 4.2 merge：进入统一 Engine 的能力

| 对象 | 合并目标 | 依据 |
| --- | --- | --- |
| `candidate_adoption_service.py` + `candidate_partial_adoption_service.py` | Version & Adoption 的 Adoption protocol | 都使用 preview、source hash、operation id、audit；仅采用粒度不同 |
| hash helper | `ContentFingerprint` 协议 | planning/evaluation/improvement/adoption/revision 分别实现 hash |
| operation id 校验与重放 | `OperationEnvelope` 协议 | planning schedule、evaluation、improvement、adoption、maintenance 都实现幂等 |
| API 成功/错误外壳 | `web/view_models.py` 统一 serializer | `api_response`、`api_ok/api_error`、`_ok/_fail` 并存 |
| 版本索引写入 | Version & Adoption storage adapter | `version_manager.py` 自有 `_write_json_atomic` 与 DataStore 重叠 |
| 评估证据来源 | Evaluation adapter registry | quality、continuity、reader、planning health 已有 adapters，仍存在旧直出入口 |

### 4.3 adapter：保留领域算法，仅经目标 Engine 调用

| 适配器对象 | 目标 Engine | 说明 |
| --- | --- | --- |
| quality report、continuity report、Reader Simulation、character state | Evaluation | 作为 `EvaluationEvidence/Issue` 来源，不复制评分/生成算法 |
| planning source projection、blueprint suggestions、conflict scan | Planning | 读源数据，不能直接改变计划基线 |
| `ImprovementService`（章节草稿改善） | Revision | 生成/再评估算法保留；候选落地交 Version & Adoption |
| `RevisionService` 的 canon 写入子流程 | Version & Adoption | 保留正史规则；以统一 version/adoption protocol 提供原子提交 |
| vector index、Obsidian sync | Memory & Context | 保留外部系统行为；必须不成为 canon writer |
| analytics、author memory、creative loop | 显式证据接口（后续） | 目前不强行并入五 Engine |

### 4.4 compatibility：需要保留的旧入口/数据责任

- `/api/planning/*` 旧计划/蓝图/next-chapter 路由：先转发到 Planning facade；其中 `api_save_or_plan_next_chapter` 先修正写入路径，不改变请求/响应形状。
- `/api/versions*`、manual/review：保留旧 source type、版本编号与 UI 预期，内部转到 Version & Adoption。
- `planning_control_routes.py` 中 `/legacy` 的 roll-forward、reanchor、refresh、cancel、restore 路径：保留直到前端和测试无引用，再按弃用窗口删除。
- 旧 quality/continuity JSON：以只读 evidence adapter 继续支持，不在没有迁移工具的批次重写。
- `draft_vNNN`、`edited_vNNN`、`manual_vNNN`、CanonVersion：继续按现有文件名读写，新增统一身份映射而非改名。

### 4.5 remove：当前无候选

本审计未发现同时满足“无运行时引用、无前端调用、无测试依赖、无真实数据兼容责任、无正式写入职责”的模块。任何标为 `remove` 的候选必须在未来批次用引用扫描、运行期检查和兼容数据清单逐项证明；16.2 不应预设删除名单。

## 5. 推荐合并顺序（16.2 设计）

### 批次 1：共享协议与兼容 View

| 项目 | 内容 |
| --- | --- |
| 前置条件 | 确认 DataStore、ProjectContext、现有 API/fixture 契约；不迁移真实数据 |
| 涉及模块 | `core/project_context.py`、`system/data_store.py`、`web/view_models.py`、各 Engine 的小型 protocol 层 |
| 目标 | 定义 `ProjectRef`、`ContentFingerprint`、`OperationEnvelope`、审计/错误/分页兼容 view；明确 `DataStore` 为新写入唯一底座 |
| 禁止同时修改 | 真实规划数据、版本 schema、候选采用业务决策、前端页面布局 |
| 兼容策略 | 新字段可选；旧 `project_id` 同时接受 name/absolute path 并规范化比较；旧 API 输出不删字段 |
| 定向验证 | project context、data store、web error contract、hash/operation id 单元测试 |
| 回滚点 | 新协议只读/包装层；可删除 facade 调用，不触碰数据 |

### 批次 2：Revision 与 Version & Adoption 收口

| 项目 | 内容 |
| --- | --- |
| 前置条件 | 批次 1 协议稳定；完整列出 draft/edited/manual/canon/adoption 的读写文件 |
| 涉及模块 | `system/version_manager.py`、candidate adoption 两服务、`ImprovementService`、`RevisionService` |
| 目标 | 单一 Version/Adoption facade 负责 version identity、preview、hash、operation id、audit、原子落地；Revision 只拥有修订规则和候选产生 |
| 禁止同时修改 | `commit-chapter` 行为、正文格式、canon schema、模型提示词 |
| 兼容策略 | 保留现有版本编号与 `/api/versions*`；candidate 服务先变 adapter，不删除 API |
| 定向验证 | `test_version_manager*`、`test_candidate_*`、`test_revision_*`、manual history/real-data protection |
| 回滚点 | facade 内保留旧 writer adapter；双写严禁，出错退回旧单 writer |

### 批次 3：Planning Engine 统一入口

| 项目 | 内容 |
| --- | --- |
| 前置条件 | 批次 1 可提供共同 source/hash/operation 约束；明确 next chapter 与 rolling slot 的不同 |
| 涉及模块 | `planning_engine/*`、`web/planning_control_routes.py`、旧 `/api/planning/*`、planning JS |
| 目标 | Planning facade 统一 strategy/contracts/window/dependency/schedule 的命令与只读视图；旧 API 转发 |
| 禁止同时修改 | story blueprint、next chapter plan、state、正文、规划生成模型调用 |
| 兼容策略 | legacy route 标注弃用，保持旧响应；先迁移 controller，不批量迁移 data |
| 定向验证 | planning control、rolling、dependencies、schedules、planning API/frontend contract |
| 回滚点 | 单路由开关回旧 service；不改变数据文件 |

### 批次 4：Memory & Context 边界收口

| 项目 | 内容 |
| --- | --- |
| 前置条件 | 修订/版本的 canon ownership 已明确；现有三层上下文测试通过 |
| 涉及模块 | `context_builder.py`、draft writer/editor 辅助函数、`NarrativeMemoryService`、vector/obsidian services |
| 目标 | 单一 WorkingContext facade；将写作端截断/检索辅助变为 adapter；明确 canon、summary、vector、external sync 的来源等级 |
| 禁止同时修改 | Chroma 索引格式、外部 Obsidian 内容、真实记忆数据、写作提示词语义 |
| 兼容策略 | 保留当前 context payload 字段；vector/Obsidian 维持可选 adapter |
| 定向验证 | context builder、memory health/repair、obsidian sync、vector status、writing constraints |
| 回滚点 | 保留原上下文 builder 输出格式和旧 helper fallback |

### 批次 5：Evaluation API 与遗留入口清理

| 项目 | 内容 |
| --- | --- |
| 前置条件 | 其他 Engine 均提供明确只读接口；前端确认不再直接依赖旧评估读取 |
| 涉及模块 | `evaluation_engine/*`、quality/continuity adapters、`web/routes.py`、`narrative-evaluation.js` |
| 目标 | Evaluation facade 统一报告、比较、usage、export、health 与 evidence adapter；将质量/连续性/Reader/Planning Health 的旧入口收为兼容层 |
| 禁止同时修改 | 评估评分规则与候选采用规则；避免把“收口”变成指标重算 |
| 兼容策略 | 旧 report/read API 转发；按公开弃用期再删除 |
| 定向验证 | evaluation、planning evaluation、comparison、production、frontend contract、API contract |
| 回滚点 | 保持旧 adapter 和旧 read API；不重写历史报告 |

## 6. 依赖风险与禁止方向

| 禁止方向 | 当前风险证据 | 目标约束 |
| --- | --- | --- |
| Evaluation 直接写 Planning 文件 | Planning evaluation 已读控制层/窗口；若直接修复会越权 | 只返回 proposal，作者经 Planning command 执行 |
| Revision 复制版本写入 | `RevisionService` 与 `version_manager` 都含版本/原子逻辑 | Revision 调用 Version & Adoption facade |
| Frontend 直接承载业务判断 | `app.js`、planning JS 与 routes 同时保有部分流程逻辑 | UI 只校验交互和呈现；服务器 Engine 决策 |
| Adapter 绕过统一写入 | 历史 `Path.write_text` 和局部自建 atomic helper | 所有新写入通过 DataStore；旧写入成为可测 adapter |
| Memory 直接采用候选正文 | narrative memory/canon 正在相邻领域 | Memory 只消费已授权的版本/canon 事件 |
| 系统模块反向依赖 Web | `web/app.py` 应处于顶层 compose 位置 | 核心/Engine 不导入 routes 或 JS 语义 |

## 7. 定向验证策略

| 层级 | 每批最低验证 |
| --- | --- |
| 协议层 | ProjectContext、DataStore、hash/operation id、错误 serializer 单元测试 |
| Planning | planning control、rolling lifecycle/window、dependencies、schedules、API 与前端合同 |
| Revision / Adoption | version manager、candidate adoption（全量/部分）、revision、manual history、real data protection |
| Memory | context builder、memory health/repair、narrative memory、vector/obsidian contract |
| Evaluation | evaluation engine/API/frontend、planning evaluation/comparison/proposals、production/usage/export |
| 回归 | 只有批次改动足够广泛时才运行全量 pytest；任何实际代码改动前后均保护 story blueprint、next plan、state、正文、canon、memory、vector、evaluations |

## 8. 阶段 16 验收指标

### 8.1 当前基线与目标值

| 指标 | 当前基线 | 阶段 16 目标 | 说明 |
| --- | ---: | ---: | --- |
| 权威项目作用域实现 | 1 (`ProjectContext`) + 直接路径旁路 | 1 | 不以删除路径数计，而以无旁路新写入计 |
| 原子写入实现 | 至少 3 类（DataStore、version manager、direct path） | 1 权威 + 兼容 adapter | 所有新写入统一到 DataStore |
| 通用 job 状态机 | 1 | 1 | 不并吞领域状态机 |
| Candidate/Adoption 协议 | 至少 2 套 | 1 协议、多个领域 policy | 正史/草稿仍可有不同审批规则 |
| hash/operation 约束实现 | 至少 4/5 处 | 1 共享协议 | 各领域保留自己的 hash 对象 |
| 顶级前端入口 | 14 个主导航入口 | 不以减少为目标 | 以每个入口唯一业务归属和可发现性为目标 |
| API 兼容层 | 多个旧/新并存、含 `/legacy` | 有登记、转发和弃用计划 | 不以立即减少路由数为目标 |
| 已证明可删除模块 | 0 | 仅证据满足时增加 | 没有“为了瘦身而删”目标 |

### 8.2 不适合量化的项

- 领域状态机语义是否仍清晰；
- 人工确认、预览、审计和回滚是否没有被“统一”削弱；
- 真实数据兼容性是否由迁移/回滚演练证明；
- API/前端兼容层是否能被用户实际流程安全替代；
- 模块物理数量是否减少（这不是成功的充分条件）。

## 9. 16.2 第一批建议

建议对象：`ProjectRef`、`ContentFingerprint`、`OperationEnvelope`、统一 API response view，以及将新写入限定到 `DataStore` 的窄 facade。

原因：这批不改变小说业务规则、不迁移数据、也不需要先选择哪个候选/版本，但能消除后续 Planning、Revision、Evaluation 同时各自复制项目隔离、hash、operation id 和错误响应的根因。完成后再进入 Version & Adoption 收口，而不是直接移动模块或删除旧入口。

## 10. 16.2-1 实施状态（2026-07-16）

- 已建立的共享协议：`core/contracts/project_ref.py` 提供内部 `ProjectRef` 与不含绝对路径的 `ProjectIdentityView`；`core/contracts/safety.py` 提供严格 SHA-256 `HashGuard`/`HashExpectation`、`OperationEnvelope` 及 `SafeResult`/`ErrorEnvelope`。
- 已接入的低风险调用点：`evaluation_engine/production_service.py::EvaluationProductionService.cleanup()` 的维护审计记录改由 `system/safe_write.py::DataStoreWriteFacade` 写入；Facade 复用 `DataStore.write_json()`，不新增原子替换实现。
- 已接入的兼容 View：`web/view_models.py::api_error()` 保留既有响应字段，并通过 `ErrorEnvelope` 脱敏 `details` 中的路径、堆栈、正文、提示词及凭据字段。
- 尚未迁移的高风险写入：`web/routes.py::api_save_or_plan_next_chapter()`、正式 blueprint/next plan/state 写入、Canon commit、整包/部分采用及 `system/version_manager.py` 的既有写入链路均保持不变。
- 16.2-2 前置条件：为 draft/edited/manual/canon 版本身份与候选 preview/adoption 明确单一写入者，并为旧版本编号、文件名和 API 入口建立兼容映射；不得由 16.2-1 的 Facade 直接接管这些业务规则。

## 11. 16.2-2B 实施状态（2026-07-16）

- 权威采用入口：`system/version_adoption_service.py::VersionAdoptionService` 统一 whole、partial、preview 与 discard 的命令编排；不调用模型、不修改 Canon、规划或 `state.json`。
- 正式版本写入：`CandidateAdoptionService._create_work_version()` 已改为 `VersionWriterFacade` 调用；保留原有 `manual_vNNN`、目录、selected pointer 与兼容返回字段。
- 兼容入口：`CandidateAdoptionService` 与 `CandidatePartialAdoptionService` 的公共方法只转发到统一服务；旧 payload、错误码、候选状态投影与 API 路由保持可用。
- 协议扩展：`AdoptionPreview` / `AdoptionRequest` 支持 `whole|partial`、`selected_patch_ids` 和 `patch_set_hash`；partial 继续使用已持久化的稳定 patch、依赖、冲突、重叠和锚点校验。
- 幂等与边界：`OperationEnvelope` 提供统一请求指纹，持久化在既有采用/放弃记录中以支持重启后 replay 与同 ID 不同请求冲突；`improvement_adoption_audit.json` 仍是采用审计权威记录。
- 未迁移边界：`system/version_manager.py` 的其他兼容入口、Canon 采用、历史版本迁移和删除旧 API 留待 16.2-2C 及后续阶段。

## 12. 16.2-2C 实施状态（2026-07-16）

- `VersionManager` 现定义为版本命名、路径计算、读取/列表与旧 API 兼容层；非 Canon version index 与 selected pointer 写入已转发 `VersionWriterFacade`。
- `VersionWriterFacade` 新增兼容工作版本写入入口，覆盖 legacy-shaped draft、edited、manual JSON/Markdown、别名文件及版本索引；实际原子写入仍由 `DataStoreWriteFacade` → `DataStore` 完成。
- `manual_editor` 与 `commands` 的正常文件路径工作版本写入已转发门面；仅纯内存 `FakePath` 测试替身保留 mock 兼容分支，不可到达磁盘。
- `VersionManager._write_json_atomic` 已降级为 archive-meta 兼容包装，不再承担工作版本写入；Canon 提交、Canon 回滚、历史版本迁移和 Planning 写入未改动。
- 16.2-3 前置条件：非 Canon 版本命名、读取、索引、selected pointer 与候选采用已具有统一写入入口，后续仅处理 Planning 写入，不应重开版本/Canon 边界。

## 13. 16.2-3 实施状态（2026-07-16）

- 新增 `system/planning_mutation_service.py::PlanningMutationService`：以封闭目标注册表承接规划写入；调用链固定为兼容调用点 → ProjectRef / HashGuard / OperationEnvelope → DataStoreWriteFacade → DataStore。调用方不能提供路径。
- 覆盖的规划目标包括 next chapter plan 与其 Markdown 投影、受白名单约束的 planning state、story planning、rolling window、dependency、schedule、strategy、milestone、contracts、locks、conflicts、metadata 与内部生成的 planning version snapshot。
- 多目标写入先完整校验路径、当前完整 SHA-256、JSON 类型与边界规则；状态字段只允许 `current_stage` 和 `next_chapter_plan` 合并，且固定最后写入。已写入目标若后续失败，会经 DataStoreWriteFacade 反向恢复原始字节内容，不创建 `.bak`。
- `data/planning_control/mutation_audit.json` 是项目隔离、内容脱敏的持久幂等记录：同一 operation id 与指纹可在重启后 replay；同 id 不同指纹返回 `OPERATION_ID_CONFLICT`。
- `web/routes.py::api_save_or_plan_next_chapter()`、`PlanningControlService`、rolling lifecycle、dependency、narrative schedule、planning control snapshot，以及旧 `system/planning_service.py` 的 planning/next-plan 写入已转为兼容调用该入口；规划算法、API 路由、版本编号与 Canon 边界未改动。
- 未迁移边界：Canon、正文提交、blueprint 生成、模型规划修订、前端业务逻辑与真实数据迁移；这些仍不属于 16.2-3。

## 14. 16.2-4 实施状态（2026-07-16）

- `system/context_assembly_service.py::ContextAssemblyService` 是新的只读上下文组装权威入口；`system/context_builder.py::build_working_context()` 保留既有返回字段，改为兼容转发。CLI 的 build-context/提交后刷新，以及 Web agent snapshot 因而共用同一入口。
- 统一包保留 Working Context、Narrative State、Canon Memory、Summary Memory、Vector Retrieval 与 External Sync 的职责分离；其中 Canon/summary/vector/external 均为来源适配器或安全投影，不取得事实或写入权威。
- ContextPackage 使用固定来源顺序：作者约束、Canon、Narrative State、正式规划、最近已提交章节、工作版本、Summary、Vector、外部投影。包内记录 source manifest、去重、冲突、profile 预算和只读标记；绝对路径、Vault 路径及客户端提供的越界 memory 路径会被剔除。
- 支持轻量 profile（drafting、planning、revision、evaluation、continuity、reader）；profile 只改变来源配额与是否允许 vector，不修改 Prompt、模型任务、Canon、state、summary 或 vector schema。上下文组装和 GET 不会写 context、summary、Canon、vector 或同步外部 Vault。
- `evaluation_engine/legacy_adapter.py::LegacyEvaluationAdapter` 为旧 quality/continuity JSON 提供只读兼容视图；`/api/quality-report` 与 `/api/continuity-report` 已转发该适配器，保留主要旧字段并标记 `source_format=legacy`、`read_only=true`，不会创建统一 EvaluationReport、索引或生命周期记录。
- 未处理边界：Canon 写入、summary 生成、真实 memory 数据迁移、vector 重建、Obsidian 同步、模型 Prompt/任务、遗留报告删除或迁移，以及前端导航；这些留待 16.3 或后续明确阶段。

## 15. 16.3 实施状态（2026-07-16）

- Canonical API ownership is registered in `web/api_registry.py`, without adding a gateway or a second route tree. The active canonical handlers are Planning (`/api/planning/*` through PlanningMutationService compatibility calls), Evaluation (`/api/evaluations*`), Revision (`/api/revisions*`), version selection/writes (VersionWriterFacade compatibility path), and read-only context preview (`/api/narrative-memory/context-preview` through ContextAssemblyService).
- `web/api_compatibility` responsibility is explicit and additive: `/api/quality-report`, `/api/continuity-report`, and `/api/planning/next-chapter` retain their path and response body, advertise safe `X-StoryOS-*` compatibility headers, and do not become removal candidates. Quality and continuity reads remain LegacyEvaluationAdapter projections; the next-chapter write remains a PlanningMutationService path.
- Canonical evaluation pagination now has one strict rule: default `limit=20`, maximum `100`, bounded cursor length, explicit 400 errors, `next_cursor`, and empty-list semantics. No offset/cursor conversion was introduced for APIs that do not actually expose history pagination.
- The public narrative-memory context preview now composes a read-only ContextAssemblyService package. It does not accept client paths, initialize vector storage, write a context snapshot, or alter narrative memory. Explicit context snapshot commands remain explicit writes outside GET.
- The visible primary evaluation entry remains the narrative evaluation center. The old quick quality action is hidden rather than removed, and quality/continuity panels remain version-workspace compatibility views. No new top-level navigation or centre was created.
- `web/static/app.js` is the shared primary request boundary: it tracks request generation, cancels in-flight requests on project changes, and stops JobManager polling on project changes or page unload. The existing revision, planning studio, and planning-control workspaces reuse this request boundary for their direct requests. Existing terminal-state polling remains queued/running only.
- Storage ownership is unchanged for domain semantics: Planning writes use PlanningMutationService, Evaluation reports use EvaluationService, revision candidates use RevisionService, work-version writes and selected pointers use VersionWriterFacade-compatible paths, and ContextAssemblyService stays read-only. New stage code does not write legacy report, version, context, or index paths.
- Remaining compatibility responsibility: legacy report readers, the legacy quality/continuity analyzer producer endpoints, legacy version naming/reading, and deprecated deep links remain until actual frontend/CLI/test/reference evidence permits a later 16.4 removal review. The analyzer producers are hidden from the primary UI and registered as `deprecated_internal`; they remain necessary to read or produce the old evidence format consumed by existing compatibility views. 16.4 is not authorized to delete anything without that evidence and final data-compatibility validation.

## 16. 16.4-A deletion audit status (2026-07-16)

- This is a read-only deletion decision audit, not a cleanup or migration. The full evidence matrix is in `docs/architecture/story-os-deletion-audit-16-4-a.md`; no source, route, frontend file, test, temporary directory, backup, or real data was removed.
- Summary: `KEEP_ACTIVE=6`, `KEEP_ANALYZER=2`, `KEEP_COMPAT=11`, `KEEP_DATA_READER=2`, `KEEP_TEST_INFRA=3`, `DELETE_CANDIDATE=0`, `TEMP_CLEANUP_CANDIDATE=14`, `DEFER_INVESTIGATE=1`, `DATA_RETENTION_DEFER=9`.
- The 14 untracked `.pytest-tmp-phase-16-2-*` directories are the only proposed R0 cleanup batch. They are outside real `data/`, but still require a new Batch 0 snapshot and explicit user approval before any literal-path deletion. No `.bak`, Canon, Memory, Vector, version, candidate, evaluation, or adoption-audit data is eligible.
- The core objects that remain non-removable are Evaluation quality/continuity analyzers, legacy report readers, VersionManager historical naming/list/read/selected-pointer symbols, `build_working_context()` compatibility, all five compatibility/deprecated registry routes, and the visible/hidden frontend compatibility boundary.
- `web/static/planning-studio.js` is not currently template-loaded but is referenced by a static test and historical planning audit; it is `DEFER_INVESTIGATE`, not a deletion candidate.
- 16.4-B proposal: Batch 0 snapshot and approval; Batch 1 only selected R0 pytest artifacts; Batch 2/3 have no approved code/frontend candidates; Batch 4 compatibility routes/readers is deferred; Batch 5 documentation/ignore-policy review follows physical work. A post-deletion final regression must include unique-basetemp full pytest and protected-data checks.

## 17. 16.4-BV final architecture validation status (2026-07-16)

- The five authority boundaries remain unchanged: PlanningMutationService -> DataStoreWriteFacade -> DataStore; EvaluationService formal reports with retained analyzers/readers; RevisionService contracts/candidates; VersionAdoptionService/VersionWriterFacade work versions; and read-only ContextAssemblyService packages. Canonical API ownership and the five Compatibility/deprecated routes remain registered. No business code was deleted (`DELETE_CANDIDATE=0`).
- The fourteen approved R0 pytest directories were validated but could not be physically deleted because the environment rejected the literal deletion command before execution. The root Git ignore rule is `/story-os-demo/.pytest-tmp-phase-*/`; cleanup is deferred to 16.4-BC and is a workspace-hygiene task, not a code or architecture blocker.
- Static acceptance passed: core Python compileall and nine first-party JavaScript syntax checks. A targeted pytest process completed without a captured final summary, so it is not used as a passing acceptance claim.
- The serial full pytest had a failure marker at approximately 23%, then its runner session lost the final pytest summary before counts, traceback, and exit code could be captured. It is not passing; no repair, rerun, HTTP smoke, or model/data action followed. Stage 16 cannot formally close until a controlled final regression returns a successful final summary.
- Protected blueprint, next-plan, and state hashes remain at the established baseline. Canon, Memory, Vector, historical versions, selected pointers, Candidates, EvaluationReports, and real `.bak` data remain outside this cleanup and validation scope. Analyzer, Legacy Reader, VersionManager, and `build_working_context()` remain retained compatibility responsibilities.

## 18. 16.4-BV-R1 reliable regression result (2026-07-16)

- The code and architecture boundaries remain unchanged and no business object was removed. Root `.gitignore` contains the narrow `/story-os-demo/.pytest-tmp-phase-*/` rule; temporary-directory physical cleanup remains a separate 16.4-BC hygiene task.
- A reliable, repository-external pytest run wrote stdout, stderr, and JUnit XML to `C:\Users\ta\AppData\Local\Temp\storyos-phase-16-4bv-r1-final`. It returned exit code `1`: `608 passed, 1 failed, 1 skipped` in `73.93s` (`610` total; JUnit failures `1`, errors `0`).
- The failure is reproducible: `tests/test_data_recovery_tool.py::test_inventory_excludes_pytest_temporary_directories` expects the recovery `inventory()` function to ignore a source beneath pytest's system-TEMP basetemp, but the function returns that `story_blueprint.json` as a filesystem candidate. A one-time diagnostic rerun reproduced the assertion in `0.19s`.
- This is a real behavior/regression failure, not an output-session loss or approved-temp-directory cleanup issue. No repair was made under 16.4-BV-R1. HTTP smoke was skipped. Stage 16 remains open until an approved fix and a subsequent successful full regression are completed; all Analyzer, Legacy Reader, VersionManager, Context compatibility, and data-retention boundaries remain intact.

## 19. 16.4-BV-F1 Data Recovery final regression result (2026-07-16)

- The only repaired boundary is the read-only Data Recovery inventory filter in `tools/data_recovery.py`. It now rejects known pytest temporary-directory structures before opening/parsing a candidate and prunes them during traversal, while retaining non-temporary project paths that merely contain words such as `pytest` or `temporary`. It uses normalized path components, Windows-safe case folding, no user-specific TEMP path, and does not follow symlink roots/files.
- No Engine authority, route, frontend, Canon, Memory, Vector, Version, Candidate, EvaluationReport, real data, backup, or deletion policy changed. The inventory API and returned candidate structure remain compatible.
- Acceptance passed: original regression `1 passed`; Data Recovery file `7 passed`; real-data protection `2 passed`; required compileall passed; and the auditable unique-basetemp full regression passed with exit code `0`, `610 passed`, `1 skipped`, JUnit `tests=611`, `failures=0`, `errors=0`, in `62.51s`.
- The protected blueprint, next-plan, and state SHA-256 values remain unchanged. The six existing `.bak` files remain intact. HTTP smoke is non-blocking and was not executed because no prebuilt standalone harness is both comprehensive and explicitly isolated from real project data.
- Stage 16 code and architecture acceptance is complete. Workspace-hygiene cleanup is still deferred to 16.4-BC: all 44 physical pytest temporary directories remain, including 14 literal paths already approved but blocked by environment policy. That deferral does not reopen a code or architecture blocker.
