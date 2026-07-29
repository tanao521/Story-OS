你正在 TRAE IDE 中执行：

# Phase 0D6-A

## Shared Chapter Lifecycle Authority & Read-Purity Hardening

---

# 1. 当前状态

```text
Phase 0D4: SEALED
Phase 0D5: SEALED

Phase 0D6-P: PARTIALLY PASSED
Phase 0D6-P architecture audit: COMPLETE
Owner decisions: RESOLVED

Phase 0D6-A: AUTHORIZED
Phase 0D6-B: NOT ENTERED
Phase 0D6-C: NOT ENTERED
Phase 0D6-D: NOT ENTERED
Phase 0D6-RC: NOT ENTERED

Phase 0E: NOT ENTERED
Provider Live: NOT ENTERED
```

0D6-P 已识别五个阻断项：

```text
B1 get_selected_version() hidden mutation
B2 active_canon() hidden mutation
B3 SimulatorLoopStateService.build() KeyError
B4 no shared Chapter creation authority
B5 committed_with_warnings semantics undefined
```

本阶段只完成：

1. 消除 Chapter/Version/Canon 读取路径中的隐藏突变；
2. 修复 SimulatorLoopStateService 的确定性 KeyError；
3. 建立 Traditional 与 Simulator 共享的 Chapter Lifecycle Authority；
4. 实现下一章纯读解析与显式创建；
5. 实现幂等、并发、冲突与 response-loss recovery；
6. 固化 Chapter Completion warning 的服务端语义。

不得实现生产 UI，不得进入 0D6-B。

---

# 2. 执行配置

```text
IDE: TRAE
Mode: SOLO Coder
Agents: 1
Sub-agents: disabled
Reasoning: medium-high
```

高效率原则：

```text
先读设计与现有实现
先修纯读与 KeyError
再建立 lifecycle authority
最后运行有限回归
不做无关重构
不运行完整仓库测试
```

---

# 3. 必须读取

## 3.1 0D6-P 交付

```text
docs/planning/PHASE_0D6_P.md
docs/planning/PHASE_0D6_P_DELIVERY_REPORT.md
docs/planning/PHASE_0D6_IMPLEMENTATION_BRIEF.md

docs/design/chapter_progression_authority_map.md
docs/design/chapter_to_chapter_state_machine.md
docs/design/cross_chapter_continuity_contract.md
docs/design/next_chapter_risk_matrix.md
docs/design/gap_matrix.md

tests/_phase0d6p_fixture_probes.py
```

上述文档是本阶段设计权威。

不得跳过 Authority Map 后凭经验重新定义 Chapter identity。

## 3.2 生产实现

至少读取真实存在的：

```text
system/version_manager.py
system/revision_service.py
system/simulator_loop_state.py

Chapter / Planning services
ProjectContext
ChapterCommitService
NarrativeChapterCommitService
Branch lifecycle/store
Traditional chapter routes
Simulator state and chapter routes
```

搜索：

```text
get_selected_version
active_canon
chapter_id
chapter_number
create_chapter
initialize_chapter
next_chapter
chapter_manifest
planning cursor
manual_v001
```

## 3.3 回归基线

读取：

```text
tests/test_phase0d5b_*.py
tests/test_phase0d5c_*.py
tests/test_phase0d5d1_*.py
tests/test_phase0d5d2_*.py

tests/test_chapter_commit_service.py
tests/test_revision_service.py
VersionManager tests
Planning tests
Traditional Mode tests
real-data protection
static-path guard
```

---

# 4. 开始前保护

执行：

```powershell
Set-Location D:\novel\StoryOS\story-os-demo
git status --short
```

记录：

```text
existing modified files
existing untracked files
0D6-P documentation files
unrelated user files
```

禁止：

```text
git reset --hard
git clean
大范围格式化
覆盖现有 dirty files
Git commit
Git push
```

建立真实数据保护基线：

```text
real project hashes
real data/chroma hashes
real Chapter count
real Version manifest count
real Canon asset count
real Candidate/Review/Commit count
```

所有 mutation 测试必须使用临时 ProjectRoot。

---

# 5. 内部 Gate A0：修复隐藏写入与 KeyError

在 Chapter Lifecycle Authority 实现前，必须先通过 A0。

## 5.1 `get_selected_version()` 改为纯读

当前问题：

