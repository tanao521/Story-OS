# Story OS 前端重构基线（阶段 0）

审计日期：2026-07-11  
审计范围：`story-os-demo/`（当前可运行的 Story OS 应用）；未进行视觉重构或接口改动。

## 1. 当前技术栈与启动入口

| 层级 | 当前实现 | 关键文件 |
|---|---|---|
| 前端 | 原生 HTML + 原生 JavaScript + CSS；没有 React/Vue、前端打包器、客户端路由或状态库 | `web/templates/index.html`、`web/static/app.js`、`web/static/style.css` |
| Web 后端 | Python FastAPI + Jinja2 + StaticFiles | `web/app.py`、`web/routes.py`、`web/schemas.py`、`web/view_models.py` |
| 服务入口 | CLI 调度后以 Uvicorn 启动 | `main.py` 的 `main()`、`run_web_server()` |
| 业务层 | `commands.py` 编排；`core/` 生成与提交；`system/` 状态、版本、审核、存储与集成 | `commands.py`、`core/`、`system/` |
| 持久化 | 本地 JSON、Markdown、章节文件、版本文件；Chroma 用于向量索引 | `data/`、`chapters/`、`logs/` |
| 测试 | pytest + FastAPI TestClient | `tests/`（Web/API、项目生命周期、版本、流水线、质量、记忆等） |

当前 Web 启动命令是：

```powershell
cd D:\novel\StoryOS\story-os-demo
.\.venv\Scripts\python.exe main.py web
```

默认监听 `127.0.0.1:7860`，入口 URL 为 `/`。`web/app.py` 挂载 `/static` 并注册 `web.routes.router`；HTML 再加载 `/static/app.js`。

## 2. 目录与职责清单

| 路径 | 职责 |
|---|---|
| `web/templates/index.html` | 唯一页面模板：首次创建向导、仪表盘、预览、编辑、版本、审核、Todo、Ask Story、日志 |
| `web/static/app.js` | 全部浏览器状态、fetch 封装、DOM 渲染、确认弹窗、页面内操作日志 |
| `web/static/style.css` | 所有页面样式与响应式布局 |
| `web/routes.py` | HTML 路由与 API 边界；不得在此复制核心业务逻辑 |
| `web/schemas.py` | 已使用的 Pydantic 请求模型（版本、人工改稿、审核、Todo、问答、首次创建） |
| `web/view_models.py` | `api_ok` / `api_error` 统一响应形状 |
| `core/` | 项目结构、首次向导、蓝图、角色/世界观、章节规划、草稿、编辑、提交 |
| `system/` | 流水线、版本、归档、审核、质量、状态、待办、记忆、Obsidian、向量索引、问答 |
| `llm/` | 模型客户端、规划服务、提示词、健康检查 |
| `data/` | 当前项目的权威运行数据和生成产物 |
| `data/pipeline_runs/` | 每次章节流水线报告（JSON + Markdown） |
| `data/archive/` | 章节/版本的安全归档，不是永久删除 |
| `tests/` | 回归保护；重点 Web 用例：`test_web_routes.py`、`test_web_api_contract.py`、`test_project_assets_api.py`、`test_writing_constraints_api.py` |
| `design_refs/` | 现有视觉参考和 UI PRD；不参与运行 |

说明：工作区根目录还包含顶层 `README.md`、`pyproject.toml` 和 `scratch/` 副本；实际可运行应用是 `story-os-demo/`，后续重构应避免误改 `scratch/`。

## 3. 页面、组件与前端状态

这是单模板、多区块页面，而不是多个路由页面。

