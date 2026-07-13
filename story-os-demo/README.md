# Story OS Demo

Story OS Demo 是一个个人用的轻量级 AI 小说工作流系统 Demo。

## v1.5: API ??? draft generation

Formal draft generation now uses the API-based large model configured in `.env`.
It does not rely on the local localhost:11434 endpoint.

### Required config

```env
LLM_PROVIDER=api
WRITE_MODEL_BASE_URL=https://api.openai.com/v1
WRITE_MODEL_NAME=gpt-4o
WRITE_MODEL_API_KEY=your_api_key
WRITE_MODEL_TIMEOUT_SECONDS=180
# Optional aliases also supported: MODEL_* / OPENAI_* / DEEPSEEK_*
```

### Health check

```bash
GET /api/llm/health
python main.py check-llm
python main.py check-llm --ping
```

`GET /api/llm/health` returns the active provider, key presence, and a no-write test generation result.
`check-llm --ping` verifies the API write path before formal `write-draft` runs.


## 核心原则

Story OS 采用滚动式逐章生成，不一次性生成全书章节。
每次只规划下一章，写完后更新状态，再决定下一章。

当前系统不写正文、不接真实模型、不实现向量库、不提供 WebUI。
当前版本：v0.1 是小说立项向导；v0.2 是全书高层蓝图。v0.2 只生成 3~5 个故事阶段，不生成章节列表。
运行方式：python main.py setup；python main.py blueprint；pytest。python main.py 兼容 setup；python main.py outline 会提示改用 blueprint。
setup 生成 data/story_spec.json、data/state.json、data/project.md；blueprint 生成 data/story_blueprint.json、data/story_blueprint.md，并增量更新 data/state.json。
后续路线：v0.3 生成角色卡和世界观细化；v0.4 生成下一章计划；v0.5 开始写当前章。
v0.3：角色卡 + 世界观设定。运行 python main.py build-assets 会生成 data/characters.json、data/characters.md、data/world_bible.json、data/world_bible.md，并更新 state。当前仍然不写正文、不调用真实大模型；后续 v0.4 才生成下一章计划。
v0.4：生成下一章计划。运行 python main.py plan-next 会生成 data/next_chapter_plan.json、data/next_chapter_plan.md，并更新 state；plan-next 不修改 current_chapter，不写正文。完整命令：python main.py setup；python main.py blueprint；python main.py build-assets；python main.py plan-next；pytest。后续 v0.5 才开始根据下一章计划写当前章。
v0.5：根据下一章计划写当前章草稿。运行 python main.py write-draft 会生成 data/drafts/chapter_001_draft.json 和 data/drafts/chapter_001_draft.md，并更新 state；write-draft 不提交章节、不推进 current_chapter。完整命令：python main.py setup；python main.py blueprint；python main.py build-assets；python main.py plan-next；python main.py write-draft；pytest。后续 v0.6 才加入提交章节、更新状态、生成摘要和写入记忆。
v0.6：提交当前章草稿，生成正式章节、章节摘要和本地 memory_index，并更新 state。完整流程：setup -> blueprint -> build-assets -> plan-next -> write-draft -> commit-chapter -> 再次 plan-next。plan-next 和 write-draft 不推进章节，commit-chapter 才推进 current_chapter；当前仍然不调用真实大模型，不实现向量库。完整命令：python main.py setup；python main.py blueprint；python main.py build-assets；python main.py plan-next；python main.py write-draft；python main.py commit-chapter；pytest。
v0.7：构建低 token 写作上下文。运行 python main.py build-context 会生成 data/context/current_context.json 和 data/context/current_context.md。推荐循环：setup -> blueprint -> build-assets -> plan-next -> write-draft -> commit-chapter -> build-context -> plan-next -> write-draft -> commit-chapter -> 重复。最近3章使用原文，更早章节只用摘要；v0.7 使用规则检索，后续可替换为 Chroma / FAISS / 向量库；不要把全书原文塞进 prompt。完整命令：python main.py setup；python main.py blueprint；python main.py build-assets；python main.py plan-next；python main.py write-draft；python main.py commit-chapter；python main.py build-context；pytest。
v0.8：同步到用户真实 Obsidian Vault，不再创建项目内 vault/。运行 python main.py sync-obsidian 会读取 .story_os/config.json，并在 Vault 内创建 StoryOS/ 项目文件夹；第一次缺少配置时会询问 Vault 路径。如果想换 Vault，修改 .story_os/config.json。当前配置的 Vault 为 D:/嵌入式开发/novel_agent。v0.8 不接向量库，v0.9 才做向量库 / 语义检索。完整命令：python main.py setup；python main.py blueprint；python main.py build-assets；python main.py plan-next；python main.py write-draft；python main.py commit-chapter；python main.py build-context；python main.py sync-obsidian；pytest。
LLM 配置检查：python main.py check-llm 只读取 .env 并脱敏显示配置，不发起请求；python main.py check-llm --ping 才会对 DeepSeek 和本地 OpenAI-compatible 服务发送“只回复 OK”的最小连通性测试。


