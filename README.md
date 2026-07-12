# Story OS

> 一个面向长篇小说创作的本地 AI 写作操作系统。  
> A local AI-powered operating system for long-form fiction writing.

---

## 项目简介

Story OS 是一个面向长篇小说创作的本地 AI 写作工作流系统。

它不是一个简单的“AI 写作按钮”，而是尝试把小说创作拆解成一套可控、可追踪、可审核、可长期记忆的工程化流程：

```text
小说立项
  ↓
故事蓝图
  ↓
角色卡 / 世界观
  ↓
上下文构建
  ↓
下一章规划
  ↓
草稿生成
  ↓
AI 编辑
  ↓
人工改稿
  ↓
质量评估
  ↓
人工审核
  ↓
提交正史
  ↓
同步 Obsidian
  ↓
更新向量记忆
```

它的核心目标是解决长篇小说创作中最常见的问题：

- AI 上下文不够长
- 前后剧情容易矛盾
- 人物声音容易混乱
- AI 容易自动推进剧情
- 生成内容缺少人工审核
- 长篇设定缺少长期记忆
- 草稿、编辑稿、人工修改稿难以管理
- 创作状态容易失控

Story OS 的设计理念是：

> 短上下文创作 + 外部长期记忆 + 状态系统 + 多版本管理 + 人工审核闸门。

---

## 项目亮点

### 1. 从零开始创建小说项目

Story OS 提供 Web 新建小说向导，可以从零填写：

- 小说标题
- 类型
- 篇幅
- 目标字数
- 世界观风格
- 整体基调
- 文笔风格
- 叙事视角
- 主角结构
- 感情线强度
- 剧情重点
- 禁止内容
- AI 味限制

如果项目尚未初始化，Web 控制台会优先展示“新建小说向导”，而不是直接进入空白控制台。

---

### 2. 章节级滚动生成

Story OS 不鼓励一次性生成整本小说。

它采用章节级滚动创作：

```text
plan-next 只规划下一章
write-draft 只生成当前章草稿
edit-draft 只编辑当前章
commit-chapter 才推进 current_chapter
```

这种方式可以降低长上下文压力，也更适合人工介入和长期维护。

---

### 3. 多版本写作流

每一章支持多个版本：

```text
draft   ：原始草稿
edited  ：AI 编辑版
manual  ：人工修改版
```

manual 版本不会覆盖 draft / edited，而是作为新的人工版本进入版本管理。

默认提交优先级：

```text
selected version
  ↓
latest manual
  ↓
latest edited
  ↓
latest draft
```

这保证了 AI 不会直接污染正式章节，用户始终拥有最终控制权。

---

### 4. 人工审核闸门

Story OS 默认不会自动提交章节。

章节进入正式内容前，需要经过人工审核：

```text
approve  → 提交章节
reject   → 拒绝提交
later    → 稍后处理
```

这套机制确保：

- AI 不会自动推进剧情
- 人工可以控制正史内容
- 错误版本不会轻易进入长期记忆
- 章节状态可追踪

---

### 5. Obsidian + Chroma 双记忆系统

Story OS 将长期记忆分成两层：

```text
Obsidian = 人类可读知识库
Chroma   = 机器语义检索记忆
```

Obsidian 用于保存：

- 项目设定
- 角色卡
- 世界观
- 正式章节
- 章节摘要
- 草稿
- 编辑稿
- 人工修改稿
- 质量报告
- Todo
- QA 日志

Chroma 用于向量检索，让系统可以在后续章节创作时召回早期设定和历史内容。

---

### 6. 质量评估系统

Story OS 支持对章节版本进行质量评估。

评估维度包括：

- 剧情目标匹配度
- 连续性
- 人物声音
- 文风自然度
- AI 味
- 节奏
- 章节钩子
- 可读性

质量报告会保存为 JSON 和 Markdown，方便后续追踪和同步到 Obsidian。

---

### 7. 记忆健康检查

长篇创作最容易出现“记忆污染”和“状态错位”。

Story OS 提供 Memory Health 检查，用来诊断：

- `story_spec.json` 是否存在
- `state.json` 是否存在
- `current_chapter` 是否和正式章节数量一致
- 每章是否有对应摘要
- draft / edited / manual 版本索引是否完整
- selected 版本是否有效
- 质量报告是否覆盖当前版本
- Todo 是否积压过多
- memory index 是否可能过期

命令：

```bash
python main.py memory-health
python main.py memory-health --json
python main.py memory-health --full
```

---

## 功能概览