| 页面/区块 | 模板节点 | 浏览器逻辑 | 真实能力 |
|---|---|---|---|
| 首次创建向导 | `#setup-view`、`#setup-form` | `initializeApp`、`createStoryProject` | 创建本地项目的 story spec、state 和基础项目文件 |
| 主仪表盘 | `#dashboard-view` | `refreshStatus`、`renderFlowTrack` | 展示项目、阶段、下一步、记忆、Todo 和质量摘要 |
| 章节归档 | `#chapter-archive-panel` | `renderChapterArchive`、`archiveChapter` | 带确认的安全归档 |
| 项目档案 | `#project-assets-panel` | `loadProjectAssets`、`saveProjectAsset` | 编辑 story spec、蓝图、角色、世界观、规则、项目 Markdown |
| AI 写作约束 | `#writing-constraints-panel` | `loadWritingConstraints`、`saveWritingConstraints` | 写回 `story_spec.json.writing_constraints` |
| 快捷操作/创作流 | `#quick-actions-panel`、`#workflow-panel` | `runChapter`、`qualityCheck`、`syncObsidian`、`indexVault` | 执行章节流水线及维护操作 |
| 正文预览 | `#preview-panel` | `loadVersionContent`、`togglePreviewExpand`、`copyCurrentText` | 读取草稿、编辑稿、人工稿或正式章全文 |
| 人工改稿 | `#manual-editor-panel` | `loadManualSource`、`saveManualVersion` | 创建 manual 版本；不推进正式章节 |
| Diff / 连贯性 / 质量 | `#diff-panel`、`#continuity-panel`、`#quality-panel` | `loadVersionDiff`、`loadQualityReport`、内联 `checkContinuity` | 版本对比和质量报告；连贯性入口当前失配，见风险 |
| 版本与已提交章节 | `#versions-panel`、`#committed-panel` | `loadVersions`、`loadCommittedChapters` | 选中、预览、归档草稿/编辑/人工版本；查看正式章节 |
| 审核、Todo、Ask Story、健康检查 | `#review-panel`、`#todo-panel`、`#ask-panel`、`#memoryHealthPanel` | 对应动作函数 | 人工审核、任务、状态/记忆问答、记忆一致性检查 |
| 页面内日志 | `#logs-view`、`#log-output` | `logMessage`、`logApiResult` | 仅记录当前浏览器会话中的 API 结果，不持久化、不订阅 |

前端全局状态字段：`currentVersion`、`currentText`、`latestDraft`、`latestEdited`、`latestManual`、`selectedVersion`、`currentManualSource`、`projectAssets`、`currentAssetId`。这些字段均仅存在浏览器内存中；刷新时用 API 重建。

## 4. API 合同清单

除 `/api/status`、`/api/llm/health`、`/api/todos` 外，大部分操作响应统一为：

```json
{"ok": true, "message": "", "result": {}, "warnings": [], "errors": []}
```

### 项目、状态与档案

| 方法 / 路径 | 请求 | 响应/后端处理 |
|---|---|---|
| `GET /` | — | 返回 `index.html` |
| `GET /api/project/init-state` | — | `initialized`、`missing_files`、`next_action`；由 `data/story_spec.json` 是否存在决定首次向导 |
| `POST /api/project/create` | `title`、`genre`、`custom_genre`、`length_type`、`target_word_count`、世界/风格字段、`focus`、`avoid`、`anti_ai_style_rules`、`need_outline`、`use_deepseek` | `core.setup_wizard.create_story_project()` 写入项目基础文件 |
| `GET /api/status` | — | `system.status_dashboard.build_status_dashboard(full=True)`；返回 project/progress/next_chapter_state/quality/todos/memory/health/next_actions 等 |
| `GET /api/project-assets` | — | 允许编辑的档案列表和内容 |
| `POST /api/project-assets/{asset_id}` | `{ "content": "..." }` | 仅允许 `story_spec`、`story_blueprint`、`characters`、`world_bible`、`world_rules`、`project_md`；JSON 会先校验再覆盖 |
| `GET /api/writing-constraints` | — | 从 `story_spec` 归一化约束 |
| `POST /api/writing-constraints` | `chapter_word_count:{min,max}`、`pacing`、`chapter_structure`、`must_follow[]`、`must_avoid[]`、`ai_style_limits[]` | 更新 `story_spec.writing_constraints` 并同步 `anti_ai_style_rules` |
| `GET /api/llm/health` | — | 模型配置与可用性检查 |
| `GET /api/memory-health?full={bool}` | 可选 `full` | `system.memory_health.run_memory_health_check()` 报告 |

