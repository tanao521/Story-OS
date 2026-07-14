# Story OS 阶段 14.0：规划系统架构审计报告

审计日期：2026-07-14
审计范围：仅审计阶段 5、阶段 7 与阶段 13.1 的既有实现；不实现阶段 14.1 的战略、里程碑、契约、滚动窗口、依赖图或重规划功能。

## 1. 当前工作区状态

- 工作区：`D:\novel\StoryOS\story-os-demo`；分支：`agent/phase-13-2-memory-repair`。
- 当前项目已提交到第 5 章，`data/state.json` 指向第 6 章的待写计划；向量记忆记录为 72 个片段。
- 当前实际规划主链路是 `story_blueprint.json` + `next_chapter_plan.json`，而不是结构化 `story_planning.json`。
- 审计时 `data/story_planning.json` 与 `data/planning_versions/` 均不存在，说明结构化规划服务尚未在这个项目被物化使用。
- 本报告写入前工作树无未提交变更；本报告是本阶段唯一新增文件。

## 2. 现有规划数据模型

现有模型并非单一对象，而是三层并存：

| 层级 | 载体 | 主要字段/职责 | 当前地位 |
| --- | --- | --- | --- |
| 长期蓝图 | `data/story_blueprint.json` | `core_premise`、`main_arc`、`core_conflict`、`ending_direction`、`story_phases`、`initial_foreshadow_pool`、`chapter_plan`、`rolling_generation_policy` | 现行长期规划来源 |
| 单章执行 | `data/next_chapter_plan.json` | `chapter_goal`、`phase_position`、`required_context`、`scene_plan`、冲突/节奏/高潮设计、连续性约束、预期状态更新 | 正文生成的当前硬约束 |
| 结构化管理 | `system/planning_service.py` → `data/story_planning.json` | `story`、`volumes`、`phases`、`chapters`、`plot_threads`、`character_arcs`、`foreshadowing`、`conflicts`、`climaxes`、`world_rule_refs` | 已有服务，当前项目未落盘 |

`system/planning_service.py` 可从旧蓝图无损迁移：保留 `legacy_blueprint`，并将 `story_phases`、`chapter_plan`、`plot_threads`、`character_arcs`、`foreshadows` 映射为结构化集合。它为每种实体补齐稳定 ID 与排序号；章节还可引用卷和阶段。

## 3. 现有规划文件和目录

```text
data/
├─ story_spec.json                 # 创作问卷和写作约束
├─ story_blueprint.json/.md        # 长期蓝图和阶段/伏笔池
├─ characters.json/.md             # 角色档案和关系图
├─ world_bible.json/.md            # 世界规则与地点
├─ state.json                      # 当前章、剧情状态、已开伏笔、时间线
├─ next_chapter_plan.json/.md      # 唯一的当前执行计划
├─ context/current_context.json/.md# 三层写作上下文
├─ narrative_memory/               # 已确认事件、投影状态、时间线、冲突和快照
├─ creative_loop/                  # 反思、问题、提案、实验、结果、演化记录
└─ versions/、canon_versions/      # 正文版本与正史版本
```

结构化规划服务预留的落盘位置为 `data/story_planning.json`、`data/planning_versions/planning_*.json`。当前项目没有这两项；不能在阶段 14.1 未定义迁移来源与冲突规则前自动创建、覆盖或反向同步它们。

## 4. 规划 API

当前 API 分为两组：

1. 当前 Web 正在使用的滚动规划 API：
   - `POST /api/planning/blueprint`：调用 `commands.generate_blueprint_command()`。
   - `POST /api/planning/assets`：生成角色档案和世界观。
   - `GET /api/planning/next-chapter`：读取当前单章计划。
   - `POST /api/planning/next-chapter`：空请求生成下一章；非空请求保存作者编辑后的计划，同时更新 `state.json` 和 Markdown。
2. 结构化规划 API：
   - `GET /api/planning/overview`；`GET/POST /api/planning/{kind}`；`PUT/DELETE /api/planning/{kind}/{entity_id}`。
   - `POST /api/planning/chapters/{chapter_id}/sync-next`：将结构化章节计划合并到 `next_chapter_plan.json`。

服务层还具备 `reorder`、`list_versions`、`restore_version`，但目前没有对应的 Web 路由。结构化 API 的 `kind` 没有路由层白名单，应在后续阶段改为显式枚举和输入校验；这是加固项，不属于本次开发范围。

## 5. 规划前端

- 已挂载的中文页面是 `web/templates/index.html` + `web/static/planning-recovery.js`：展示并编辑“当前章节计划”，可查看故事阶段、生成蓝图/资产、保存单章计划。它使用滚动规划 API，符合当前正文工作流。
- 蓝图编辑器位于项目档案区域，由 `web/static/app.js` 管理；可结构化浏览与编辑 `story_blueprint.json`，并保留原始 JSON 兼容入口。
- `web/static/planning-studio.js` 和配套 CSS 存在，但该脚本没有在 `index.html` 中加载；内容仍有英文文案，且调用的 `PUT /api/planning/blueprint` 与现有路由不匹配。它是未接入的旧/实验性结构化界面，不能作为阶段 14 的直接 UI 基础。