## v1.0：DeepSeek 规划层

v1.0 只把 DeepSeek 接入规划层：`setup`、`blueprint`、`plan-next`。系统仍然不使用 DeepSeek 写正文、不润色正文、不提交章节、不构建上下文、不同步 Obsidian、不实现向量库。

启用方式：

```bash
python main.py configure-llm --enable
python main.py check-llm
python main.py blueprint
python main.py plan-next
pytest
```

关闭方式：

```bash
python main.py configure-llm --disable
```

`.env` 中只保存敏感配置：

```env
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

`.story_os/config.json` 只保存非敏感开关：

```json
{
  "use_deepseek_for_planning": true
}
```

如果 Key 缺失、API 请求失败、返回内容不是 JSON、或 JSON 缺少字段，系统会自动回退到本地 mock 规划，并尽量用 mock 补齐缺失字段。DeepSeek 输出必须是 JSON；即使启用 DeepSeek，也坚持滚动式逐章生成：每次只规划下一章，写完后更新状态，再决定下一章。


## v1.1：本地模型写当前章草稿

v1.1 只把本地 OpenAI-compatible 模型接入 `write-draft`。DeepSeek 仍负责规划层，本地模型只负责当前章草稿；`commit-chapter` 才会推进 `current_chapter`。如果本地模型不可用、返回过短、返回 JSON、或输出大纲/说明，系统会自动 fallback 到 mock。

本地模型配置只放在 `.env`：

```env
LOCAL_MODEL_API_KEY=ollama
LOCAL_MODEL_BASE_URL=http://localhost:11434/v1
LOCAL_MODEL_NAME=qwen2.5:7b
USE_LOCAL_MODEL_FOR_DRAFT=true
```

常用命令：

```bash
python main.py check-llm
python main.py check-llm --ping
python main.py write-draft
pytest
```

限制：本地模型不会规划整本书，不会生成大纲，不会提交章节，不会更新 state，不会一次写多章，也不会把全书历史原文塞进 prompt；最近原文章节最多使用 3 章，更早章节只使用摘要或检索结果。


## v1.2：DeepSeek 后处理 / 编辑器

新增命令：

```bash
python main.py edit-draft
```

`.env` 示例：

```env
USE_DEEPSEEK_FOR_EDITING=true
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

v1.2 中 DeepSeek 只编辑当前章草稿：去 AI 味、修正不自然句式、减少模板句和破折号，并保持章节计划、人物声音、世界观规则和结尾钩子不变。DeepSeek 不规划剧情、不写下一章、不更新 state、不推进 current_chapter。如果 DeepSeek 不可用，`edit-draft` 会使用本地规则编辑 fallback。

推荐流程：

```text
setup -> blueprint -> build-assets -> build-context -> plan-next -> write-draft -> edit-draft -> commit-chapter -> sync-obsidian -> build-context -> 下一轮 plan-next
```

`commit-chapter` 会优先提交 `data/edited/chapter_XXX_edited.json`；如果编辑版不存在，则提交 `data/drafts/chapter_XXX_draft.json`。只有 `commit-chapter` 会推进 `current_chapter`。


## v1.3：一键单章流水线

方式 A：手动逐步执行

```bash
python main.py build-context
python main.py plan-next
python main.py write-draft
python main.py edit-draft
python main.py commit-chapter
python main.py sync-obsidian
python main.py index-vault
```

方式 B：一键单章流水线

```bash
python main.py run-chapter
```

`run-chapter` 一次只处理一章，不会一次生成多章，也不会循环生成全书。`plan-next`、`write-draft`、`edit-draft` 都不会推进章节，只有 `commit-chapter` 会推进 `current_chapter`，且流水线结束后最多推进 1 章。某一步失败时，可以回到对应单步命令修复后继续。

流水线顺序：

```text
build-context -> plan-next -> write-draft -> edit-draft -> commit-chapter -> sync-obsidian -> index-vault
```

每次运行会保存报告：

```text
data/pipeline_runs/run_chapter_001.json
data/pipeline_runs/run_chapter_001.md
```