| 模块 | 功能 |
|---|---|
| 小说立项 | 创建 story spec |
| 故事蓝图 | 生成高层故事结构 |
| 角色与世界观 | 生成角色卡、世界观设定 |
| 上下文构建 | 最近章节 + 摘要记忆 |
| 章节规划 | 只规划下一章 |
| 草稿生成 | 调用本地模型或 Mock 生成 |
| AI 编辑 | 调用 DeepSeek 或规则编辑 |
| 人工改稿 | Web 中保存 manual 版本 |
| 版本管理 | draft / edited / manual |
| 质量评估 | 章节质量报告 |
| 审核闸门 | approve / reject / later |
| 正式提交 | commit-chapter 推进章节 |
| Obsidian 同步 | 同步 Markdown 知识库 |
| 向量索引 | Chroma 语义检索 |
| 记忆问答 | ask-state / ask-memory / ask-story |
| Todo 系统 | 维护修改任务 |
| 状态仪表盘 | 查看项目当前状态 |
| 记忆健康 | 检查数据一致性 |
| Web 控制台 | 本地可视化操作入口 |

---

## 技术栈

### 后端

- Python
- FastAPI
- JSON / Markdown 文件系统存储
- Chroma 向量库
- Sentence Transformers Embedding
- OpenAI-compatible LLM Client

### 前端

- 原生 HTML
- 原生 CSS
- 原生 JavaScript
- 无 React / Vue
- 无外部 CDN

### 模型支持

- DeepSeek：规划、编辑、评估等高质量任务
- 本地模型：草稿生成
- Mock fallback：无模型时也能跑通基本流程

### 外部知识库

- Obsidian Vault
- Chroma Vector DB

---

## 项目结构

```text
story-os-demo/
├── main.py
├── commands.py
├── AGENTS.md
├── PROJECT_ROADMAP.md
├── README.md
├── .env.example
├── .story_os/
│   └── config.json
├── data/
│   ├── story_spec.json
│   ├── state.json
│   ├── project.md
│   ├── story_blueprint.json
│   ├── characters.json
│   ├── world_bible.json
│   ├── context/
│   ├── drafts/
│   ├── edited/
│   ├── manual/
│   ├── chapters/
│   ├── summaries/
│   ├── versions/
│   ├── quality_reports/
│   ├── todos/
│   ├── qa_logs/
│   ├── memory/
│   └── health/
├── system/
│   ├── setup_wizard.py
│   ├── blueprint.py
│   ├── asset_builder.py
│   ├── context_builder.py
│   ├── planner.py
│   ├── draft_writer.py
│   ├── draft_editor.py
│   ├── manual_editor.py
│   ├── version_manager.py
│   ├── quality_checker.py
│   ├── review_gate.py
│   ├── chapter_committer.py
│   ├── obsidian_sync.py
│   ├── memory_health.py
│   ├── status_dashboard.py
│   └── self_check.py
├── llm/
│   ├── deepseek_client.py
│   ├── openai_compatible_client.py
│   ├── planning_service.py
│   └── local_model_service.py
├── web/
│   ├── app.py
│   ├── routes.py
│   ├── templates/
│   │   └── index.html
│   └── static/
│       ├── app.js
│       └── style.css
└── tests/
```

实际文件结构可能会随版本略有调整。

---

## 安装与运行

### 1. 克隆项目

```bash
git clone https://github.com/your-name/story-os-demo.git
cd story-os-demo
```

---

### 2. 创建虚拟环境

Windows：

```bash
python -m venv .venv
.venv\Scripts\activate
```

macOS / Linux：

```bash
python -m venv .venv
source .venv/bin/activate
```

---

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

如果暂时没有 `requirements.txt`，可以根据项目实际依赖安装：

```bash
pip install fastapi uvicorn pydantic python-dotenv chromadb sentence-transformers requests
```

---

### 4. 配置环境变量

复制示例文件：

```bash
copy .env.example .env
```

`.env` 示例：

```env
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com

LOCAL_MODEL_API_KEY=
LOCAL_MODEL_BASE_URL=
LOCAL_MODEL_NAME=

USE_LOCAL_MODEL_FOR_DRAFT=true
USE_DEEPSEEK_FOR_EDITING=true
USE_DEEPSEEK_FOR_QUALITY_CHECK=false
```

## 启动 Web 控制台

```bash
python main.py web
```

然后打开：

```text
http://127.0.0.1:7860
```

如果终端显示的是其他端口，请以终端输出为准。

不要直接双击打开：

```text
web/templates/index.html
```

否则 CSS、JS、API 都可能无法正常工作。

---

## 第一次使用流程

第一次打开 Web 后，如果项目尚未初始化，会进入“新建小说向导”。

推荐流程：

```text
1. 新建小说项目
2. 生成故事蓝图
3. 生成角色卡与世界观
4. 构建上下文
5. 规划下一章
6. 写草稿
7. 编辑草稿
8. 手动改稿
9. 质量评估
10. 审核提交
11. 同步 Obsidian
12. 更新向量库
```