```text
system/version_manager.py:192-209
读取 selected version 时自动创建 chapter_{N}_versions.json
```

目标：

```text
get_selected_version()
→ 只读取
→ 文件不存在时返回稳定的未初始化结果或明确 domain error
→ 文件系统不发生变化
```

禁止：

```text
读取时创建 manifest
读取时创建 manual_v001
读取时写 selected version
读取时修复损坏文件
```

根据现有接口兼容性，选择一种稳定契约：

```text
None
VERSION_STATE_NOT_INITIALIZED
显式的 Optional result
```

不得抛出原始 `FileNotFoundError` 或内部路径。

### 显式初始化

将原来的初始化副作用迁移到明确 mutation，例如现有或新增的内部方法：

```text
initialize_chapter_versions(...)
```

名称以仓库风格为准。

显式初始化必须：

```text
由 Chapter Lifecycle Service 调用
只在创建新 Chapter 时调用
不可由 GET/read 路径调用
支持幂等重放
不修改其他 Chapter
```

---

## 5.2 `active_canon()` 改为纯读

当前问题：

```text
system/revision_service.py:122-139
读取 active Canon 时创建三个 Canon 文件
```

目标：

```text
active_canon()
→ 只读取现有 Canon authority
→ 不存在时返回稳定的未初始化状态
→ 不产生任何文件
```

禁止：

```text
读取时创建 Canon content
读取时创建 active pointer
读取时创建 revision metadata
读取时隐式激活 revision
```

建立或复用显式初始化：

```text
initialize_chapter_canon(...)
```

具体名称按现有架构。

显式初始化只能由 Chapter Lifecycle mutation 调用。

不得改变：

```text
RevisionService revision semantics
ChapterCommitService
existing Canon activation contract
```

---

## 5.3 修复 `SimulatorLoopStateService.build()` KeyError

当前问题位置：

```text
system/simulator_loop_state.py:395
```

要求：

1. 使用真实 Branch manifest/schema 读取字段；
2. 缺失、损坏或旧 schema 必须 fail closed；
3. 返回稳定的 blocking reason；
4. 不得因只读状态聚合写入 Branch 数据；
5. 不得使用默认 active Branch 掩盖 scope 错误；
6. 不得回退到其他 Branch。

错误状态应表达为现有或稳定的新 read-model code，例如：

```text
BRANCH_MANIFEST_INVALID
BRANCH_SCOPE_UNAVAILABLE
BRANCH_STATE_UNREADABLE
```

不得暴露：

```text
traceback
absolute path
raw KeyError
artifact path
```

---

## 5.4 A0 测试

新增或扩展：

```text
tests/test_phase0d6a_read_purity.py
tests/test_phase0d6a_simulator_state.py
```

至少验证：

```text
get_selected_version missing manifest → no write
get_selected_version existing manifest → correct read
active_canon missing files → no write
active_canon existing authority → correct read
damaged Branch manifest → safe fail-closed state
legacy Branch manifest → deterministic handling
build() does not raise KeyError
read paths leave SHA-256 manifest unchanged
```

只有 A0 全部通过，才继续 lifecycle authority。

---

# 6. Shared Chapter Lifecycle Authority

## 6.1 核心原则

建立一个共享的后端 authority，例如：

```text
ChapterLifecycleService
```

最终名称按照仓库命名习惯。

它必须由 Traditional 与 Simulator 共用。

禁止：

```text
SimulatorChapterService
TraditionalChapterService
两套 create chapter endpoint
前端创建目录
前端生成权威 Chapter ID
Planning helper 隐式创建 Chapter
GET 请求创建 Chapter
```

## 6.2 职责边界

该服务只负责：

```text
解析现有下一章
创建明确的下一章
初始化 Authority Map 规定的最小 Chapter 资产
返回 durable result
恢复同一 operation
```

不得负责：

```text
生成正文
创建 Turn
确认 Turn
编译 Candidate
批准 Candidate
Commit Chapter
修改上一章 Candidate/Review/Commit
自动推进 Branch
调用 Provider
执行 Vector embedding
```

---

# 7. Chapter Identity

必须严格复用 0D6-P Authority Map 中识别出的 Chapter identity。

禁止：

```text
前端传入未经验证的 chapter_number + 1
仅通过目录名决定 Chapter identity
创建随机 ID 绕开现有 registry
同时维护第二套 chapter registry
```