## v1.4：人工审核闸门

推荐流程：

```bash
python main.py run-chapter
python main.py review-draft
```

`run-chapter` 默认只生成到待审核状态，不会自动提交，也不会推进 `current_chapter`。运行 `review-draft` 后选择：

```text
approve
```

才会执行 `commit-chapter -> sync-obsidian -> index-vault`。

如果希望恢复一键自动提交，需要双重确认：

1. 在 `.story_os/config.json` 中设置：

```json
{
  "review_gate": {
    "enabled": true,
    "allow_auto_commit": true
  }
}
```

2. 显式运行：

```bash
python main.py run-chapter --auto-commit
```

如果配置不允许，即使命令传入 `--auto-commit`，流水线也会停在待审核状态。

## v1.5：草稿版本管理

v1.5 为当前章草稿和编辑稿加入轻量版本管理。系统仍然坚持滚动式逐章生成：不会一次性生成多章，不会生成全书正文，`commit-chapter` 才会推进 `current_chapter`。

新增命令：

```bash
python main.py regenerate-draft
python main.py reedit-draft
python main.py reedit-draft --draft-version 2
python main.py compare-drafts
python main.py compare-drafts --select edited:1
python main.py review-draft
pytest
```

版本化文件示例：

```text
data/drafts/chapter_001_draft_v001.json
data/drafts/chapter_001_draft_v001.md
data/edited/chapter_001_edited_v001.json
data/edited/chapter_001_edited_v001.md
data/versions/chapter_001_versions.json
```

兼容文件仍会保留：

```text
data/drafts/chapter_001_draft.json
data/drafts/chapter_001_draft.md
data/edited/chapter_001_edited.json
data/edited/chapter_001_edited.md
```

`review-draft` 新增 `versions` 和 `select` 操作。提交优先级为：已选择版本 -> 最新 edited -> 最新 draft。选中版本缺失时会回退到最新可用版本并给出 warning。

## v1.6：质量评估器

v1.6 新增 `quality-check`，用于对当前章 draft / edited 版本生成质量报告。它只读版本文本和轻量设定，不写正文、不修改正文、不推进 `current_chapter`，质量分只辅助人工审核，不会强制阻止提交。

常用命令：

```bash
python main.py quality-check
python main.py quality-check --all
python main.py quality-check --edited-version 1
python main.py compare-drafts
python main.py review-draft
```

推荐流程：

```text
run-chapter
  -> quality-check
  -> compare-drafts
  -> 如果质量不满意：
       regenerate-draft
       reedit-draft
       quality-check --all
  -> compare-drafts --select edited:2
  -> review-draft
  -> approve
```

`compare-drafts` 会显示已有质量分；`review-draft` 会显示当前版本质量摘要，并支持输入 `quality` 生成或刷新报告。若当前版本质量分低于 0.65，approve 前会二次确认，但不会自动拒绝。

## v1.7：项目状态仪表盘

v1.7 新增 `status` 命令，用于一眼查看项目进度、下一章状态、质量评分、文件健康、同步状态和下一步建议。`status` 只读取状态并保存报告，不写正文、不修改章节、不推进 `current_chapter`，也不会调用 DeepSeek、本地模型、Obsidian 或向量库。

常用命令：

```bash
python main.py status
python main.py status --full
python main.py status --json
```

建议每天写作前先运行：

```bash
python main.py status
```

然后根据“下一步建议”继续执行 `setup`、`blueprint`、`build-assets`、`run-chapter`、`quality-check`、`review-draft`、`sync-obsidian` 或 `index-vault`。

每次运行会保存：

```text
data/status/latest_status.json
data/status/latest_status.md
```



## v1.8：任务队列 / To-do 系统

v1.8 新增轻量待办系统，用于记录人工修改意见、伏笔提醒、设定补全、章节重写任务、质量问题和灵感。todo 只管理任务，不写正文、不修改正文、不提交章节、不推进 `current_chapter`。

常用命令：

```bash
python main.py todo
python main.py todo add "重写第3章结尾" --chapter 3 --type revision --priority high
python main.py todo list
python main.py todo list --status open
python main.py todo list --type style
python main.py todo list --chapter 3
python main.py todo done 1
python main.py todo reopen 1
python main.py todo delete 1
python main.py todo edit 1 "新的任务标题"
python main.py todo from-quality
python main.py todo from-quality --report data/quality_reports/chapter_001_edited_v001_quality.json
```

推荐流程：

```text
quality-check
  -> todo from-quality
  -> todo list
  -> 人工处理重要问题
  -> review-draft
  -> approve
```