### 章节、版本、审核与维护

| 方法 / 路径 | 请求 | 响应/后端处理 |
|---|---|---|
| `POST /api/run-chapter` | `{}` | `commands.run_chapter_command(auto_commit=False, require_model=True)` |
| `POST /api/chapters/{chapter_number}/archive` | `{}` | `system.chapter_archive.archive_chapter()`；移动关联文件并更新 state/memory |
| `POST /api/quality-check` | 可为空，或 `{source_type: draft|edited|manual, version}` | `commands.quality_check_command()`；可精确评估当前预览版本 |
| `GET /api/versions` | — | 草稿、编辑、人工、已提交章节和 selected 版本 |
| `GET /api/versions/content?source_type={draft|edited|manual|committed}&version={n}` | 查询参数 | 返回 `chapter_id`、文本、标题、字数、路径、generation、quality |
| `GET /api/versions/diff?left_type&left_version&right_type&right_version` | 查询参数 | `system.text_diff.build_text_diff()` |
| `GET /api/quality-report?source_type&version` | 查询参数 | 指定版本质量报告 |
| `POST /api/versions/select` | `{source_type: draft|edited|manual, version}` | 选择后续审核/提交来源 |
| `POST /api/versions/archive` | `{source_type: draft|edited|manual, version, chapter_id?}` | 安全归档一个版本 |
| `POST /api/manual/save` | `{chapter_id, source_type, source_version, text}` | `system.manual_editor.create_manual_version()` |
| `POST /api/review/approve` | `{force:false, polish:null|bool}` | 低分先返回 `need_confirm`；批准后可 AI 润色并提交，再同步/索引 |
| `POST /api/review/reject` | `{}` | 写入 rejected 审核状态 |
| `POST /api/review/later` | `{}` | 写入 pending 审核状态 |
| `GET /api/todos` | — | open Todo 列表（该接口不是统一响应包装） |
| `POST /api/todos` | `{title,type,priority,chapter_id?}` | 创建 Todo |
| `POST /api/todos/{id}/done|reopen|cancel` | `{}` | 更新 Todo 状态 |
| `POST /api/ask` | `{mode: state|memory|story, question, use_llm, use_vector}` | 状态问答、记忆问答或故事问答 |
| `POST /api/sync-obsidian` | `{}` | 同步已提交内容到 Obsidian |
| `POST /api/index-vault` | `{}` | 建立/更新向量索引 |

当前没有 Web API 或 UI 用于列出、切换多个小说项目；`core.project.resolve_current_project_root()` 只在底层支持 `.story_os/config.json` 的 `active_project` 和 `projects/{name}` 解析。

## 5. 真实功能与数据流映射

