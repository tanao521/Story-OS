# Chapter-to-Chapter State Machine

> 基于 `story-os-demo` 代码库审计整理的章节流转状态机规范。
> 证据来源：`system/simulator_loop_state.py`、`system/chapter_commit_service.py`、前端 `simulator-candidate-review.js` 等。

---

## 1. 背景与动机

StoryOS 的"章节到章节"推进并非由独立的后端工作流驱动，而是嵌入在 **Simulator Loop（模拟器循环）** 的阶段判定逻辑中。章节完成（chapter completion）的唯一权威信号是 **文件系统上 `chapter_{NNN}.md` 的存在性检查**；下一章的解析不走规划器/注册表，也不经过后端 API 路由，而是由前端通过 `history.pushState` 直接切换 URL。

本状态机文档用于把分散在 Python 后端与 JS 前端中的隐式协作关系显式化，降低回归与排障成本。

---

## 2. 关键实现证据

### 2.1 章节完成检测（`system/simulator_loop_state.py:460`）

```python
chapter_data = {
    "current_chapter": chapter_id,
    "completed": completed,
    "next_chapter_available": (
        self.context.chapters_dir / f"chapter_{chapter_id + 1:03d}.md"
    ).exists(),
    "next_chapter_id": chapter_id + 1
    if (self.context.chapters_dir / f"chapter_{chapter_id + 1:03d}.md").exists()
    else None,
}
```

- `next_chapter_available` 完全由文件存在性决定，无规划/注册表解析逻辑。
- `completed` 由提交状态派生（见 2.3）。

### 2.2 完成视图（前端 `simulator-candidate-review.js:44`）

```javascript
function renderCompletion() {
  const complete = state.model.chapter_progression;
  const done = !!complete.completed;
  setVisible("simulator-chapter-completion", done);
  const next = document.querySelector("[data-start-next-chapter]");
  if (next) { next.disabled = !complete.next_chapter_available; }
}
```

- 完成面板仅当 `completed === true` 时展示。
- "开始下一章"按钮在 `next_chapter_available === false` 时被禁用。

### 2.3 下一章导航（前端 `simulator-candidate-review.js:56`）

```javascript
function nextChapter() {
  if (!next.next_chapter_available) { return; }
  push({
    chapter_id: next.next_chapter_id,
    candidate_id: null,
    turn_id: null,
    action_id: null,
    view: "narrative-turn",
  });
}
```

- 导航是纯前端 `pushState`，没有后端 API 用于"章节解析"。
- 新章节的"进入视图"是 `narrative-turn`（并非回落到 `entry`）。

### 2.4 提交状态枚举（`system/chapter_commit_service.py:23-28`）

```python
class CommitStatus(str, Enum):
    COMMITTED = "committed"
    ALREADY_COMMITTED = "already_committed"
    COMMITTED_WITH_WARNINGS = "committed_with_warnings"
    FAILED = "failed"
```

`COMMITTED` 与 `ALREADY_COMMITTED` 都会使 `chapter.completed = True`；
`COMMITTED_WITH_WARNINGS` **同样视为完成**（只是带告警）；仅 `FAILED` 会保留在 `CHAPTER_ACTIVE`。

### 2.5 模拟器循环阶段（`system/simulator_loop_state.py:461-476`）

阶段判定优先级：

```
BLOCKED  >  COMPLETE  >  COMMIT  >  REVIEW  >  CANDIDATE  >  TURN  >  HISTORY  >  ENTRY
```

同时存在两个短路规则：

1. 若 `recovery.status != READY_FOR_NEXT_ACTION` 或 turn/candidate 存在 `stale` freshness → 强制 `BLOCKED`。
2. 若 `branch_readiness.active == False` 或 `lifecycle_status == "archived"` → 强制 `BLOCKED`。

---

## 3. 状态机总览

### 3.1 状态清单

| # | 状态 | 触发条件 |
|---|---|---|
| S1 | `CHAPTER_ACTIVE` | 当前章节 N 尚未提交，存在待处理 turn / candidate |
| S2 | `CHAPTER_COMMITTING` | `commit.status` 为 `pending`/`running`（写入中） |
| S3 | `CHAPTER_COMPLETE` | `commit.status ∈ {COMMITTED, ALREADY_COMMITTED}` |
| S4 | `CHAPTER_COMPLETE_WITH_WARNINGS` | `commit.status == COMMITTED_WITH_WARNINGS` |
| S5 | `NEXT_CHAPTER_RESOLVING` | 完成后检查下一章文件是否存在 |
| S6 | `NEXT_CHAPTER_AVAILABLE` | `chapter_{N+1:03d}.md` 存在 |
| S7 | `NEXT_CHAPTER_MISSING` | `chapter_{N+1:03d}.md` 不存在 |
| S8 | `NEXT_CHAPTER_CREATION_REQUIRED` | 规划器决定需创建下一章文件 |
| S9 | `NEXT_CHAPTER_BLOCKED` | `branch_readiness` 非 active 或 `vector_readiness != ready` |
| S10 | `NEXT_CHAPTER_READY` | 下一章文件存在且分支/向量就绪，可进入 `narrative-turn` |