Create 请求应表达“从已完成 Chapter N 创建其合法 successor”，而不是任意写目录。

至少绑定：

```text
project_id
timeline_id
current_chapter_id
expected_current_chapter_fingerprint 或等价 CAS
expected_completion/commit identity
expected active Branch identity
expected Branch registry revision
expected Planning revision（若 Planning 是创建约束）
request fingerprint
operation_id
```

字段以现有 authority 实际能提供的值为准。

不得伪造不存在的 revision 字段；如果现有 authority 缺少必要 CAS，应在本阶段补足 lifecycle authority 自己的 request fingerprint 和创建前二次校验。

---

# 8. Pure Next-Chapter Resolver

实现共享纯读能力：

```text
resolve_next_chapter(...)
```

命名按仓库风格调整。

必须只返回：

```text
NEXT_CHAPTER_AVAILABLE
NEXT_CHAPTER_MISSING
NEXT_CHAPTER_BLOCKED
NEXT_CHAPTER_RECOVERY_REQUIRED
```

或状态机中的等价状态。

返回至少包含：

```text
current chapter
resolved next chapter identity（存在时）
existence
source/version readiness
Canon readiness
Branch carry-forward identity
creation availability
blocking reason
warning classification
```

要求：

```text
纯读取
Cache-Control: no-store（若提供 HTTP read route）
无目录创建
无 Version 创建
无 Canon 创建
无 Planning 写入
无 selected version 修改
无 active Branch 修改
```

---

# 9. Explicit Create-Next-Chapter Mutation

## 9.1 Mutation 入口

建立一个共享 mutation service。

只有确实需要 HTTP 接线时，提供一个共享 endpoint。

不得创建 Simulator-only endpoint。

路由名称应遵循现有 Chapter route 风格；如果仓库没有适合的 namespace，可采用类似：

```text
POST /api/chapters/next
```

但不要机械使用该路径；先检查现有路由结构。

## 9.2 请求

请求至少包含：

```text
operation_id
project_id
timeline_id
current_chapter_id
expected completion/commit identity
expected active Branch
expected Branch registry revision
expected Planning/version/Canon state（按 Authority Map）
```

不得信任前端直接提供的最终新 Chapter identity。

服务端必须根据现有 Chapter authority解析合法 successor。

## 9.3 Operation Authority

使用仓库现有 operation authority 约定：

```text
immutable operation request authority
mutable optional phase
durable result
request fingerprint
outcome fingerprint
schema version
```

建议目录应遵循已有项目数据结构，例如：

```text
data/chapter_lifecycle/operations/{operation_id}.json
data/chapter_lifecycle/operations/{operation_id}.phase.json
data/chapter_lifecycle/operations/{operation_id}.result.json
```

具体路径根据仓库现有 authority 习惯决定。

不得把 phase 当作完成事实。

## 9.4 幂等与冲突

必须满足：

```text
same operation + same request
→ return/recover same durable result

same operation + different request
→ OPERATION_CONFLICT

different operations creating same successor
→ first durable creator wins

existing legitimate next chapter
→ return existing identity or explicit ALREADY_EXISTS result
→ no duplicate Chapter
```

## 9.5 二次 freshness fence

在实际发布 Chapter 资产前重新读取：

```text
current Chapter still complete
commit result still authoritative
active Branch still valid
Branch registry revision unchanged
Planning constraint unchanged
successor still absent
```

如果发生变化：

```text
fail closed
no partial Chapter
no selected version mutation
no Canon activation
```

---

# 10. 最小 Chapter 初始化

只初始化 0D6-P Authority Map 明确要求的资产。

候选包括：

```text
Chapter registry/manifest entry
Chapter directory
initial Version manifest
manual_v001 或等价初始 Version
selected Version pointer
initial Canon assets
Branch carry-forward reference
Planning chapter entry
```

不能默认全部创建。

对每类资产，必须在实现前标注：

```text
REQUIRED_FOR_VALID_CHAPTER
OPTIONAL
DEFER_TO_LATER_PHASE
MUST_NOT_CREATE
```

## 10.1 原子性

Chapter 不能处于部分初始化后被当作 ready。

采用现有适合的策略：

```text
temporary staging + atomic publish
或
first-writer-wins immutable asset publication + final durable lifecycle result
```

要求：

```text
最终 Chapter identity 只发布一次
未完成初始化不出现在正常 next-chapter resolver 中
失败的 staging 可恢复或安全忽略
```

