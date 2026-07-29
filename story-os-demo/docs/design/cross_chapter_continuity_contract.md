# 跨章节连续性契约 (Cross-Chapter Continuity Contract)

> **状态:** 已验证 · 基于 StoryOS 审计数据
> **最后更新:** 2026-07-28
> **适用范围:** StoryOS 核心引擎中所有涉及章节 (Chapter) 切换的组件

---

## 1. 已验证制品作用域 (Verified Artifact Scopes)

下表基于审计过程中对各制品（Artifact）在 **项目 / 时间线 / 分支 / 章节** 四个维度以及 **来源 / 候选 / 操作 / 指纹** 等辅助维度的验证结果汇总。

| 制品 (Artifact) | 项目 | 时间线 | 分支 | 章节 | 来源 | 候选 | 操作 | 指纹 |
|-----------------|:----:|:------:|:----:|:----:|:----:|:----:|:----:|:----:|
| Turn plan (回合计划) | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Turn result (回合结果) | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ |
| Transition (过渡) | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| History (历史) | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| Candidate (候选) | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Review (审阅) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Commit (提交) | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ |

### 1.1 作用域解读

- **✅** 表示该维度已被持久化存储层或服务层显式支持与验证。
- **❌** 表示该维度当前 **没有** 独立的持久化验证，运行时行为完全依赖上层逻辑。
- **Source (来源)**: 仅 Candidate / Review / Commit 明确追踪上下文来源。Turn plan / result / transition / history 的来源归属为隐式约定。
- **Operation (操作)**: History 不记录操作维度，意味着历史变更无法追溯至具体操作类型（如 create / update / delete）。
- **Fingerprint (指纹)**: Transition 缺少内容指纹，跨版本 diff 检测存在盲区。
- **Commit 的时间线 / 分支为 ❌**: Commit 对象只绑定章节，不绑定时间线或分支——这在跨章节推进时可能导致提交归属歧义。

---

## 2. 核心不变量 (Key Invariants)

以下八条不变量是 StoryOS 跨章节连续性的 **硬约束**。任何实现若违反其中任一不变量，将直接导致章节间状态污染或数据丢失。

### INV-1: 章节 N 的 Commit 在持久化结果存在后即不可变

```
∀ commit ∈ Chapter_N:
  durable_result_exists(commit) → immutable(commit)
```

- **含义:** 一旦 `CommitRunStore` 为 Chapter N 的 Commit 写入了持久化结果，该 Commit 对象及其引用的所有关联数据（候选、审阅、版本快照）即被冻结，后续章节不得读取、修改或回写。
- **证据:** `CommitRunStore` 的写入路径具有事务性语义，成功写入后不再接受 update/delete 操作。
- **违反后果:** 已完成章节的历史被篡改 → 后续章节上下文基于被污染的历史构建 → 连续性崩溃。

### INV-2: 章节 N+1 不继承章节 N 的运行时制品

```
TurnOps(Chapter_N+1) ∩ TurnOps(Chapter_N) = ∅
Candidates(Chapter_N+1) ∩ Candidates(Chapter_N) = ∅
Reviews(Chapter_N+1) ∩ Reviews(Chapter_N) = ∅
CommitOps(Chapter_N+1) ∩ CommitOps(Chapter_N) = ∅
```

- **含义:** 章节切换后，Turn 操作序列、候选列表、审阅记录、Commit 操作记录 **全部重置**。新章节的运行时状态从零开始构建，与上一章节无任何运行时层面的引用关系。
- **证据:** Turn plan / Turn result / Transition / Candidate / Review / Commit 均以 chapter_id 为隔离键。
- **注意:** 章节 N 的 **只读历史内容**（Narrative State、Canon、Memory）会通过上下文装配服务传递给章节 N+1，这是唯一允许的"继承"形式。

### INV-3: 章节 N 的旧候选在章节 N+1 中 fail-closed

```
∀ candidate ∈ Candidates(Chapter_N), chapter_id = N:
  scope_check(candidate, Chapter_N+1) → reject(scope_mismatch)
```