| 功能 | 前端入口 | API / 处理链 | 主要读写数据与状态 |
|---|---|---|---|
| 新建项目 | 首次向导提交 | `/api/project/create` → `create_story_project` → `ensure_project_structure` | `story_spec.json`、`state.json`、`project.md`、`project_config.json`、基础蓝图/资产占位文件 |
| 项目切换 | 无实际 UI | 仅底层 `resolve_current_project_root` 支持 active project | `.story_os/config.json`；当前 Web 固定相对 `data/` |
| 项目配置 | 首次创建；项目档案；约束面板 | 创建 API；`/api/project-assets/*`；`/api/writing-constraints` | story spec、允许的基础档案；`project_config.json` 未被档案面板暴露 |
| Story Blueprint | 项目档案的 story_blueprint 文本编辑器 | `GET/POST /api/project-assets/story_blueprint` | `data/story_blueprint.json`；创建项目时 `ensure_project_structure` 可生成/修复基础结构 |
| 下一章大纲 | 当前无单独的可视化编辑器 | `run-chapter` → `plan_next_command`；CLI `plan-next` | `data/next_chapter_plan.json/.md`、`state.next_chapter_plan` |
| 章节列表/正文 | 已提交章节与版本列表 | `/api/versions`、`/api/versions/content` | `data/chapters/chapter_XXX.md` 和版本目录 |
| 手动章节编辑 | Manual Edit | `/api/manual/save` → `create_manual_version` | `data/manual/chapter_XXX_manual_vXXX.{json,md}`；不推进 `current_chapter` |
| 删除章节 | 标注为“归档”并二次确认 | `/api/chapters/{n}/archive` → `archive_chapter` | 移动到 `data/archive/chapters/chapter_XXX/`；更新 `state.archived_chapters` 和 memory index |
| 版本记录 | Draft / Edited / Manual / Published | `/api/versions*`、`system.version_manager` | `data/drafts/`、`data/edited/`、`data/manual/`、`data/versions/`、`data/chapters/` |
| 生成下一章 | “生成下一章到待审核” | `/api/run-chapter` → `run_chapter_command` → `run_single_chapter_pipeline` | 见下方完整链路 |
| AI 写作约束 | Writing Rules 面板 | `/api/writing-constraints` | `story_spec.writing_constraints`；同步 `anti_ai_style_rules` |
| 本地预览 | 正文预览、展开、复制 | `/api/versions/content` | 只读文本进 `currentText`；无独立预览路由 |
| 日志/状态/错误 | 页面日志、状态总览、记忆健康 | 所有 `runAction`/`runWithBusy`；`/api/status`、`/api/memory-health` | 页面日志仅内存；流水线持久化到 `data/pipeline_runs`；错误以 `message/errors/warnings` 呈现 |
| 失败重试 | 无专用“重试失败任务”按钮 | 可再次点击生成；CLI 有 `regenerate-draft`、`reedit-draft` | 新版本/新 pipeline 报告；没有队列、恢复 API 或重试状态机 |

### “生成下一章”完整调用链（必须保护）

```text
runChapter() in app.js
  -> POST /api/run-chapter
  -> commands.run_chapter_command(auto_commit=False, require_model=True)
  -> system.pipeline_runner.run_single_chapter_pipeline(...)
     -> build-context
     -> plan-next                 -> data/next_chapter_plan.json/.md
     -> write-draft (真实模型)    -> data/drafts + version index
     -> prepare review record     -> data/reviews + state.current_stage=waiting_for_review
     -> save pipeline report      -> data/pipeline_runs/*.json/.md

用户审核通过
  -> POST /api/review/approve
  -> 可选 edit-draft
  -> commit-chapter（唯一正常推进 current_chapter 的操作）
  -> 归档旧候选版本、同步 Obsidian、更新向量索引
```

默认 `auto_commit=False` 是关键安全行为：生成不应自动成为正式章节。

## 6. 关键数据结构（不可变兼容面）

| 文件 | 关键字段/格式 |
|---|---|
| `data/story_spec.json` | 基础设定字段及 `writing_constraints.chapter_word_count/pacing/chapter_structure/must_follow/must_avoid/ai_style_limits` |
| `data/state.json` | `current_stage`、`current_chapter`、`plot`、`foreshadows`、`timeline`、`next_chapter_plan`、`draft`、`edited`、`review`、`last_committed_chapter`、`obsidian`、`vector_memory`、`context` |
| `data/story_blueprint.json` | `project_meta`、`basic_settings`、`narrative_settings`、`world_and_plot`、`core_rules`、`character_bible`、`story_phases`、`rolling_generation_policy` 等 |
| `data/next_chapter_plan.json` | `chapter_id`、`chapter_title`、`word_count_constraints`、`chapter_goal`、`required_context`、`scene_plan`、`conflict_design`、`pacing_design`、`continuity_constraints`、`state_updates_expected` |
| `data/pipeline_runs/*.json` | `pipeline_version`、`status`、`chapter_id`、`steps[]`、`final_state`、`review`、`warnings`、`errors`、`run_id`、`report_paths` |
| `data/chapters/chapter_XXX.md` | 正式提交的章节文本；`GET /api/versions/content?source_type=committed` 直接读取 |
| `data/{drafts,edited,manual}/..._vXXX.{json,md}` | 可选择的工作版本；版本名称和字段由 `system.version_manager` / `system.manual_editor` 依赖 |