不得依赖进程内锁作为唯一并发保护。

## 10.2 上一章保护

创建 Chapter N+1 必须保持不变：

```text
Chapter N Candidate bytes
Chapter N Review decision
Chapter N Commit result
Chapter N History
Chapter N selected Version
Chapter N Canon revision
Chapter N Branch State
```

除非 Authority Map 明确规定 Planning cursor 需要显式推进。

---

# 11. Canon 与 Version 初始化

## 11.1 Version

显式初始化必须：

```text
通过 VersionManager 的 mutation API
不通过 get_selected_version()
仅初始化新 Chapter
不修改上一章 manifest
稳定生成初始 version_label
幂等重放返回同一 version identity
```

如果 `manual_v001` 是现有合法初始状态，可复用。

如果不是，必须按 Authority Map 的真实规则初始化。

## 11.2 Canon

显式初始化必须：

```text
通过 RevisionService 明确 mutation
不通过 active_canon()
只创建新 Chapter 所需 Canon authority
不激活或改写上一章 Canon
幂等重放返回同一 revision identity
```

Chapter N+1 初始 Canon 的内容与来源必须遵守 0D6-P 的 Canon carry-forward 决策。

本阶段不得自行引入新的 Canon aggregate。

---

# 12. Branch Carry-Forward

复用 0D6-P 已确定的 Branch 跨章语义。

必须保证：

```text
创建下一章不自动切换 active Branch
Browse Branch 不决定 successor Branch
请求绑定创建开始时的 active Branch
Branch archive/switch race fail closed
Branch A 的 carry-forward 不读取 Branch B 状态
```

如果现有 Branch 是 Timeline-global：

```text
下一章引用同一合法 branch_id
不创建新 Branch
```

如果 Authority Map 得出的结论不同，以文档为准。

不得新增第二个 Branch registry。

---

# 13. Completion Warning 语义

本阶段固化以下服务端语义。

## 13.1 Commit 已完成

```text
COMMITTED
COMMITTED_WITH_WARNINGS
```

两者都表示：

```text
Chapter Commit authority completed
可纯读 resolve next chapter
可以显式创建下一章
```

前提是没有：

```text
COMMIT_RECOVERY_REQUIRED
invalid/corrupt commit result
scope mismatch
```

## 13.2 Readiness 独立表达

创建下一章成功不等于可以开始 Turn。

生命周期结果中应独立返回：

```text
chapter_created
chapter_navigation_ready
turn_start_ready
memory_readiness
vector_readiness
blocking_reason
warnings
```

本阶段不要实现 Turn-start readiness 的全部聚合逻辑；该工作留给 0D6-B。

但必须确保：

```text
committed_with_warnings 不被错误视为 Commit 失败
recovery required 不允许创建下一章
corrupt commit result fail closed
```

---

# 14. Recovery Hooks

至少测试以下故障点：

```text
after operation authority claim
after successor identity resolution
after staging creation
after Version initialization
after Canon initialization
after Chapter publication
after durable result publication
before completed phase marker
```

每个 fault：

1. 第一次执行注入一次性故障；
2. 创建新的 service instance；
3. 使用相同 operation ID 重放；
4. authority bytes 不变；
5. 只存在一个 successor Chapter；
6. Version/Canon 不重复；
7. durable result 一致；
8. missing/stale phase 可修复；
9. 不修改上一章。

Fault 只允许出现在测试 hook 或 fixture。

不得加入生产环境变量 bypass。

---

# 15. 并发矩阵

至少覆盖：

## 15.1 create vs create

```text
两个 operation 同时创建相同 successor
→ first durable publication wins
→ one Chapter
→ one initial Version set
→ one initial Canon set
```

## 15.2 create vs existing Chapter appears

```text
freshness check 后
另一合法 mutation 创建 successor
→ 当前 operation 返回 existing/conflict
→ 不覆盖
```

## 15.3 create vs Branch archive

```text
第一次检查后 active Branch 被 archive
→ 二次 fence 失败
→ no Chapter publication
```

## 15.4 create vs Branch switch

```text
请求绑定 Branch A
active pointer 变为 Branch B
→ 按 Authority Map 决定 fail closed
→ 不静默改为 Branch B
```

## 15.5 create vs Planning change

如果 Planning 是约束：

```text
revision/fingerprint changed
→ fail closed
```