- **含义:** 当章节 N 的候选条目（如未提交的草稿）在章节 N+1 的上下文中被引用时，系统必须以 **作用域不匹配** 为由拒绝，而不是静默通过。这防止了跨章节的"脏草稿"被误提交。
- **证据:** Candidate 制品作用域为 ✅（含章节维度），scope_check 逻辑在 CandidateService 中实现。
- **违反后果:** 章节 N 的半成品候选可能在章节 N+1 被激活 → 内容连续性断裂。

### INV-4: 分支 A 不读取分支 B 的状态

```
∀ branch_a ≠ branch_b:
  NarrativeBranchStore.read(branch_a, query_b) → deny_cross_branch_read
```

- **含义:** `NarrativeBranchStore` 作为分支注册表，其读取接口强制绑定当前分支 ID。分支间数据完全隔离，不存在"跨分支只读"的隐式通道。
- **证据:** `NarrativeBranchStore` 的查询方法签名要求 `branch_id` 参数，内部通过 branch_id 过滤所有查询结果。
- **违反后果:** 分支间数据泄露 → 多分支叙事出现非预期耦合。

### INV-5: 浏览模式不修改活动分支指针

```
BrowseMode.active_branch_pointer = CONSTANT
BrowseMode.read_only = TRUE
```

- **含义:** 用户进入浏览模式（如查看历史版本、预览其他分支）时，活动分支指针保持不变。浏览操作不会触发分支切换、版本切换或状态迁移。
- **证据:** BrowseMode 状态机中无 `branch_pointer_write` 事件。
- **违反后果:** 浏览操作意外改变活动上下文 → 用户在错误分支上继续创作。

### INV-6: Refresh / Back / Forward 不创建章节、不修改状态

```
Refresh / Back / Forward → { no_chapter_create, no_state_mutate }
```

- **含义:** 浏览器级别的刷新、前进、后退操作不应在 StoryOS 引擎层产生任何副作用。这些操作仅影响客户端视图状态，不应触发章节创建、版本写入或状态迁移。
- **证据:** 前端路由层的导航事件未连接到后端的 chapter_create / state_mutate 事件通道。
- **违反后果:** 刷新页面导致重复创建章节 → 章节编号错乱 → 连续性数据冗余。

### INV-7: 章节标识永远不由前端生成

```
chapter_id = BackendGenerated(UUIDv7 | ULID | snowflake)
Frontend ∉ chapter_id_authority
```

- **含义:** `chapter_id` 的生成权完全属于后端。前端仅接受后端分配的章节 ID，绝不自行生成或猜测。这保证了章节标识的唯一性、单调性和可追溯性。
- **证据:** 章节创建流程中，`ChapterService.create_chapter()` 返回的 `chapter_id` 由后端 ID 生成器产出，前端无对应的 id-generate 逻辑。
- **违反后果:** 前端生成的 ID 可能与后端冲突 → 章节数据覆盖 → 连续性不可逆丢失。

### INV-8: 传统选中版本在跨章节中不被隐式修改

```
VersionManager.selected_version(Chapter_N) → immutable_across_chapter_boundary
Chapter_N+1.selected_version = NULL | Chapter_N+1.own_selected_version
```

- **含义:** 章节 N 中用户选中的源版本（selected source version）在章节切换时 **不会被隐式修改**。章节 N+1 的版本选择基于自身的版本列表，与章节 N 的选中状态完全独立。
- **证据:** `VersionManager` 的 `selected_version` 属性按 chapter_id 分片存储，跨章节读取返回独立的版本指针。
- **违反后果:** 章节 N+1 意外继承章节 N 的选中版本 → 引用不存在于当前章节的版本 → 内容错乱。

---

## 3. 上下文源优先级 (Context Source Priority for Chapter N+1)