数据文件：

```text
data/todos/todos.json
data/todos/todos.md
```

`quality report` 可以自动转换为 todo；`status` 会展示待办摘要并在 urgent 或当前章节 revision/continuity 待办存在时优先建议处理 todo。Obsidian 同步路径为：

```text
StoryOS/13_Todos/Todos.md
```


## v1.9：创作记忆问答

v1.9 新增本地规则优先的创作记忆问答能力。ask 系列命令只查询状态和记忆，不写正文、不修改正文、不提交章节、不推进 `current_chapter`。默认不调用 LLM；只有 `ask-story --llm` 或 `USE_DEEPSEEK_FOR_QA=true` 时才尝试综合回答，并保留本地 fallback。

常用命令：

```bash
python main.py ask-state "现在还有哪些 open 伏笔？"
python main.py ask-memory "钱满仓什么时候提到过传销组织？"
python main.py ask-story "第3章写作前要注意什么？"
python main.py ask-story "苏星野现在知道什么？" --llm
python main.py ask-state "现在第几章？" --json
python main.py ask-memory "铁门出现过吗？" --no-vector
python main.py ask-story "当前最重要的问题是什么？" --no-log
```

每次问答默认保存：

```text
data/qa_logs/qa_YYYYMMDD_HHMMSS.json
data/qa_logs/qa_YYYYMMDD_HHMMSS.md
```

Obsidian 同步路径：

```text
StoryOS/14_QA_Logs/
```


## v2.0：统一创作控制台 Shell

v2.0 新增交互式创作控制台。shell 只是已有命令的交互式入口，不改变原命令行为，不会自动写作，也不会自动提交；所有推进章节的行为仍然遵守 review gate 和 commit 规则。

启动：

```bash
python main.py shell
```

进入后可以输入：

```text
status
run-chapter
quality-check
compare-drafts
review-draft
todo list
ask-state 现在有哪些 open 伏笔？
ask-memory 钱满仓什么时候出现过？
ask-story 下一章写作前要注意什么？
sync-obsidian
index-vault
exit
```

常用别名：

```text
s      = status
sf     = status --full
r      = run-chapter
qc     = quality-check
cmp    = compare-drafts
td     = todo list
state  = ask-state
mem    = ask-memory
ask    = ask-story
sync   = sync-obsidian
idx    = index-vault
```

Shell 日志保存到：

```text
data/shell_logs/shell_YYYYMMDD_HHMMSS.log
```

默认不会同步 shell logs 到 Obsidian；如需启用，在 `.story_os/config.json` 中设置：

```json
{
  "sync_shell_logs_to_obsidian": true
}
```


## v2.1：轻量 Web 控制台 MVP

启动：

```bash
python main.py web
```

默认访问：

```text
http://127.0.0.1:7860
```

Web 控制台功能：

- 查看项目状态
- 生成下一章到待审核
- 查看版本并选择版本
- 质量评估
- 审核通过 / 拒绝 / 稍后
- Todo 管理
- Ask State / Memory / Story
- 同步 Obsidian
- 更新向量库索引
- 章节安全归档

限制：

- Web 不会自动提交章节
- 生成下一章后仍然进入待审核
- 审核通过才会 commit
- 默认只允许本机访问
- 不显示 API Key
- 不修改模型环境配置

依赖：

```bash
pip install -r requirements.txt
```



## Web 章节安全归档

Web 控制台提供章节归档功能，默认不是永久删除。

API：

```text
POST /api/chapters/{chapter_number}/archive
```

归档会把本地相关章节文件移动到：

```text
data/archive/chapters/chapter_XXX/
```

并写入：

```text
data/archive/chapters/chapter_XXX/archive_meta.json
```

归档后的章节不会参与普通章节列表、版本列表和后续上下文构建。Obsidian 与向量记忆不会被静默删除；如已经同步或索引，需要后续单独清理或重建。
## v2.2：Web 正文预览、版本 Diff 与质量报告

Web 控制台现在支持：

- 查看 draft / edited 正文
- 复制正文
- 选择版本
- 查看质量报告
- 生成质量评估
- 对比 draft 与 edited 差异
- 在审核区确认当前 selected 版本

使用方式：

```bash
python main.py web
```

打开：

```text
http://127.0.0.1:7860
```

推荐流程：

1. 点击“生成下一章到待审核”
2. 在版本列表中查看 draft / edited
3. 点击“对比”查看修改差异
4. 点击“生成质量评估”
5. 选择最满意版本
6. 审核通过
7. 同步 Obsidian
8. 更新向量库