## 15.6 create vs Canon/Commit change

```text
current Chapter completion authority changed/corrupt
→ fail closed
```

---

# 16. API 与安全错误

如果提供 HTTP：

## Read

```text
GET next-chapter resolution
Cache-Control: no-store
```

## Mutation

```text
POST shared create-next-chapter
```

错误至少包括仓库风格的等价 code：

```text
CURRENT_CHAPTER_NOT_COMPLETE
COMMIT_RECOVERY_REQUIRED
COMMIT_RESULT_INVALID
NEXT_CHAPTER_ALREADY_EXISTS
CHAPTER_CREATION_CONFLICT
OPERATION_CONFLICT
BRANCH_STALE
BRANCH_ARCHIVED
PLANNING_STALE
VERSION_INITIALIZATION_FAILED
CANON_INITIALIZATION_FAILED
CHAPTER_LIFECYCLE_RECOVERY_REQUIRED
```

不得暴露：

```text
traceback
absolute path
temporary staging path
operation artifact path
Canon internal file path
Chroma internals
```

---

# 17. Traditional 与 Simulator 共享

本阶段不改生产 UI，但必须证明：

```text
Traditional 后续可调用同一 resolver/service
Simulator 后续可调用同一 resolver/service
不存在 mode-specific Chapter authority
```

Chapter 创建不得：

```text
隐式改变 Traditional selected Chapter
隐式改变 Traditional selected Version
删除传统草稿
覆盖传统 quality review
```

如果现有 Traditional 创建流程使用不同、不安全入口：

```text
记录为后续迁移项
不要在本阶段删除旧入口
提供共享 service adapter
```

后续迁移归入 0D6-B 或单独 RC，按 Implementation Brief 决定。

---

# 18. Filesystem Diff

每个 lifecycle 测试建立 SHA-256 manifest。

## 允许变化

只允许临时 ProjectRoot 中合法的：

```text
chapter lifecycle operation authority
phase/result
new Chapter identity/manifest
new Chapter initial Version assets
new Chapter initial Canon assets
必要的 Planning progression
必要的 Branch carry-forward reference
```

## 必须不变

```text
previous Chapter Candidate
previous Chapter Review
previous Chapter Commit
previous Chapter History
previous Chapter Version assets
previous Chapter Canon
other Branch
other Timeline
Traditional selected Version
real project
real data/chroma
```

---

# 19. 自动化测试

新增或按仓库结构合并：

```text
tests/test_phase0d6a_read_purity.py
tests/test_phase0d6a_chapter_lifecycle.py
tests/test_phase0d6a_idempotency.py
tests/test_phase0d6a_concurrency.py
tests/test_phase0d6a_recovery.py
tests/test_phase0d6a_freshness.py
tests/test_phase0d6a_routes.py
tests/test_phase0d6a_filesystem_diff.py
tests/test_phase0d6a_traditional_isolation.py
tests/test_phase0d6a_simulator_state.py
```

必须覆盖：

```text
selected-version read does not write
active-canon read does not write
Branch manifest KeyError fixed

existing next Chapter resolves read-only
missing next Chapter resolves read-only
explicit creation creates one Chapter
same operation replay
same operation different request conflict
different operations create/create race
existing Chapter race
Branch archive race
Branch switch race
Planning/Canon freshness
response loss recovery
result exists phase missing recovery
Version initialized once
Canon initialized once
previous Chapter immutable
cross-Branch isolation
cross-Chapter isolation
Traditional selected Version unchanged
safe errors
no-store read responses
```

---

# 20. 有限回归

运行：

```text
Phase 0D6-A focused tests

Phase 0D5 B/C/D1/D2 tests
ChapterCommitService
RevisionService
VersionManager
Planning
Traditional chapter/version/review
Branch lifecycle/scope
Turn scope
real-data protection
static-path guard
```

不要运行完整仓库测试，除非 focused regression 暴露广泛破坏。

PowerShell 下先使用 `Get-ChildItem` 展开测试文件。

每条命令记录：

```text
full command
collected
passed
failed
skipped
warnings
exit code
```

分类重叠时注明：

```text
category labels overlap and are not additive
```

---

# 21. 允许修改范围

允许：

```text
system/version_manager.py
system/revision_service.py
system/simulator_loop_state.py

现有或新增共享 Chapter lifecycle service
极薄的共享 Chapter route/DTO
Planning adapter（仅必要时）
对应测试
0D6-A 文档
```