### 3.2 文本状态转移图

```
                     commit.success
     CHAPTER_ACTIVE ──────────────────► CHAPTER_COMMITTING
       (TURN/CANDIDATE/REVIEW)              │    │    │
                                            │    │    └──► FAILED → CHAPTER_ACTIVE (rollback)
                                            │    └──────► COMMITTED_WITH_WARNINGS
                                            │                              │
                                            ▼                              ▼
                                   CHAPTER_COMPLETE         CHAPTER_COMPLETE_WITH_WARNINGS
                                            \                              /
                                             \       file check          /
                                              └──────────► NEXT_CHAPTER_RESOLVING
                                                                    │          │
                                                             exists │          │ missing
                                                                    ▼          ▼
                                                      NEXT_CHAPTER_AVAILABLE   NEXT_CHAPTER_MISSING
                                                                    │          │
                                         branch+vector ready        │          │ planner creates
                                                                    ▼          ▼
                                                        NEXT_CHAPTER_READY   NEXT_CHAPTER_CREATION_REQUIRED
                                                                    │
                                                                    ▼
                                                             CHAPTER_ACTIVE (N+1)

     * 任一阶段：branch inactive / archived / vector not ready / stale recovery
                 ─────────────────────────────────────────────────────────► NEXT_CHAPTER_BLOCKED / BLOCKED
```

---

## 4. 各状态详细规格

### S1 — `CHAPTER_ACTIVE`

- **权威证据**：`simulator_loop_state.py:469-474`（TURN/CANDIDATE/REVIEW 分支 + `completed=False`）
- **读操作**：读取 turn 历史、候选列表、分支清单、规划快照
- **允许变更**：写入 turn、创建/编辑 candidate、提交 commit（带 review approval）
- **主要动作**：用户/模拟器推进叙事回合 → 审阅候选 → 批准 → 提交
- **阻塞原因**：turn freshness=stale、candidate freshness=stale、`recovery.status != READY_FOR_NEXT_ACTION`
- **恢复动作**：重新运行 preflight 刷新 freshness，或调用 recovery 流程
- **URL / View**：`?view=narrative-turn&chapter_id=N`

### S2 — `CHAPTER_COMMITTING`

- **权威证据**：`simulator_loop_state.py:465-466`、`chapter_commit_service.py:55 CommitResult`
- **读操作**：读取 commit run 状态、版本服务状态
- **允许变更**：仅允许取消/回滚 commit（不可修改 candidate/turn）
- **主要动作**：系统执行 commit（revision → 写入 canonical 文件 → 更新 run_store）
- **阻塞原因**：向量索引锁冲突、文件写入锁冲突、revision 哈希冲突
- **恢复动作**：等待超时或调用 `CommitRunStore` 的 retry 分支
- **URL / View**：`?view=commit-progress&chapter_id=N`

### S3 — `CHAPTER_COMPLETE`

- **权威证据**：`simulator_loop_state.py:463-464`（`completed=True` → `stage=COMPLETE`）
- **读操作**：读取 chapter_data、commit summary、已归档 candidate
- **允许变更**：禁止修改当前章节文件；仅允许创建下一章
- **主要动作**：展示完成面板 → 调用 `next_chapter_available` 解析
- **阻塞原因**：无（只进不出，除非触发下一章解析）
- **恢复动作**：若文件物理丢失 → 通过 `revision_service` 从 `core_commit` 恢复
- **URL / View**：`?view=chapter-complete&chapter_id=N`

### S4 — `CHAPTER_COMPLETE_WITH_WARNINGS`

- **权威证据**：`chapter_commit_service.py:26 COMMITTED_WITH_WARNINGS`
- **读操作**：同 S3，外加 warnings 列表
- **允许变更**：同 S3；允许查看 warnings 详情
- **主要动作**：完成面板上显示告警横幅，用户可选择"仍然继续"或"回滚重试"
- **阻塞原因**：warnings 中若包含 `vector_inconsistent` → 软阻塞，需用户确认
- **恢复动作**：点击"回滚重试"→ 回退到 S1；或忽略告警继续推进
- **URL / View**：`?view=chapter-complete&chapter_id=N&warnings=1`