## 7. 重构保护清单

后续视觉重构必须保持以下行为、名称和数据约定：

1. 所有现有 API 路径、HTTP 方法、请求字段和统一响应字段不变；不要把 API 变成虚构的前端 mock。
2. `main.py web`、`web.app:app`、`/`、`/static` 和 `127.0.0.1:7860` 的启动/访问方式不变。
3. `current_chapter` 只能由正常的 `commit-chapter` 流程推进；manual 保存、规划、草稿生成都不得推进。
4. `POST /api/run-chapter` 必须继续使用 `auto_commit=False`、`require_model=True`，并在审核闸门处停下。
5. 章节归档是移动而非永久删除，且要同步处理 state、版本、摘要和 memory index 的排除标记。
6. 项目档案仅编辑当前 allowlist；JSON 校验失败时不得覆盖原文件。
7. 写作约束必须保存在 `story_spec.writing_constraints`，且同步 `anti_ai_style_rules`。
8. 版本选择优先级（selected > manual > edited > draft）、版本命名和正式章 Markdown 路径保持兼容。
9. 已提交章节预览仍使用 `source_type=committed&version=<chapter_id>`。
10. 审核低分确认、审核状态、同步 Obsidian、向量索引以及 pipeline report 的副作用顺序不得改变。
11. 不在前端展示 `.env`、API key 或模型密钥；测试不得调用外部模型。
12. 目前没有日志订阅、轮询或 WebSocket；若以后新增，应作为新增能力而非替换当前同步错误反馈语义。

## 8. 已存在但未完整暴露的能力

- CLI：`blueprint`、`build-assets`、`plan-next`、`write-draft`、`regenerate-draft`、`edit-draft`、`reedit-draft`、`quality-check`、`review-draft`、`commit-chapter`、`self-check`、`memory-health`、`shell`、`ask-*`、`configure-llm`。
- 底层多项目解析：`projects/{name}` 和 `.story_os/config.json.active_project`，但当前 Web 没有项目列表、切换器或设置 API。
- LLM 健康 API 已存在，但模板没有对应可见面板。
- 质量、归档、Obsidian、向量记忆、Story QA、Todo、手工版本和安全归档都已实现，不能因主界面改版而隐藏或移除。

## 9. 风险与耦合问题

| 优先级 | 风险 | 证据与影响 |
|---|---|---|
| 高 | 前端存在调用未实现 API 的失配 | `app.js` 在已提交章的编辑分支调用 `/api/manual/commit-patch`，模板中的 `checkContinuity()` 调用 `/api/continuity-check`；`web/routes.py` 当前未声明这两个路由。视觉重构不得假定它们可用。 |
| 高 | 前端大文件、高耦合 | 单个 `app.js` 同时承担 HTTP、状态、渲染、模板字符串、确认、日志和业务动作；`index.html` 含大量 inline `onclick` 与页面尾部脚本。 |
| 高 | 单页面刷新是串行的 | `refreshAll()` 串行请求 status、committed、assets、versions、todos、constraints；首屏和大数据时易变慢，且错误只写控制台/页面日志。 |
| 中 | 缺少项目切换的完整 Web 流程 | 底层支持 active project，但 Web API 都用相对 `data/`，UI 也没有切换器；不能在重构时声称已支持多项目管理。 |
| 中 | 大纲只能原始 JSON 编辑 | 蓝图可通过 project assets 读取/保存，但没有语义化 Story Blueprint 或 Next Chapter Plan 编辑器；后者甚至未暴露在 allowlist。 |
| 中 | 运行状态不是实时任务系统 | 无任务 ID、状态轮询、事件订阅或失败重试 API；长生成请求同步阻塞浏览器动作。 |
| 中 | 数据路径双轨 | 项目结构创建 `chapters/`，而 Web 正式章节读取 `data/chapters/`；重构时必须按现有调用点区分，不能擅自合并。 |
| 中 | API 类型边界不完整 | 项目档案和写作约束 POST 手工读取 JSON；许多响应是 dict 而非明确 response model，修改 UI 时要以真实字段容错。 |
| 低 | 文档与实现有漂移迹象 | README/历史说明含旧阶段描述；应以 routes、commands、测试和实际数据为准。 |

