# StoryOS 交接说明（Trae IDE）

更新时间：2026-07-28

这份文件是把当前仓库交给 Trae IDE 继续阅读和维护的入口。先看本文件，
再按需要阅读 `docs/planning/PHASE_0D5_IMPLEMENTATION_BRIEF.md` 和各阶段
delivery report。不要把旧的中间报告中的“未封存”当作当前状态；最终 RC 报告
已经关闭了这些中间状态。

## 当前最终状态

```text
Phase 0D4: SEALED
Phase 0D5-P: PASSED
Phase 0D5-A: PASSED
Phase 0D5-B: PASSED
Phase 0D5-C: SEALED
Phase 0D5-D1: SEALED
Phase 0D5-D2: SEALED
Phase 0D5-D: SEALED
Phase 0D5-RC: PASSED
Phase 0D5: SEALED
Phase 0D6 / E / Provider Live: NOT ENTERED
```

最终依据：

- `docs/planning/PHASE_0D5_RC.md`
- `docs/planning/PHASE_0D5_RC_DELIVERY_REPORT.md`
- `docs/planning/PHASE_0D5_D1_RC1_DELIVERY_REPORT.md`
- `docs/planning/PHASE_0D5_D2_DELIVERY_REPORT.md`

## 项目做什么

StoryOS 是一个本地、项目隔离的小说/叙事工作台。传统写作模式负责草稿、
编辑、版本、质量审查和 Canon。Simulator 是另一条 branch-aware 的叙事循环：

```text
明确 scope
  -> 规划 Turn
  -> 用户选择/确认 Turn
  -> Turn 结果与不可变 transition journal
  -> Candidate 编译
  -> Candidate durable review
  -> approved 才能进入 ChapterCommitService
  -> Canon/向量合法产物
  -> Chapter Completion
```

所有 mutation 都必须经过既有 authority 和 operation/recovery artifact；
前端只读聚合状态，不拥有事实状态。

## 关键权威和代码入口

| 能力 | 权威入口 |
|---|---|
| Turn plan/result/transition | `story-os-demo/system/narrative_turn_service.py`、`narrative_turn_store.py` |
| Branch 生命周期、active pointer、registry revision | `narrative_branch_lifecycle_service.py`、`narrative_branch_store.py` |
| Candidate 编译 | `narrative_chapter_compiler.py` 的 `NarrativeChapterCompiler` |
| Candidate review | `narrative_candidate_review_service.py` |
| Commit | `narrative_chapter_compiler.py` 的 `NarrativeChapterCommitService`，内部只能调用既有 `ChapterCommitService` |
| Canon revision | `revision_service.py` |
| Simulator read model | `simulator_loop_state.py` |
| HTTP routes | `web/narrative_turn_routes.py`、`narrative_branch_routes.py`、`narrative_chapter_routes.py`、`simulator_state_routes.py` |
| Simulator shell | `web/templates/index.html`、`web/static/simulator-usable-loop.js`、`simulator-candidate-review.js`、`simulator-usable-loop.css` |

## D1 审阅权威规则

Candidate 文件本身不可变，不能通过修改 Candidate payload 伪造批准。Review
记录位于项目数据目录的独立 authority 下：

```text
data/narrative_candidate_review/operations/{operation_id}.json
data/narrative_candidate_review/operations/{operation_id}.phase.json
data/narrative_candidate_review/operations/{operation_id}.result.json
data/narrative_candidate_review/decisions/{candidate_id}.json
```

Review 先做 scope、candidate fingerprint、source fingerprint、active Canon、
branch lifecycle 和 registry revision 的 fresh re-read；同一 Candidate 的
首个决定 first-writer-wins。`pending`、`rejected`、`stale` 不能提交。

Commit recovery 必须优先读取已完成的 durable commit result；不能因为 phase
缺失或过期就再次调用 `ChapterCommitService`。

HTTP：