---

## 常用命令

### 自检

```bash
python main.py self-check
python main.py self-check --json
```

---

### 新建小说项目

CLI：

```bash
python main.py setup
```

Web：

```bash
python main.py web
```

然后进入网页中的“新建小说向导”。

---

### 生成故事蓝图

```bash
python main.py blueprint
```

---

### 生成角色卡和世界观

```bash
python main.py build-assets
```

---

### 构建上下文

```bash
python main.py build-context
```

---

### 规划下一章

```bash
python main.py plan-next
```

---

### 写草稿

```bash
python main.py write-draft
```

---

### 编辑草稿

```bash
python main.py edit-draft
```

---

### 查看和选择版本

```bash
python main.py compare-drafts
python main.py compare-drafts --select edited:1
python main.py compare-drafts --select manual:1
```

---

### 质量评估

```bash
python main.py quality-check
python main.py quality-check --manual-version 1
```

---

### 审核草稿

```bash
python main.py review-draft
```

---

### 提交章节

```bash
python main.py commit-chapter
```

---

### 一键单章流程

```bash
python main.py run-chapter
```

注意：

> 默认不会自动提交，仍需人工审核。

---

### 同步 Obsidian

```bash
python main.py sync-obsidian
```

---

### 更新向量索引

```bash
python main.py index-vault
```

---

### 记忆问答

```bash
python main.py ask-state "当前有哪些未解决伏笔？"
python main.py ask-memory "主角第一次进入地下室发生了什么？"
python main.py ask-story "下一章应该注意哪些连续性问题？"
```

---

### Todo

```bash
python main.py todo list
python main.py todo add "修改第一章结尾钩子"
python main.py todo done 1
```

---

### 状态仪表盘

```bash
python main.py status
python main.py status --full
python main.py status --json
```

---

### 记忆健康检查

```bash
python main.py memory-health
python main.py memory-health --json
python main.py memory-health --full
```

---

## Web 控制台功能

Web 控制台支持：

- 新建小说向导
- 状态摘要
- 章节流程操作
- 版本列表
- 正文预览
- draft / edited Diff 对比
- 质量报告展示
- 手动改稿 manual 版本
- 审核操作
- Todo 查看
- Ask Story
- 记忆健康检查

---

## 多项目使用建议

当前 Story OS 默认是单项目模式，所有小说数据都写入：

```text
data/
```

如果要同时写多本小说，建议一个小说一个项目副本：

```text
D:\novel\StoryOS\projects\末日种田
D:\novel\StoryOS\projects\玄幻新书
D:\novel\StoryOS\projects\科幻悬疑
```

每个项目都有独立的：

```text
data/
.env
.story_os/config.json
```

后续可以扩展为正式的多项目管理系统。

---

## GitHub 上传注意事项

请确保 `.gitignore` 包含：

```gitignore
# Python
__pycache__/
*.pyc
.venv/
venv/

# Env
.env

# Local data
data/
chroma/
*.log

# IDE
.idea/
.vscode/

# OS
.DS_Store
Thumbs.db
```

如果你希望上传一个空项目模板，可以保留：

```text
data/.gitkeep
```

但不要上传真实小说正文、API Key、个人 Obsidian 路径。

---

## 适合展示的项目价值

这个项目可以用于展示：

- AI Agent 工作流设计能力
- 长文本创作系统设计能力
- RAG / 向量记忆实践
- 本地知识库与 Obsidian 集成
- Web 控制台开发
- 多版本内容管理
- 人工审核机制设计
- LLM 工程化落地能力
- Python 后端工程能力
- AI 产品思维

---

## 开发状态

当前项目处于个人实验性可用阶段。

已具备完整主链：

```text
从零创建小说
→ 章节规划
→ 草稿生成
→ AI 编辑
→ 人工改稿
→ 质量评估
→ 审核提交
→ 长期记忆同步
```

后续重点不是继续堆功能，而是：

```text
真实写作使用
发现痛点
小范围修复
提高稳定性
优化 Web 使用体验
```

---

## License

本项目可根据实际情况选择开源协议。

推荐：

```text
MIT License
```

---

## 作者
Created by `tadx`

一个关于 AI Agent、长篇创作、个人知识库和本地写作系统的实验项目。

## 最新补充说明

最近一次更新已经把几个容易丢的入口补回来了：

- 手动改稿现在有独立入口，不只是藏在某个角落里
- 右侧上下文检查器里的“编辑上下文”已经恢复可见
- 本地知识库和向量库入口也已经回到 Web 控制台
- 这些模块和章节流、版本流、记忆健康检查是联动的，适合直接在同一个页面里完成创作、改稿和核对

如果你刷新后还看不到这些卡片，先强制刷新一次浏览器缓存，再重开 Web 控制台。