谨慎允许：

```text
ProjectContext / Chapter registry helper
```

只有不存在安全复用路径时才修改。

禁止：

```text
Narrative Turn authority
Narrative Chapter Compiler 核心语义
Candidate Review authority
Commit approval gate
ChapterCommitService
Revision commit semantics
Chroma lifecycle
Provider
生产 Simulator UI
生产 Traditional UI
```

---

# 22. 文档

新增：

```text
docs/planning/PHASE_0D6_A.md
docs/planning/PHASE_0D6_A_DELIVERY_REPORT.md
```

更新：

```text
docs/planning/PHASE_0D6_IMPLEMENTATION_BRIEF.md
docs/design/chapter_progression_authority_map.md
docs/design/chapter_to_chapter_state_machine.md
docs/design/cross_chapter_continuity_contract.md
docs/design/next_chapter_risk_matrix.md
docs/design/gap_matrix.md
```

只有实现事实改变时更新设计文档。

不得修改 0D5 封存结论。

---

# 23. 交付报告结构

必须包含：

```text
1. Executive Summary
2. Gate Status
3. Owner Decisions Applied
4. Dirty Worktree Baseline
5. Read-Purity Hardening
6. SimulatorLoopState KeyError Fix
7. Chapter Lifecycle Authority
8. Chapter Identity Resolution
9. Explicit Initialization
10. Version Initialization
11. Canon Initialization
12. Branch Carry-Forward
13. Completion Warning Semantics
14. Operation Authority
15. Idempotency
16. Concurrency
17. Recovery
18. Freshness
19. Route and Error Boundary
20. Traditional/Simulator Sharing
21. Filesystem Diff
22. Validation Ledger
23. Files Changed
24. Safety Boundary
25. Remaining Gaps
26. Final Verdict
```

每个生产修复记录：

```text
original symptom
root cause
changed file/function
authority impact
regression test
```

---

# 24. 通过标准

全部满足才允许：

```text
Phase 0D6-A: PASSED
Phase 0D6-A: SEALED

Read paths are pure: VERIFIED
SimulatorLoopState KeyError: CLOSED
Shared Chapter Lifecycle Authority: VERIFIED
Existing next-Chapter resolution: VERIFIED
Explicit create-next-Chapter: VERIFIED
First-writer-wins: VERIFIED
Idempotent replay: VERIFIED
Operation conflict: VERIFIED
Response-loss recovery: VERIFIED
Version initialization exactly once: VERIFIED
Canon initialization exactly once: VERIFIED
Branch freshness: VERIFIED
Previous Chapter immutability: VERIFIED
Traditional/Simulator shared authority: VERIFIED
Filesystem boundaries: VERIFIED

Phase 0D6-B: AUTHORIZED, NOT ENTERED
```

如果任一以下问题存在：

```text
read path still writes
partial Chapter visible
duplicate Chapter possible
Version/Canon duplicated
Chapter identity generated by frontend
Branch race not fail-closed
previous Chapter mutated
Traditional and Simulator use different authority
recovery cannot reconstruct one result
```

则：

```text
Phase 0D6-A: PARTIALLY PASSED
Phase 0D6-A: NOT SEALED
Phase 0D6-B: NOT AUTHORIZED
```

---

# 25. 安全边界

最终必须报告：

```text
Provider calls: 0
External network: 0
Real project writes: 0
Real data/chroma writes: 0
Frontend authority: 0
New Commit path: 0
ChapterCommitService changes: 0
Candidate/Review authority changes: 0
Production UI changes: 0
New dependencies: 0
Git write operations: 0
```

---

# 26. 停止条件

完成 0D6-A 实现、测试和文档后立即停止。

不得：

```text
进入 0D6-B
实现 Chapter progression UI
修改 Completion 页面
开始跨章 Turn
实现 Memory/Vector readiness UI
进入 0D6-C/D/RC
进入 0E
启用 Provider Live
执行 Git commit/push
```

最终只输出：

```text
Phase 0D6-A: PASSED
Phase 0D6-A: SEALED
Phase 0D6-B: AUTHORIZED, NOT ENTERED
```

或：

```text
Phase 0D6-A: PARTIALLY PASSED
Phase 0D6-A: NOT SEALED
Phase 0D6-B: NOT AUTHORIZED
```