以下优先级列表基于对 `system/narrative_turn_context.py`、`system/context_assembly_service.py` 和 `system/context_builder.py` 的审计。当章节 N+1 启动时，上下文按此顺序装配，高优先级源可以覆盖低优先级源中的冲突条目。

| 优先级 | 上下文源 | 读取方式 | 核心服务 / 模块 | 可写性 |
|:------:|---------|---------|----------------|--------|
| **1** | Active Committed Canon | `RevisionService.read_active_canon()` | `system/revision_service.py` | 只读（由 Chapter N Commit 写入） |
| **2** | Branch Narrative State | `NarrativeBranchStore.read(branch_id)` | `system/narrative_branch_store.py` | 只读（由分支注册表管理） |
| **3** | Narrative Memory | `NarrativeMemoryService.query(characters, relationships, locations)` | `system/narrative_memory_service.py` | 只读（记忆模型注入） |
| **4** | Planning | `PlanningService.get_chapter_plan(chapter_id)` | `system/planning_service.py` | 只读（滚动窗口策略） |
| **5** | Selected Source Version | `VersionManager.get_selected_version(chapter_id)` | `system/version_manager.py` | 读写（当前章节内可控） |
| **6** | Vector Retrieval | `VectorIndexLifecycle.search(filtered_by_scope)` | `system/vector_index_lifecycle.py` | 只读（向量索引按作用域过滤） |
| **7** | Chapter N Content | `ChapterStore.read(N, read_only)` | `system/chapter_store.py` | 只读（跨章节引用） |

### 3.1 优先级说明

- **优先级 1–4:** 构成章节 N+1 的 **不可变上下文基础**，这些源的内容在章节 N Commit 完成后已被冻结。
- **优先级 5:** 章节 N+1 的 **第一个可变上下文**，用户在此章节内的版本选择仅影响当前章节。
- **优先级 6:** 语义检索层，结果受作用域过滤约束（见 INV-3），不会越界召回不相关的向量。
- **优先级 7:** 跨章节只读引用，章节 N 的内容仅作为背景参考传递给章节 N+1，不可被修改。

### 3.2 冲突解决规则

1. **高优先级覆盖低优先级:** 当同一实体在多个源中出现时，高优先级源的值生效。
2. **同优先级不合并:** 同一优先级内的多个源（如多个 Narrative Memory 条目）通过语义一致性检查决定取舍，不做简单拼接。
3. **空值传递:** 若某优先级源返回空，系统不降级到下一优先级，而是将该槽位标记为"未定义"，等待后续回合填充。

---

## 4. 通过夹具验证的连续性风险 (Fixture-Verified Continuity Risks)

以下风险均通过 StoryOS 的集成测试夹具（integration test fixtures）验证确认，每个风险描述了一个具体的、可复现的连续性缺陷路径。

### RISK-1: `get_selected_version()` 读时即写入 → 隐藏的版本变更风险

```
get_selected_version(chapter_N+1)
  → 检测到 chapter_00N+1_versions.json 不存在
  → 自动创建 chapter_00N+1_versions.json（包含默认版本列表）
  → 返回默认选中版本
```

- **触发条件:** 章节 N+1 首次读取 selected version 时，版本文件不存在。
- **风险描述:** `VersionManager.get_selected_version()` 在读取路径上隐式创建了 `chapter_00N_versions.json` 文件。这意味着 **纯读操作产生了写副作用**。如果章节 N+1 的初始版本选择逻辑设计不当，可能在此处意外写入不符合预期的默认版本，导致：
  - 章节 N+1 的初始版本列表被静默初始化，与预期的"空状态"不一致。
  - 后续代码路径基于"文件已存在"的假设做出决策，跳过了本应执行的初始化检查。
- **影响范围:** 版本管理、章节初始化、上下文装配。
- **建议修复:** 将"读时创建"改为显式的初始化步骤（`init_selected_version(chapter_id)`），在章节创建流程中一次性完成。

### RISK-2: `active_canon()` 对任意 `.md` 文件自动初始化 Canon