结论：阶段 14.1 应在现有中文“章节大纲”界面内增量增加战略与契约摘要，不应激活或复制这套未挂载的英文工作室。

## 6. 下一章计划生成流程

```text
story_spec + story_blueprint + characters + world_bible + state
                         + current_context（若存在）
    → core.next_chapter_planner.plan_next_chapter()
    → 可选模型增强（当前代码仍称 DeepSeek planning）
    → data/next_chapter_plan.json/.md
    → write_draft 读取该计划；commit-chapter 才推进 current_chapter
```

`commands.plan_next_command()` 会先确保蓝图和资产完整，再构建本地模板计划；可选模型输出缺字段时以本地计划补齐，并强制修正章节号。`current_context` 提供最近章节摘要；计划器本身还从 `state.foreshadows` 读取开放伏笔。规划不推进章节，也不自动提交正文。

已知缺口：目前“阶段选择”按章节号阈值推断，尚未基于卷/阶段契约、依赖、容量、风险或作者锁定解释“为什么现在写这一章”。这正是阶段 14 后续阶段的边界，不应在 14.0 临时补写。

## 7. 规划版本机制

- 正文版本与正史版本已独立存在：`data/versions/`、`data/archive/versions/`、`data/canon_versions/`；它们不是规划版本。
- 结构化规划服务每次保存会在 `data/planning_versions/` 保存不可变快照，并写入 `data/story_planning.json`；可列举或恢复快照。
- 蓝图与下一章计划当前只依赖 `DataStore` 的备份文件（如 `.bak`）或直接保存，没有统一的规划版本号、来源版本、审批状态或跨文件原子提交。
- `sync_next_plan()` 能从结构化章节覆盖/合并到单章计划，却没有“计划版本→正文版本→正史版本”的关联链。

因此阶段 14.1 需要新增的是**规划控制层版本**，不是替换正文/正史版本管理，也不能悄然把所有蓝图编辑改成不可逆重写。

## 8. 剧情线、角色弧光和伏笔结构

- 长期蓝图：`story_phases` 包含阶段冲突、人物变化、要埋/回收的伏笔 ID；`initial_foreshadow_pool` 记录预期回收阶段。
- 项目状态：`state.json` 有 `plot.main_arc`、`sub_arcs`、`completed_events`、`foreshadows`、`timeline`；真实项目中的 `plot.main_arc` 目前为空，说明蓝图与运行态并未持续自动对齐。
- 结构化规划服务：支持 `plot_threads`、`character_arcs`、`foreshadowing`、`conflicts`、`climaxes` 实体，但当前项目尚未保存这些集合。
- `data/plot_state.json` 是另一份轻量剧情状态，当前只含空的 `open_threads`/`resolved_threads` 等字段，未见主流程读取证据。
- 角色弧光主要存在于蓝图的阶段 `character_changes`、角色档案及未物化的 `character_arcs` 中；没有当前章到角色弧光槽位的强引用。

阶段 14.1 不应复制这些内容。它应以引用 ID、来源文件、状态和约束强度建立“战略/契约”索引，并允许作者显式选择未结构化的旧字段。

## 9. 与叙事记忆的连接

- `system/context_builder.py` 已建立三层记忆：全局设定、最近章节/摘要、关键词与向量检索；`commands.build_context_command()` 额外尝试注入结构化规划的当前章节、活跃剧情线和开放伏笔。
- 阶段 7 的 `NarrativeMemoryService` 从已激活正史提取候选事件，必须经人工确认/修正后才投影为人物、地点、物品、伏笔、世界规则与时间线状态；支持冲突检查、快照、失效与人工 pin/exclusion。
- `run_chapter` 会执行叙事记忆预检，阻断存在 blocking 冲突的生成。
- 但 `plan_next_command()` 当前不直接读取阶段 7 的确认事件投影或预检结果；它只接收 `state.json` 和已有工作上下文。阶段 14.1 只能建立“可读取的证据来源”接口，不能把未确认事件写回计划。

## 10. 与创作闭环的连接

阶段 13.1 创作闭环将反思、健康、问题转化为 `future_strategy` 提案；提案携带来源正史版本、影响范围、建议与风险。作者决定会写入提案的 `author_decision` 和审计记录。

它明确不自动改写计划、正文或正史：路由返回文案和 `tests/test_creative_loop.py` 都验证提案接受后 `next_chapter_plan.json` 保持不变。当前没有“已接受提案 → 规划实体”的自动链接。

阶段 14.1 应只预留人工确认后的 `proposal_id`/`accepted_change` 来源引用；实际把提案转成计划变更，至少留到后续集成阶段并须显示差异、影响范围和撤销路径。

## 11. 重复功能风险