## v2.3 Web 手动改稿

Web 控制台支持基于 draft / edited / manual 版本进行人工改稿，并保存为新的 manual 版本。

流程：

1. 打开 Web 控制台。
2. 查看 draft / edited 正文。
3. 进入“手动改稿”区域。
4. 选择来源版本并载入正文。
5. 在 textarea 中修改正文。
6. 保存为 manual_v001、manual_v002 等新版本。
7. manual 版本会进入版本列表并默认选中。
8. 对 manual 版本进行质量评估。
9. 审核通过后再提交为正式章节。

约束：

- manual 版本不会覆盖 draft / edited。
- 每次保存都会生成新的 manual 版本。
- 保存 manual 不会推进 current_chapter。
- 只有审核通过 / commit-chapter 才会推进章节状态。
- Web 不显示 API Key，也不会读取或展示 .env 原文。

## Project context files

This project uses two local context files for Codex:

- `AGENTS.md`: long-term project rules and safety constraints
- `PROJECT_ROADMAP.md`: completed versions and planned roadmap

Before implementing a new version, Codex should read both files.

This reduces repeated prompt tokens and keeps future iterations consistent.



## Memory Health / 记忆健康检查

Story OS 提供记忆健康检查，用于诊断长篇创作过程中以下内容是否一致：

- story_spec / state / project 是否存在
- current_chapter 是否与正式章节数量一致
- 正式章节是否有对应摘要
- draft / edited / manual 版本索引是否完整
- selected 版本是否有效
- selected 版本是否有质量报告
- Todo 是否积压过多
- memory_index 是否可能过期

### CLI

```bash
python main.py memory-health
python main.py memory-health --json
python main.py memory-health --full
```

### Web

启动 Web：

```bash
python main.py web
```

打开：

```text
http://127.0.0.1:7860
```

进入“记忆健康”区域，点击“运行检查”。

### 注意

当前 v2.4 只做检查，不做自动修复。
自动修复能力会在后续版本中单独实现。
## v2.5 Stabilization / Self Check

Common commands:

```bash
python main.py web
python main.py self-check
python main.py self-check --json
python main.py memory-health
python main.py memory-health --json
python main.py memory-health --full
```

Notes:

- First Web use opens the new story setup wizard when `data/story_spec.json` is missing.
- Manual versions are human-edited versions and do not replace draft / edited history.
- `memory-health` is check-only in this version and does not auto-fix project data.
- `self-check` checks project structure and imports only; it does not generate story content.

## v2.6：Web 控制台入口恢复说明

这次更新把几个常用入口重新放回了 Web 控制台：

- 手动改稿模块重新可见
- 右侧上下文检查器恢复了“编辑上下文”入口
- 本地知识库入口恢复可见
- 记忆与向量库健康检查入口恢复可见
- 向量库摘要会直接展示已索引到第几章、多少片段

这样做的目标是让你在同一个工作台里完成：

1. 查看章节状态
2. 对照上下文编辑草稿
3. 查询本地知识库
4. 检查记忆 / 向量库是否健康
5. 再回到版本管理和提交流程

如果浏览器缓存较旧，建议先强制刷新一次页面。

## v2.7：故事蓝图、角色档案与章节规划恢复

Web 端新增规划层入口：先生成/重建故事蓝图，再生成角色档案和世界观，最后生成下一章规划。章节规划会读取蓝图、角色档案、世界规则、已开伏笔、最近章节上下文和向量记忆；正文生成继续以 data/next_chapter_plan.json 为硬约束。

如果项目已有旧的空 characters.json 或空蓝图，点击 Web 中的生成按钮会自动补齐；已有非空档案默认不会被覆盖，除非明确点击重建。


## 当前首次创建流程

首次创建项目时，Web 端和命令行 setup 都会先保存创作问卷，再自动完成规划层初始化：

1. 根据创作意见生成全书故事蓝图（包含故事阶段和初始伏笔池）。
2. 根据蓝图生成角色档案和世界观设定。
3. 生成当前待写章节的章节计划，并登记到蓝图的 chapter_plan。
4. 后续使用 plan-next 滚动生成下一章；正文生成必须遵守当前章节计划、蓝图、角色档案和世界观规则。

默认使用本地规划模板；在首次创建时勾选 DeepSeek 并配置 DEEPSEEK_API_KEY 后，规划层会优先调用 DeepSeek，失败时自动回退到本地模板。手动执行 blueprint、build-assets 或 plan-next 仍可单独重建对应文件。