```
active_canon(chapter_id)
  → 查找 chapter_id 对应的 .md 文件
  → 若存在 → 自动初始化 Canon 对象（即使该文件不属于已提交章节）
  → 若不存在 → 返回空 Canon
```

- **触发条件:** 磁盘上存在对应章节的 `.md` 文件，但该章节尚未完成 Commit。
- **风险描述:** `RevisionService.active_canon()` 会为任何存在 `.md` 文件的章节初始化 Canon 对象，无论该章节是否已通过 Commit 流程正式建立。这可能导致：
  - 章节 N+1 在尚未正式创建的情况下，意外获得一个"幽灵 Canon"。
  - 后续上下文装配基于该 Canon 构建，包含了未经过 Commit 验证的草稿内容。
  - INV-1（Commit 不可变性）被绕过，因为该 Canon 不是通过 Commit 流程产生的。
- **影响范围:** Canon 生命周期管理、上下文装配、章节初始化边界。
- **建议修复:** `active_canon()` 应增加 `require_committed=True` 参数，仅为已 Commit 的章节初始化 Canon。

### RISK-3: `SimulatorLoopStateService.build()` 存在 `KeyError: 'revision'` Bug

```python
# simulator_loop_state_service.py (示意)
def build(self, branch_id):
    manifest = self.branch_registry[branch_id]
    return {
        'revision': manifest['revision'],  # ← KeyError: 'revision'
        # ...
    }
```

- **触发条件:** 分支注册表条目中缺少 `revision` 键（即分支从未被正式 revision 化）。
- **风险描述:** `SimulatorLoopStateService.build()` 在解析分支清单（branch manifest）时硬编码访问 `manifest['revision']`，当分支清单不包含该键时抛出 `KeyError`。这意味着：
  - **新建分支**首次运行模拟器循环时必然崩溃。
  - 分支清单解析逻辑缺乏对缺失键的防御性处理。
  - 此 Bug 会阻塞跨章节模拟器的启动流程。
- **影响范围:** 模拟器循环、分支创建、跨章节模拟执行。
- **建议修复:** 使用 `manifest.get('revision', DEFAULT_REVISION)` 并在分支注册表中明确 `revision` 字段的默认值。

### RISK-4: 缺少统一的章节创建权限 → 章节 N+1 创建未定义

```
Chapter N completed
  → Chapter N+1 creation authority = UNDEFINED
  → 多个服务可能同时尝试创建 Chapter N+1
  → 竞态条件 / 重复创建
```

- **触发条件:** 章节 N 的 Commit 完成后，没有明确的、唯一的服务被授权创建章节 N+1。
- **风险描述:** 当前架构中，多个服务（`ChapterService`、`CommitRunStore`、`NarrativeTurnContext`）均有潜在的章节创建入口，但没有统一的权限控制。这可能导致：
  - 两个服务同时创建 Chapter N+1 → 重复章节 ID → 数据冲突。
  - 客户端直接触发章节创建，绕过 INV-7（后端独占 ID 生成权）。
  - 章节创建的触发时机不确定（是 Commit 完成时？还是第一个 Turn 开始时？）。
- **影响范围:** 章节生命周期、数据一致性、ID 唯一性。
- **建议修复:** 设立 `ChapterCreationAuthority` 单点服务，仅在 `CommitRunStore.on_commit_completed()` 事件中被调用，统一处理章节 N+1 的创建。

### RISK-5: 缺少跨章节版本继承逻辑 → 章节 N+1 默认空版本列表

```
Chapter N versions: [v1, v2, v3]
  → Commit N complete
  → Chapter N+1 created
  → Chapter N+1 versions: []  ← 空列表，无任何继承
```

- **触发条件:** 章节 N 完成 Commit 后创建章节 N+1。
- **风险描述:** 当前版本管理机制中，章节 N+1 的版本列表为空，不继承章节 N 的任何版本。这可能导致：
  - 用户在章节 N+1 中无法访问章节 N 的历史版本作为参考。
  - 上下文装配时缺少版本锚点（version anchor），导致 AI 生成的内容与章节 N 的风格/设定不连贯。
  - 用户可能期望在章节 N+1 中看到章节 N 的版本历史，但实际看到的是空列表（与 RISK-1 中"读时创建"的行为矛盾——一个说空，一个说自动填充）。