1. 新建第二份全书大纲会与 `story_blueprint.json` 重复，并造成蓝图、状态、单章计划三方漂移。
2. 新建另一套章节计划会绕开 `next_chapter_plan.json`，使正文生成无法确定唯一约束来源。
3. 将阶段 14“版本”混入正文或正史版本会破坏现有人工审核与提交闸门。
4. 自动采纳阶段 13 提案会违反作者控制边界，也会把建议误当事实。
5. 激活未挂载的英文 `planning-studio.js` 会引入双 UI、双 API 语义和已知路由不匹配。
6. 把叙事记忆候选事件直接当规划事实会绕过确认/修正规则。

## 12. 兼容和迁移方案

采用“既有文件为事实源、规划控制层为增量引用”的方案：

```text
story_blueprint.json ─┐
state.json            ├─> 阶段14控制层（只存来源、约束、版本、锁定和作者决定）
narrative_memory      ┤
creative_loop 提案    ┘
                              ↓（明确确认后）
                    next_chapter_plan.json
```

- **不得修改/替换**：`story_blueprint.json` 的既有字段、`next_chapter_plan.json` 的执行语义、`state.json.current_chapter` 的推进规则、正史/正文版本目录、阶段 7 的事件确认状态。
- **可扩展**：新增一个最小控制数据目录（建议 `data/planning_control/`），所有记录保存 `schema_version`、`source_refs`、`created_at`、`updated_at`、`author_confirmed_at` 和可选 `supersedes_version_id`。
- **旧项目迁移**：首次读取时只生成内存投影；作者保存第一份战略或契约时才创建控制文件。蓝图、状态、结构化规划服务的同名信息必须以来源引用呈现，不能静默合并或覆盖。
- **冲突规则**：同一信息来自蓝图、已确认叙事记忆与作者锁定时，显示冲突；正史事实和作者锁定优先，模型建议最低。任何写回既有蓝图/下一章计划都必须是作者确认的单独操作。
- **回退**：控制层读取失败或文件不存在时，现有 `plan-next`、写作和提交流程继续按当前行为运行。

## 13. 阶段 14.1 最小实现范围

仅在上述兼容基础完成以下最小闭环：

1. 新增真实需要的 `planning_engine/models.py` 与一个策略/契约服务，不预建滚动窗口、依赖图、重规划等空模块。
2. 定义并持久化 `StoryStrategy`、`NarrativeMilestone`、`VolumeContract`、`PhaseContract`、锁定记录和控制层版本；全部项目隔离、UTF-8、可追溯。
3. 只读聚合既有蓝图、运行状态、确认叙事记忆和已决定的创作提案，输出来源与冲突，不自动写回。
4. 提供最小中文 API 与现有“章节大纲”中的摘要/编辑入口；保持作者保存和批准为唯一写入动作。
5. 添加迁移、版本/锁定、冲突、项目隔离及“不改写 next_chapter_plan/正史”的针对性测试。

明确不包括：未来章节滚动窗口、依赖/调度图、容量估算、风险引擎、自动重规划、下一章生成接入、模型调用、自动接纳提案。

## 14. 风险与建议

- **最高风险：双事实源漂移。** 先定义来源优先级和显式确认写回，再新增任何生成逻辑。
- **数据质量风险：** 实际项目的运行态 `plot.main_arc` 为空，而蓝图存在主线；阶段 14 应报告差异，不自动修复。
- **接口风险：** 已有结构化规划 CRUD 没有 `kind` 白名单；在其被新 UI 使用前必须补足校验和版本/恢复 API。
- **前端风险：** 保留现有中文大纲页作为唯一入口，移除或隔离未接入的英文规划工作室，避免用户看到两套不一致的概念。
- **模型风险：** 阶段 14.1 的数据控制层应规则优先；Qwen 仅能在后续阶段作为受限建议生成者，不能决定事实、锁定或写回。
- **验证建议：** 阶段 14.1 先用临时项目的迁移夹具覆盖旧蓝图、空蓝图、结构化规划已存在、叙事记忆冲突和提案过期五种情形。

本次审计辅助验证：

```text
python -m pytest -q --basetemp <workspace temp> \
  tests/test_planning_service.py tests/test_next_chapter_planner.py \
  tests/test_planning_api.py tests/test_creative_loop.py \
  tests/test_recovered_routes.py

35 passed in 4.36s
```

首次运行受系统共享 pytest 临时目录权限影响；将 `TEMP`、`TMP` 和 `--basetemp` 指向工作区后，同一测试集全部通过。

## 15. 是否适合进入阶段 14.1

**适合，但附带准入条件。** 现有系统已经具备长期蓝图、单章执行计划、结构化规划试验服务、正史记忆、作者确认提案和稳定的单章工作流；足以建设一个增量、可回退的战略与契约层。

进入 14.1 前必须接受本报告的边界：以既有蓝图和单章计划为事实源；控制层只增量存储；所有写回都经作者明确确认；不在 14.1 提前接入滚动规划、自动重规划或模型驱动的全书决策。
