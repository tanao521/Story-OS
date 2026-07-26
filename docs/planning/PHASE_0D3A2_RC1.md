# Phase 0D3A2-RC1 — Browser QA Closure

## 结论

**PASSED。** 本阶段完成了隔离原型的真实浏览器 QA、四个目标视口截图、代表性状态切换、控制台检查、可访问性快速检查、回归测试与保护性校验。Mode-switch placement 与 URL/context behavior 均已正式确认。未进入 Phase 0D3B，未修改生产页面、生产 API 或后端写入路径。

## 范围与前置核对

- 已核对 `PHASE_0D3A2.md`、`PHASE_0D3A2_DELIVERY_REPORT.md`、原型 README/HTML/CSS/JS、响应式与无障碍规范、0D3B implementation brief。
- 原型仍位于 `docs/design/prototypes/simulator-panel-review/`，11 个 fixture 位于 `docs/design/fixtures/model_persona_panel_review/`，未接入生产导航或真实 API。
- `rg -n "storyos-http" .` 返回 exit 1、无匹配。结论：`storyos-http` 来自外部浏览器启动器/工具环境，不是仓库命令或项目代码；未注册、删除或替换该协议。
- `frontend-design` skill 仅用于本阶段视觉验收，没有重新设计。

## 本地静态服务与访问证据

最终 QA 使用仓库根目录静态服务，以保证原型中 `../../fixtures/...` 相对 URL 能正确落到设计 fixture 目录：

```text
cwd: D:\novel\StoryOS
command: py -m http.server 4174 --bind 127.0.0.1
listener: 127.0.0.1:4174
PID: 33308
```

4173 已被已有本地进程占用（PIDs 48704、25904），且以原型目录作为根目录时 fixture 相对路径无法完成闭环，因此没有把 4173 的错误根因误判为项目缺陷。最终服务证据：

- `GET /docs/design/prototypes/simulator-panel-review/` → HTTP 200，返回 `Story OS · Simulator Review Preview` HTML。
- `GET /docs/design/fixtures/model_persona_panel_review/ready-current.json` → HTTP 200。
- 未使用 `file:///`、`storyos-http`、外部 CDN 或外部网络资源。

## 浏览器 QA

浏览器实际打开：`http://127.0.0.1:4174/docs/design/prototypes/simulator-panel-review/`。四个目标视口均完成真实渲染检查，`scrollWidth < innerWidth`，未发现核心横向溢出。

| 视口 | Fixture | 结果 |
|---|---|---|
| 1440×900 | `ready-current` | `READY / 当前`；Persona 顺序 01/02/03；authoritative 与 model supplement 分区清晰；usage supplement 可见 |
| 1280×800 | `partial` | `PARTIAL / 部分完成`；2 个 persona；`PARTIAL_PANEL_RESULT` 与 `MISSING_PERSONA_RESULT` 可见 |
| 768×1024 | `stale-mixed` | `STALE / 陈旧`；`STALE_MODEL_RESULT` 与 `SOURCE_VERSION_MISMATCH` 可见 |
| 390×844 | `source-missing` | `SOURCE MISSING / 来源缺失`；warning/status 在窄屏可见；authority 分数显示“未提供” |

代表性状态快速切换也已完成：

- `not-run` → `NOT RUN / 尚未运行`
- `failed` → `FAILED / 失败`，`PROVIDER_FAILURE`
- `explicit-run-404` → `FAILED / 失败`，`PANEL_RUN_NOT_FOUND`；未静默 fallback，章节上下文保留
- `usage-null` → `READY / 当前`，usage 显示“未提供”，不显示 0；`USAGE_INCOMPLETE`
- `agreements-conflicts` → Agreement 使用 `≈`，Conflict 使用 `≠` 且明确 `unresolved`
- `warnings-multiple` → `PARTIAL / 部分完成`，多条 warning 同时可见

## 可访问性与控制台

- Console error/warning：四个目标视口逐一检查，均为 0；未发现未处理 Promise rejection、fixture 404、外部资源失败或真实 `/api/` 请求。
- 状态选择器存在中文可读 `aria-label`，Tab 操作后焦点仍可识别；模式按钮“传统写作 / 模拟器”可见。
- DOM 存在 `prefers-reduced-motion` media query；状态使用文本/语义，不依赖颜色单独传达。
- 原型 JS 无绝对路径、无 endpoint/secret/prompt/chapter text 泄漏；生产引用扫描通过。

## 截图

四张截图均由实际浏览器渲染保存，文件名与目标视口对应。浏览器内容区域因滚动条略小于 CSS viewport，这是预期渲染结果：

- `ready-1440x900.png`（PNG 1425×891）
- `partial-1280x800.png`（PNG 1265×791）
- `stale-768x1024.png`（PNG 753×1004）
- `source-missing-390x844.png`（PNG 375×811）

## 回归与保护校验

- Phase 0D2B3 + Web/route/static regression：**52 passed**。
- `python -m compileall -q .`（在 `story-os-demo` 项目根执行）：exit 0。
- `node --check docs/design/prototypes/simulator-panel-review/prototype.js`：exit 0。
- 11 个 fixture JSON：全部解析；敏感 canary clean。
- 外部网络资源扫描、生产模板/static 引用隔离扫描：clean。
- `protected_ok=True`；Chroma 6、authority assets 16、Obsidian bindings 30；真实 model/panel run JSON 目录均为 0。

## 原型修复清单

无原型代码修复。浏览器访问问题的根因是静态服务器根目录与 fixture 相对 URL 不匹配，以及 4173 端口已有占用；通过选择仓库根目录的 4174 静态服务完成验证，未改 `index.html`、`prototype.css` 或 `prototype.js`。

## 产品确认与后续门禁

- **Mode-switch placement: APPROVED**
- **URL/context behavior: APPROVED**
- 原型仍未接入生产；未调用 provider/model、run create/rerun/repair、Chroma/Obsidian/story write，也未执行 POST/PUT/PATCH/DELETE。
- 本阶段不提交、不 push、不 reset、不 clean、不 rebase。
- 允许进入 Phase 0D3B 前，仍须遵守 0D3A2 的 stop rule，并复用现有 Jinja2 + vanilla JS/CSS 项目上下文。