- **影响范围:** 版本可用性、上下文连贯性、用户体验。
- **建议修复:** 明确策略：在章节创建时决定是否继承（read-only carry-forward）章节 N 的版本列表，或通过上下文源优先级中优先级 7（Chapter N Content）提供只读版本访问。

---

## 5. 风险汇总与修复优先级矩阵

| 风险 ID | 严重程度 | 触发概率 | 修复难度 | 建议优先级 |
|---------|---------|---------|---------|-----------|
| RISK-1 | 中 (P1) | 高 | 低 | **立即修复** — 读时写副作用违反最小惊讶原则 |
| RISK-2 | 高 (P0) | 中 | 中 | **立即修复** — 绕过 INV-1 不可变性约束 |
| RISK-3 | 高 (P0) | 高 | 低 | **立即修复** — 直接阻塞核心流程 |
| RISK-4 | 高 (P0) | 中 | 高 | **短期修复** — 需要架构层面的单点权限设计 |
| RISK-5 | 中 (P1) | 中 | 中 | **短期修复** — 影响用户体验但不阻塞流程 |

---

## 6. 不变量验证清单 (Invariant Verification Checklist)

在每次迭代或重构后，通过以下清单验证跨章节连续性是否仍被维护：

- [ ] **INV-1** 已提交章节的 Commit 在 `CommitRunStore` 中不可变
- [ ] **INV-2** 章节 N+1 的 Turn / Candidate / Review / Commit 操作集合与章节 N 完全隔离
- [ ] **INV-3** 章节 N 的候选在章节 N+1 中被 scope_check 拒绝
- [ ] **INV-4** 分支间无隐式状态读取通道
- [ ] **INV-5** 浏览操作不修改活动分支指针
- [ ] **INV-6** Refresh / Back / Forward 不触发 chapter_create 或 state_mutate
- [ ] **INV-7** 前端不生成 `chapter_id`
- [ ] **INV-8** 跨章节 selected version 不被隐式修改
- [ ] **Context Priority** 七个上下文源按优先级顺序装配，冲突按规则解决
- [ ] **RISK-1** `get_selected_version()` 无读时写副作用
- [ ] **RISK-2** `active_canon()` 仅为已 Commit 章节初始化 Canon
- [ ] **RISK-3** `SimulatorLoopStateService.build()` 对缺失键做防御性处理
- [ ] **RISK-4** 章节创建权限收敛到单一入口
- [ ] **RISK-5** 跨章节版本继承策略明确且已实现

---

## 附录: 术语表

| 术语 | 定义 |
|------|------|
| **Artifact (制品)** | StoryOS 中具有独立持久化生命周期的核心数据实体，如 Turn Plan、Commit、Candidate 等 |
| **Chapter (章节)** | 叙事流程的基本单元，拥有独立的 ID、版本历史和上下文快照 |
| **Canon (正典)** | 经 Commit 流程确认的、不可变的叙事真相集合 |
| **Commit (提交)** | 将章节的运行时状态固化为持久化历史的操作，由 `CommitRunStore` 管理 |
| **Narrative Memory (叙事记忆)** | 跨章节的角色/关系/地点状态存储，由 `NarrativeMemoryService` 管理 |
| **Branch (分支)** | 叙事的平行时间线，拥有独立的状态空间，通过 `NarrativeBranchStore` 注册 |
| **Scope (作用域)** | 制品的隔离边界，通常包含 project / timeline / branch / chapter 四个维度 |
| **Fingerprint (指纹)** | 制品内容的哈希摘要，用于跨版本 diff 检测 |
| **Source Priority (上下文源优先级)** | 上下文装配时各数据源的读取顺序和覆盖规则 |