## 10. 建议的前端组件拆分（不改变接口）

建议先保持单页路由与全部 API 不变，仅按职责拆分现有 DOM/JS：

```text
app shell
├─ ProjectBootstrap (init state + setup wizard)
├─ DashboardHeader / StatusOverview / FlowTrack
├─ ProjectAssetsEditor
├─ WritingConstraintsEditor
├─ ChapterWorkspace
│  ├─ ChapterArchive
│  ├─ VersionList / CommittedChapterList
│  ├─ ManuscriptPreview / DiffViewer / QualityReport
│  ├─ ManualEditor
│  └─ ReviewControls
├─ Operations (run, quality, Obsidian, index)
├─ SideTools (Todo, MemoryHealth, AskStory)
└─ ActivityLog / ApiClient
```

先抽取不含业务改变的 `ApiClient`（保留 `apiGet/apiPost` 语义）、响应标准化、DOM 查询与 escape 工具，再逐块迁移渲染函数。不要在第一轮同时重写模板、CSS 和调用链。

## 11. 后续阶段实施顺序

1. **阶段 1：稳定壳层和信息架构** — 从 `web/templates/index.html`、`web/static/style.css`、`web/static/app.js` 的布局壳、导航锚点、状态区开始；保留所有 ID、`onclick` 或提供等价兼容绑定。
2. **阶段 2：项目与规划工作区** — `ProjectAssetsEditor`、约束面板、状态/流程图；仍使用现有 `/api/project-assets` 与 `/api/writing-constraints`。
3. **阶段 3：章节工作台** — 版本列表、已提交章节、正文预览、manual 编辑、diff、质量与审核；以 `web/routes.py` 的真实版本合同为验收基线。
4. **阶段 4：运行可观测性** — 先改善当前同步 loading/error/log 表达；只有获得明确授权后才设计任务状态 API、轮询或订阅。
5. **阶段 5：补齐已确认失配功能** — 在用户授权的后端小改阶段，单独决定并实现/移除 `continuity-check` 与 `manual/commit-patch` 的 UI 入口；本次不修。
6. **每阶段回归** — 至少运行相关 Web/API pytest、Python 编译和 `node --check web/static/app.js`；对生成、审核、归档、版本选择做现有数据的手工验证。

## 12. 本阶段允许的后续代码修改

- 修复已证实会阻断启动、导入或现有页面基础使用的问题。
- 为现有 API 合同补足必要且兼容的类型定义。
- 在不改变路径、方法、参数、返回字段与副作用的前提下，去重 API 调用封装。
- 添加本基线文档、针对既有功能的回归测试或只读检查脚本。

不允许：修改后端合同或数据结构、变更 `story_blueprint.json`/`pipeline_runs`/章节文件格式、换框架、引入大型 UI 框架、删除现有功能，或开始大规模视觉重写。

## 13. 启动与基线验证结果

- `python main.py web` 成功启动 Uvicorn，服务地址为 `http://127.0.0.1:7860`。
- `GET /` 返回 200，页面包含 `Story OS Web Console`。
- 当前项目已初始化；状态为已提交第 4 章、下一章为第 5 章；版本接口返回 4 个正式章节，当前没有待审 draft/edited/manual 版本。
- 已验证 `project-assets`、`writing-constraints`、`memory-health`、`versions` 和 `llm/health` 的基础响应；LLM 健康检查报告写作模型可用。
- 验证完成后应停止本地开发服务器；本次未执行任何生成、保存、归档或后端接口修改。