```text
GET  /api/simulator/state
GET  /api/narrative-chapter/candidates/{candidate_id}
POST /api/narrative-chapter/compile
POST /api/narrative-chapter/candidates/{candidate_id}/review
POST /api/narrative-chapter/commit
```

读接口使用 `Cache-Control: no-store`，错误使用 safe envelope；不得返回内部
路径、operation 文件、Chroma 细节或 traceback。

## 开发环境与常用命令

工作目录是：

```text
D:\novel\StoryOS\story-os-demo
```

使用仓库已有 Python 环境，不要安装新依赖。常用检查：

```powershell
Set-Location D:\novel\StoryOS\story-os-demo
python -m py_compile system\narrative_candidate_review_service.py system\narrative_chapter_compiler.py system\simulator_loop_state.py web\narrative_chapter_routes.py
python -m pytest -q
```

Phase 0D5 重点回归：

```powershell
python -m pytest -q tests\test_phase0d5d1_*.py
python -m pytest -q tests\test_phase0d5d2_*.py
python -m pytest -q tests\test_phase0d5b_*.py tests\test_phase0d5c_*.py
python -m pytest -q tests\test_phase0d4f_*.py tests\test_chapter_commit_service.py tests\test_revision_service.py
python -m pytest -q tests\test_real_data_protection.py tests\test_static_path_guard.py tests\test_review_gate.py
```

PowerShell 不会可靠展开 pytest 的 `*` 参数；如果出现“no tests ran”，先
用 `Get-ChildItem` 解析成完整路径，再传给 `python -m pytest`。

## 已验证的最终证据

最终 RC 使用临时 project root 和 Chromium fixture，完成了：

- 两次确认 Turn，并显示第三个独立 Turn context；
- immutable History；
- Candidate 编译一次、Review 一次、Commit 一次；
- approved 后才出现 commit 能力；
- Reject、Compile/Review/Commit response-loss recovery；
- Refresh、Back/Forward 只读；
- Branch 创建/选择/归档/恢复及 scope isolation；
- Traditional Mode 隔离；
- 1024x768、768x1024、390x844 responsive/accessibility smoke；
- application console errors/warnings/unhandled rejection 均为 0；
- Provider、应用外网、frontend authority、额外 commit path、直接 Canon/Chroma
  review write、真实项目写入、Git write 均为 0。

最终统计见 `PHASE_0D5_RC_DELIVERY_REPORT.md`：核心 focused pytest 61 passed，
authority/version/quality/real-data/static-path regression 93 passed，最终
Browser verifier 4 passed。

## Trae 继续开发时的边界

当前阶段已经封存，默认不要继续扩展 roadmap。任何新工作必须先得到新的
明确阶段授权，并先写设计/边界说明。

禁止默认做以下事情：

- 进入 Phase 0D6、Phase E 或 Provider Live；
- 重写 Compiler、ChapterCommitService、RevisionService 或创建第二套入口；
- 在前端、URL、localStorage 或 client cache 中创建 authority；
- 直接写 Canon、Chroma、Branch registry 或传统写作版本；
- 为测试添加生产 bypass；
- 安装依赖、改 CI、提交 Git、推送远端；
- 把历史报告的暂时性 TODO 当成当前未关闭缺陷。

如果要修 bug，先建立临时 fixture 和最小回归测试，再修改最小生产代码，
最后重新运行相应 RC 回归。保留当前 dirty worktree 中用户已有修改，不做
`git reset --hard` 或大范围格式化。

## 推荐的 Trae 开始顺序

1. 阅读本文件和 `PHASE_0D5_RC_DELIVERY_REPORT.md`。
2. 运行 `git status --short`，记录现有 dirty files，不要覆盖它们。
3. 阅读 `system/simulator_loop_state.py`、`narrative_candidate_review_service.py`
   和 `narrative_chapter_compiler.py`。
4. 运行上述 focused tests，确认环境基线。
5. 只有用户给出新阶段授权后，才建立新的变更计划。