### S5 — `NEXT_CHAPTER_RESOLVING`

- **权威证据**：`simulator_loop_state.py:460` 文件存在性检查
- **读操作**：只读 `chapters_dir` 目录
- **允许变更**：禁止
- **主要动作**：同步 I/O 检查 `chapter_{N+1:03d}.md`
- **阻塞原因**：文件系统权限、磁盘 I/O 错误
- **恢复动作**：重试；失败则进入 `NEXT_CHAPTER_MISSING` 并提示
- **URL / View**：`?view=chapter-resolving&chapter_id=N`

### S6 — `NEXT_CHAPTER_AVAILABLE`

- **权威证据**：`simulator_loop_state.py:460`（`next_chapter_available=True`）
- **读操作**：读取下一章文件、分支清单、向量索引元数据
- **允许变更**：允许推进到下一章 ACTIVE
- **主要动作**：前端渲染"开始下一章"按钮为 enabled
- **阻塞原因**：仅当分支/向量未就绪（→ 跳转 S9）
- **恢复动作**：运行 branch vector readiness 检查
- **URL / View**：`?view=chapter-available&chapter_id=N`

### S7 — `NEXT_CHAPTER_MISSING`

- **权威证据**：`simulator_loop_state.py:460`（`next_chapter_available=False` 且非 S8 方案）
- **读操作**：只读规划状态、story blueprint
- **允许变更**：允许创建下一章文件、触发 planner
- **主要动作**：显示"下一章缺失"提示并引导进入规划/创建流程
- **阻塞原因**：planning service 不可用、blueprint 冲突
- **恢复动作**：调用 `next_chapter_planner` 生成 `chapter_{N+1:03d}.md`
- **URL / View**：`?view=chapter-missing&chapter_id=N`

### S8 — `NEXT_CHAPTER_CREATION_REQUIRED`

- **权威证据**：`core/next_chapter_planner.py`（由 `NEXT_CHAPTER_MISSING` 触发）
- **读操作**：读取 blueprint、依赖图、rolling projection
- **允许变更**：创建下一章 Markdown、写入章节 plan
- **主要动作**：Planner 生成下一章骨架并写入 `chapters_dir`
- **阻塞原因**：planning dependency 未满足、token budget 超限
- **恢复动作**：进入保守模式（`conservative_token_budget`）或切到 LOCAL_ONLY policy
- **URL / View**：`?view=chapter-create&chapter_id=N+1`

### S9 — `NEXT_CHAPTER_BLOCKED`

- **权威证据**：`simulator_loop_state.py:475-476`、`branch_readiness.vector_readiness`
- **读操作**：读取 branch_readiness、vector_client 健康状态
- **允许变更**：修复向量索引、激活分支
- **主要动作**：显示"章节推进受阻"诊断面板
- **阻塞原因**：`branch.active=False`、`branch.lifecycle_status=archived`、`vector_readiness != ready`
- **恢复动作**：激活分支 / 等待向量索引构建 / 从 archived 状态恢复
- **URL / View**：`?view=chapter-blocked&chapter_id=N`

### S10 — `NEXT_CHAPTER_READY`

- **权威证据**：`simulator_loop_state.py:460` + `branch_readiness.active=True` + `vector_readiness=ready`
- **读操作**：同 S6
- **允许变更**：允许进入 `CHAPTER_ACTIVE(N+1)`
- **主要动作**：前端 `pushState` 跳转到 `?chapter_id=N+1&view=narrative-turn`
- **阻塞原因**：无
- **恢复动作**：无（已就绪）
- **URL / View**：`?view=narrative-turn&chapter_id=N+1`

---

## 5. Fixture 验证观察

基于 `tests/` 下 fixture 级探针（`_phase0d6p_fixture_probes.py` 等）与审计：

1. **`SimulatorLoopStateService.build()` 在解析分支 manifest 时抛出 `KeyError: 'revision'`**  
   - 现象：fixture 中 branch manifest 缺失 `revision` 字段导致崩溃。
   - 影响：阻塞 `CHAPTER_ACTIVE → CHAPTER_COMMITTING` 路径，表现为永远停在 `BLOCKED`。
   - 修复建议：在 `build()` 中对 `revision` 做 `get(..., None)` 安全读取，并在缺失时短路为 `BLOCKED` + 诊断信息。

2. **`next_chapter_available` 的判定仅依赖文件系统**  
   - 当文件被外部移动/删除时，state 会在"完成"后误报"下一章缺失"，即便规划器中已存在下一章计划。
   - 建议：在 S5 增加"计划存在性"作为降级判定信号。

3. **前端 `nextChapter()` 没有提交任何后端事件**  
   - 意味着后端对"章节切换"无持久化日志；若用户刷新页面，状态仅能从文件/分支重建。
   - 建议：在 transition 时写入一条 `chapter_transition` 审计事件。

4. **`COMMITTED_WITH_WARNINGS` 与 `COMMITTED` 在状态判定上等值**  
   - 代码中 `completed=True` 直接跳过 warnings 检查。
   - 建议：在 S3/S4 之间引入软分叉，允许前端基于 warnings 做差异化 UX。

5. **URL 状态与后端状态存在短暂竞态**  
   - 前端 `pushState` 后立即请求 `/api/state`，但后端文件可能尚未 flush；偶发导致 `chapter_data.completed` 为旧值。
   - 建议：在 `commit` 返回前广播状态就绪信号（SSE/WebSocket），前端等待后再导航。

---

## 6. 关键风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|---|---|---|---|
| 章节推进被 `stale` freshness 永久阻塞（fixture 回归问题） | 中 | 高 | 引入自动 freshness 修复任务；BLOCKED 超过阈值触发强制 re-plan |
| 文件系统丢失导致 `next_chapter_available=False` 假阴性 | 中 | 中 | 增加 planner 存在性作为第二信号；提供"从 blueprint 恢复"按钮 |
| 分支 archived 后无法恢复到 active | 低 | 高 | 在 `narrative_branch_lifecycle_service` 增加 un-archive 操作并加审计 |
| 向量索引构建慢于章节完成 → S9 卡死 | 高 | 中 | 引入 `DEFERRED` 提交策略：允许章节先完成，向量异步补建 |
| 前端直接 `pushState` 绕过后端审计 | 中 | 中 | 增加后端 `/chapter-transition` 事件日志端点 |
| `revision` 缺失导致 `KeyError` | 高 | 高 | 在 `build()` 处补全默认值 + 失败降级路径 |

---

## 7. 路由与视图映射

| 状态 | 建议 URL | 前端视图 | 后端只读端点 |
|---|---|---|---|
| CHAPTER_ACTIVE | `?view=narrative-turn&chapter_id=N` | narrative-turn | `/api/state?chapter_id=N` |
| CHAPTER_COMMITTING | `?view=commit-progress&chapter_id=N` | commit-progress | `/api/commits/{id}` |
| CHAPTER_COMPLETE | `?view=chapter-complete&chapter_id=N` | chapter-completion | `/api/state?chapter_id=N` |
| CHAPTER_COMPLETE_WITH_WARNINGS | `?view=chapter-complete&chapter_id=N&warnings=1` | chapter-completion (warn) | `/api/commits/{id}` |
| NEXT_CHAPTER_RESOLVING | `?view=chapter-resolving&chapter_id=N` | resolving overlay | `/api/state?chapter_id=N` |
| NEXT_CHAPTER_AVAILABLE | `?view=chapter-available&chapter_id=N` | chapter-available | `/api/state?chapter_id=N` |
| NEXT_CHAPTER_MISSING | `?view=chapter-missing&chapter_id=N` | chapter-missing | `/api/plans/{chapter_id}` |
| NEXT_CHAPTER_CREATION_REQUIRED | `?view=chapter-create&chapter_id=N+1` | chapter-create | `/api/plans` |
| NEXT_CHAPTER_BLOCKED | `?view=chapter-blocked&chapter_id=N` | chapter-blocked | `/api/diagnostics?chapter_id=N` |
| NEXT_CHAPTER_READY | `?view=narrative-turn&chapter_id=N+1` | narrative-turn | `/api/state?chapter_id=N+1` |

---

## 8. 参考文件

- `system/simulator_loop_state.py` — 阶段判定主逻辑
- `system/chapter_commit_service.py` — `CommitStatus` 与 `CommitResult`
- `core/next_chapter_planner.py` — 下一章规划器
- `core/project_context.py` — `chapters_dir` 定义
- `system/vector_index_lifecycle.py` — 向量就绪判定
- `system/narrative_branch_lifecycle_service.py` — 分支 active/archived 生命周期
- `tests/_phase0d6p_fixture_probes.py` — fixture 探针
- `tests/test_phase0d5d2_completion.py` — 完成态测试
- `tests/test_phase0d5d2_navigation.py` — 导航测试
