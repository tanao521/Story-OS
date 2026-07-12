function renderKnowledgeStoreSummary() {}
let currentVersion = null;
let currentText = "";
let latestDraft = null;
let latestEdited = null;
let latestManual = null;
let selectedVersion = null;
let currentManualSource = null;
let projectAssets = [];
let currentAssetId = "story_spec";

async function readJsonResponse(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

function formatApiError(method, url, response, data) {
  const message = data && typeof data.message === "string" ? data.message : "";
  const errors = Array.isArray(data && data.errors) ? data.errors.filter(Boolean) : [];
  const warnings = Array.isArray(data && data.warnings) ? data.warnings.filter(Boolean) : [];
  const detailParts = [];
  if (message) detailParts.push(message);
  if (errors.length) detailParts.push(errors.join("；"));
  if (!message && warnings.length) detailParts.push(warnings.join("；"));
  return detailParts.length ? detailParts.join(" ") : `${method} ${url} failed: ${response.status}`;
}

async function apiGet(url) {
  const response = await fetch(url);
  const data = await readJsonResponse(response);
  if (!response.ok) throw new Error(formatApiError("GET", url, response, data));
  return data;
}

async function apiPost(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await readJsonResponse(response);
  if (!response.ok) throw new Error(formatApiError("POST", url, response, data));
  return data;
}

async function initializeApp() {
  await runWithBusy(async () => {
    const state = await apiGet("/api/project/init-state");
    if (state.result && state.result.initialized) {
      showDashboard();
      await refreshAll();
    } else {
      showSetupWizard();
    }
  });
}

function showSetupWizard() {
  document.getElementById("setup-view").classList.remove("hidden");
  document.getElementById("dashboard-view").classList.add("hidden");
  document.getElementById("logs-view").classList.add("hidden");
  document.getElementById("project-line").textContent = "首次使用：请先创建小说项目";
}

function showDashboard() {
  document.getElementById("setup-view").classList.add("hidden");
  document.getElementById("dashboard-view").classList.remove("hidden");
  document.getElementById("logs-view").classList.remove("hidden");
}

async function createStoryProject() {
  const title = valueOf("setup-title");
  const errorTarget = document.getElementById("setup-error");
  errorTarget.textContent = "";
  if (!title) {
    errorTarget.textContent = "小说标题不能为空。";
    return;
  }
  const body = {
    title,
    genre: valueOf("setup-genre"),
    custom_genre: valueOf("setup-custom-genre"),
    length_type: valueOf("setup-length"),
    target_word_count: Number(valueOf("setup-word-count") || 0),
    world_style: valueOf("setup-world-style"),
    tone: valueOf("setup-tone"),
    writing_style: valueOf("setup-writing-style"),
    narration: valueOf("setup-narration"),
    character_structure: valueOf("setup-character-structure"),
    romance_level: valueOf("setup-romance"),
    focus: listValueOf("setup-focus"),
    avoid: listValueOf("setup-avoid"),
    anti_ai_style_rules: listValueOf("setup-anti-ai"),
    need_outline: document.getElementById("setup-need-outline").checked,
    use_deepseek: document.getElementById("setup-use-deepseek").checked,
  };
  await runWithBusy(async () => {
    const result = await apiPost("/api/project/create", body);
    if (!result.ok) {
      errorTarget.textContent = result.message || "创建失败。";
      logApiResult("创建小说项目", result);
      return;
    }
    showDashboard();
    logApiResult("创建小说项目", result);
    logMessage("下一步：点击或运行 python main.py blueprint 生成故事蓝图。", "success");
    await refreshAll();
  });
}

async function refreshStatus() {
  const status = await apiGet("/api/status");
  const project = status.project || {};
  const progress = status.progress || {};
  const nextState = status.next_chapter_state || {};
  const quality = status.quality || {};
  const todos = status.todos || {};
  const foreshadows = status.foreshadows || {};
  const memory = status.memory || {};
  const actions = status.next_actions || [];
  updateShellContext(project, progress);
  renderKnowledgeStoreSummary(memory);
  document.getElementById("project-line").textContent =
    `${project.title || "未命名项目"} · 第 ${progress.next_chapter || 1} 章 · ${stageLabel(progress.current_stage)}`;
  document.getElementById("review-status").textContent =
    `当前审核状态：${nextState.review_status || "无"}`;
  document.getElementById("review-version").textContent = nextState.selected_version
    ? `当前审核版本：${versionLabel(nextState.selected_version)} · 质量评分：${formatScore(nextState.quality_score)}`
    : "当前未手动选择版本，将默认使用最新 edited。建议提交前先选择满意版本。";
  document.getElementById("next-action").textContent = actions[0]
    ? `下一步建议：${actions[0].command} · ${actions[0].reason}`
    : "下一步建议：生成故事蓝图";
  const metrics = [
    ["已提交章节", progress.current_chapter || 0],
    ["下一章", progress.next_chapter || 1],
    ["当前阶段", stageLabel(progress.current_stage)],
    ["审核状态", nextState.review_status || "无"],
    ["选中版本", versionLabel(nextState.selected_version)],
    ["质量评分", formatScore(quality.latest_score)],
    ["Open Todo", todos.open_count || 0],
    ["Open 伏笔", foreshadows.open_count || 0],
    ["Obsidian", memory.obsidian_synced ? "已同步" : "未同步"],
    ["向量库", memory.vector_memory_enabled ? `${memory.vector_indexed_chapters || 0}章/${memory.vector_chunks || 0}片段` : "未启用"],
  ];
  document.getElementById("status-metrics").innerHTML = metrics.map(([label, value]) => `<div class="metric"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(String(value))}</span></div>`).join("");
  renderChapterArchive(progress.active_chapters || []);
  renderFlowTrack(progress, nextState);
}

function renderFlowTrack(progress, nextState) {
  const track = document.getElementById("flow-track");
  if (!track) return;
  const steps = [
    { key: "blueprint", label: "故事大纲" },
    { key: "assets", label: "角色与世界观" },
    { key: "context", label: "背景构建" },
    { key: "plan", label: "章节规划" },
    { key: "draft", label: "草稿生成" },
    { key: "review", label: "审核" },
    { key: "edit", label: "AI 润色" },
    { key: "commit", label: "提交章节" },
  ];
  const stage = progress.current_stage || "";
  const hasPlan = nextState.plan_exists;
  const hasDraft = (nextState.draft_versions_count || 0) > 0;
  const reviewStatus = nextState.review_status || "";
  const hasEdited = (nextState.edited_versions_count || 0) > 0;
  const committed = stage.includes("committed") || progress.current_chapter > 0;

  const activeIndex = committed ? steps.length - 1
    : reviewStatus === "approved" ? 6
    : hasDraft ? 5
    : hasPlan ? 4
    : 3;

  track.innerHTML = steps.map((step, i) => {
    let cls = "flow-step";
    if (i < activeIndex) cls += " done";
    else if (i === activeIndex) cls += " active";
    else if (i === activeIndex + 1) cls += " warm";
    let status = i < activeIndex ? "已完成" : i === activeIndex ? "进行中" : "待处理";
    return `<div class="${cls}"><b>${i + 1}</b><span>${step.label}</span><small>${status}</small></div>`;
  }).join("");
}


function renderChapterArchive(chapters) {
  const target = document.getElementById("chapter-archive-list");
  if (!target) return;
  if (!chapters.length) {
    target.innerHTML = '<div class="empty-state">暂无可归档章节</div>';
    return;
  }
  target.innerHTML = chapters.map((chapter) => {
    const chapterId = Number(chapter.chapter_id || 0);
    const code = String(chapterId).padStart(3, "0");
    const title = chapter.title ? ` · ${chapter.title}` : "";
    return `<article class="version-card"><div class="version-title"><strong>第 ${code} 章${escapeHtml(title)}</strong></div><div class="version-meta">${escapeHtml(chapter.chapter_path || "")}</div><div class="card-actions"><button class="btn btn-danger" type="button" onclick="archiveChapter(${chapterId})">归档章节</button></div></article>`;
  }).join("");
}

async function archiveChapter(chapterId) {
  const code = String(Number(chapterId || 0)).padStart(3, "0");
  const confirmed = window.confirm(`确定要归档第 ${code} 章吗？\n\n归档后，该章节不会再参与后续生成、上下文构建和版本列表展示。\n相关草稿、编辑稿、人工稿和摘要会被移动到归档目录。\n此操作不会永久删除文件。`);
  if (!confirmed) return;
  await runAction("归档章节", () => apiPost(`/api/chapters/${Number(chapterId)}/archive`));
  await refreshAll();
}
async function loadVersions() {
  const data = await apiGet("/api/versions");
  latestDraft = lastItem(data.drafts || []);
  latestEdited = lastItem(data.edited || []);
  latestManual = lastItem(data.manual || []);
  selectedVersion = data.selected || null;
  document.getElementById("selected-version").textContent = `Selected: ${versionLabel(selectedVersion)}`;
  renderVersions("draft-list", data.drafts || []);
  renderVersions("edited-list", data.edited || []);
  renderVersions("manual-list", data.manual || []);
  populateManualSourceOptions(data);
}

function renderVersions(targetId, items, isCommitted = false) {
  const target = document.getElementById(targetId);
  if (!items.length) {
    target.innerHTML = '<div class="empty-state">暂无版本</div>';
    return;
  }
  target.innerHTML = items.map((item) => {
    const selected = selectedVersion && selectedVersion.source_type === item.source_type && Number(selectedVersion.version) === Number(item.version);
    const title = item.chapter_title ? ` · ${escapeHtml(item.chapter_title)}` : "";
    const actions = isCommitted
      ? `<button class="btn btn-secondary" type="button" onclick="loadVersionContent('${escapeJs(item.source_type)}', ${Number(item.version)})">查看正文</button>`
      : `<button class="btn btn-secondary" type="button" onclick="loadVersionContent('${escapeJs(item.source_type || "")}', ${Number(item.version || 0)})">查看</button><button class="btn btn-primary" type="button" onclick="selectVersion('${escapeJs(item.source_type || "")}', ${Number(item.version || 0)})">选择</button><button class="btn btn-secondary" type="button" onclick="compareWithOpposite('${escapeJs(item.source_type || "")}', ${Number(item.version || 0)})">对比</button><button class="btn btn-danger" type="button" onclick="archiveVersion('${escapeJs(item.source_type || "")}', ${Number(item.version || 0)}, ${Number(item.chapter_id || 0)})">弃用</button>`;
    return `<article class="version-card ${selected ? "selected" : ""}"><div class="version-title"><strong>${escapeHtml(versionLabel(item))}</strong>${title}${selected ? '<span class="status-token">Selected</span>' : ""}</div><div class="version-meta">${escapeHtml(String(item.actual_word_count || 0))} 字 · ${escapeHtml(item.mode || "unknown")}${item.quality_score ? ` · score=${escapeHtml(formatScore(item.quality_score))}` : ""}</div><code>${escapeHtml(item.json_path || "")}</code><div class="card-actions">${actions}</div></article>`;
  }).join("");
}

async function loadVersionContent(sourceType, version) {
  const data = await apiGet(`/api/versions/content?source_type=${encodeURIComponent(sourceType)}&version=${encodeURIComponent(version)}`);
  if (!data.ok) return logApiResult("查看版本", data);
  renderVersionContent(data.result);
  await loadQualityReport(sourceType, version);
}
async function selectVersion(sourceType, version) { await runAction("选择版本", () => apiPost("/api/versions/select", { source_type: sourceType, version })); await refreshAll(); }
async function archiveVersion(sourceType, version, chapterId) {
  const label = `${sourceType}_v${String(Number(version || 0)).padStart(3, "0")}`;
  const confirmed = window.confirm(`确定要弃用 ${label} 吗？\n\n弃用后，该版本会移动到归档目录，不再出现在章节版本列表，也不会作为后续审核、提交或人工稿来源。\n此操作不会永久删除文件。`);
  if (!confirmed) return;
  var body = { source_type: sourceType, version: Number(version) };
  if (chapterId) body.chapter_id = Number(chapterId);
  await runAction("弃用版本", () => apiPost("/api/versions/archive", body));
  if (currentVersion && currentVersion.source_type === sourceType && Number(currentVersion.version) === Number(version)) {
    currentVersion = null;
    currentText = "";
  }
  await refreshAll();
}
async function selectCurrentVersion() { if (!currentVersion) return logMessage("请先查看一个版本。", "warning"); await selectVersion(currentVersion.source_type, currentVersion.version); }
async function compareWithOpposite(sourceType, version) { const other = sourceType === "draft" ? (latestEdited || latestManual) : (latestManual || latestEdited || latestDraft); if (!other || (other.source_type === sourceType && Number(other.version) === Number(version))) return logMessage("缺少可对比的另一类版本。", "warning"); return loadVersionDiff(sourceType, version, other.source_type, other.version); }
async function loadVersionDiff(leftType, leftVersion, rightType, rightVersion) { const data = await apiGet(`/api/versions/diff?left_type=${leftType}&left_version=${leftVersion}&right_type=${rightType}&right_version=${rightVersion}`); if (!data.ok) return logApiResult("Diff 对比", data); renderDiff(data.result); }
async function loadQualityReport(sourceType, version) { const data = await apiGet(`/api/quality-report?source_type=${encodeURIComponent(sourceType)}&version=${encodeURIComponent(version)}`); if (!data.ok) return logApiResult("质量报告", data); renderQualityReport(data.result); }

function renderVersionContent(data) {
  currentVersion = { source_type: data.source_type, version: data.version };
  currentText = data.text || "";
  const generation = data.generation || {};
  const quality = data.quality || {};
  const isCommitted = data.source_type === "committed";
  document.getElementById("preview-meta").classList.remove("empty-state");
  document.getElementById("preview-meta").innerHTML = [["版本", data.version_label || ""], ["标题", data.title || ""], ["字数", data.word_count || 0], ["模式", generation.mode || "unknown"], ["评分", formatScore(quality.score)], ["路径", data.json_path || ""]].map(([label, value]) => `<div class="meta-item"><b>${escapeHtml(label)}</b><span>${escapeHtml(String(value))}</span></div>`).join("");
  var preview = document.getElementById("text-preview");
  preview.textContent = currentText || "该版本暂无正文内容。";
  preview.classList.remove("expanded");
  var toggle = document.getElementById("preview-toggle");
  if (toggle) { toggle.style.display = currentText ? "" : "none"; toggle.textContent = "展开全文"; }
}

function togglePreviewExpand() {
  var preview = document.getElementById("text-preview");
  var toggle = document.getElementById("preview-toggle");
  var expanded = preview.classList.toggle("expanded");
  if (expanded) {
    preview.textContent = currentText;
    toggle.textContent = "收起";
  } else {
    var lines = (currentText || "").split(/\n\n+/);
    var snippet = lines.slice(0, 3).join("\n\n");
    if (lines.length > 3) snippet += "\n\n...";
    preview.textContent = snippet;
    toggle.textContent = "展开全文";
  }
}

function togglePreviewExpand() {
  var preview = document.getElementById("text-preview");
  var toggle = document.getElementById("preview-toggle");
  var expanded = preview.classList.toggle("expanded");
  toggle.textContent = expanded ? "收起" : "展开全文";
}
function renderDiff(data) { const summary = data.summary || {}; document.getElementById("diff-summary").classList.remove("empty-state"); document.getElementById("diff-summary").innerHTML = [["对比", `${versionLabel(data.left)} -> ${versionLabel(data.right)}`], ["左侧字数", summary.left_chars || 0], ["右侧字数", summary.right_chars || 0], ["新增", summary.added_count || 0], ["删除", summary.removed_count || 0], ["变化比例", `${Math.round((summary.changed_ratio || 0) * 100)}%`]].map(([label, value]) => `<div class="meta-item"><b>${escapeHtml(label)}</b><span>${escapeHtml(String(value))}</span></div>`).join(""); document.getElementById("diff-output").innerHTML = data.diff_html || ""; }
function renderQualityReport(data) { if (!data.exists) { document.getElementById("quality-output").classList.add("empty-state"); document.getElementById("quality-output").innerHTML = '<p>当前版本尚未生成质量报告。</p><button class="btn btn-secondary" type="button" onclick="qualityCheck()">生成质量评估</button>'; return; } document.getElementById("quality-output").classList.remove("empty-state"); const risk = riskLevel(data.overall_score); const scores = Object.entries(data.scores || {}).map(([key, value]) => `<li>${escapeHtml(key)}：${escapeHtml(formatScore(value))}</li>`).join("") || "<li>暂无</li>"; const flags = (data.flags || []).map((item, index) => `<li>${index + 1}. [${escapeHtml(item.severity || "")}][${escapeHtml(item.type || "")}] ${escapeHtml(item.message || "")}</li>`).join("") || "<li>暂无</li>"; const suggestions = (data.suggestions || []).map((item) => `<li>${escapeHtml(String(item))}</li>`).join("") || "<li>暂无</li>"; document.getElementById("quality-output").innerHTML = `<div class="quality-score risk-${risk}">总分：${escapeHtml(formatScore(data.overall_score))} · 风险：${risk}</div><h3>分项评分</h3><ul>${scores}</ul><h3>问题</h3><ol>${flags}</ol><h3>建议</h3><ul>${suggestions}</ul>`; }


function populateManualSourceOptions(versions) {
  const select = document.getElementById("manual-source-select");
  if (!select) return;
  const items = [...(versions.drafts || []), ...(versions.edited || []), ...(versions.manual || []), ...(versions.committed || [])];
  if (!items.length) {
    select.innerHTML = '<option value="">暂无可载入版本</option>';
    currentManualSource = null;
    return;
  }
  const preferred = selectedVersion || latestManual || latestEdited || latestDraft || items[items.length - 1];
  select.innerHTML = items.map((item) => {
    const value = `${item.source_type}:${item.version}:${item.chapter_id || versions.chapter_id || 1}`;
    const selected = preferred && preferred.source_type === item.source_type && Number(preferred.version) === Number(item.version);
    return `<option value="${escapeHtml(value)}" ${selected ? "selected" : ""}>${escapeHtml(versionLabel(item))} · ${escapeHtml(String(item.actual_word_count || 0))} 字</option>`;
  }).join("");
}

async function loadManualSource(sourceType = "", version = 0) {
  const select = document.getElementById("manual-source-select");
  let chapterId = 1;
  if (!sourceType || !version) {
    const raw = select ? select.value : "";
    if (!raw) return logMessage("请先选择来源版本。", "warning");
    const parts = raw.split(":");
    sourceType = parts[0];
    version = Number(parts[1] || 0);
    chapterId = Number(parts[2] || 1);
  }
  const data = await apiGet(`/api/versions/content?source_type=${encodeURIComponent(sourceType)}&version=${encodeURIComponent(version)}`);
  if (!data.ok) return logApiResult("载入人工改稿来源", data);
  currentManualSource = { chapter_id: data.result.chapter_id || chapterId, source_type: sourceType, version: Number(version), version_label: data.result.version_label || "" };
  renderManualEditor(data.result);
}

function renderManualEditor(data) {
  const editor = document.getElementById("manualEditor");
  if (!editor) return;
  editor.value = data.text || "";
  document.getElementById("manual-source-meta").textContent = `来源：${data.version_label || versionLabel(currentManualSource)} · ${data.word_count || 0} 字 · ${data.json_path || ""}`;
  updateManualWordCount();
}

function updateManualWordCount() {
  const target = document.getElementById("manual-word-count");
  if (!target) return;
  target.textContent = `${getCurrentManualEditorText().trim().length} 字`;
}

function getCurrentManualEditorText() {
  return document.getElementById("manualEditor")?.value || "";
}

function clearManualEditor() {
  const editor = document.getElementById("manualEditor");
  if (!editor) return;
  editor.value = "";
  updateManualWordCount();
}

async function saveManualVersion() {
  const text = getCurrentManualEditorText();
  if (!text.trim()) return logMessage("正文不能为空。", "warning");
  if (!currentManualSource) await loadManualSource();
  if (!currentManualSource) return;
  const isCommitted = currentManualSource.source_type === "committed";
  const endpoint = isCommitted ? "/api/manual/commit-patch" : "/api/manual/save";
  const label = isCommitted ? "直接更新已提交正文" : "保存 manual 版本";
  await runAction(label, async () => {
    const result = await apiPost(endpoint, {
      chapter_id: currentManualSource.chapter_id,
      source_type: currentManualSource.source_type,
      source_version: currentManualSource.version,
      text,
    });
    if (result.ok && result.result) {
      logMessage(isCommitted
        ? `第${currentManualSource.chapter_id}章已更新，无需再次审核。`
        : `${result.result.version_label || "manual"} 已保存并选中。`, "success");
    }
    return result;
  });
  await refreshAll();
}

document.addEventListener("input", (event) => {
  if (event.target && event.target.id === "manualEditor") updateManualWordCount();
});

async function copyCurrentText() { if (!currentText) return logMessage("当前没有可复制的正文。", "warning"); if (!navigator.clipboard) return logMessage("当前浏览器不支持 clipboard。", "warning"); await navigator.clipboard.writeText(currentText); logMessage("正文已复制。", "success"); }
async function runChapter() { await runAction("生成下一章", () => apiPost("/api/run-chapter")); await refreshAll(); }
async function qualityCheck(notifyOnCompletion = false) { let result; await runWithBusy(async () => { result = await apiPost("/api/quality-check", {}); logApiResult("\u8d28\u91cf\u8bc4\u4f30", result); }); await refreshAll(); if (notifyOnCompletion && result && result.ok !== false) window.alert(result.message || "质量评估完成。"); }
async function approveReview(force = false, polish = null) { let result; await runWithBusy(async () => { result = await apiPost("/api/review/approve", { force, polish }); if (result.need_confirm && !force) { const confirmed = window.confirm(result.message || "当前版本质量评分较低，是否仍然继续？"); if (confirmed) result = await apiPost("/api/review/approve", { force: true, polish }); } logApiResult("审核通过", result); }); if (result && result.ok && result.polish_available && polish === null) { const continuePolish = window.confirm("审核已通过。是否继续 AI 润色？\n\n确定：AI 润色后提交章节。\n取消：直接提交当前审核版本。"); return approveReview(true, continuePolish); } if (result && !result.need_confirm) await refreshAll(); }
async function rejectReview() { await runAction("拒绝审核", () => apiPost("/api/review/reject")); await refreshAll(); }
async function laterReview() { await runAction("稍后审核", () => apiPost("/api/review/later")); await refreshAll(); }
async function syncObsidian() {
  const data = await apiGet("/api/versions");
  if (!(data.committed || []).length) return logMessage("没有已提交章节，无需同步。", "warning");
  await runAction("同步 Obsidian", () => apiPost("/api/sync-obsidian"));
  await refreshAll();
}
async function indexVault() {
  const data = await apiGet("/api/versions");
  if (!(data.committed || []).length) return logMessage("没有已提交章节，无需更新向量库。", "warning");
  await runAction("更新向量库", () => apiPost("/api/index-vault"));
  await refreshAll();
}
async function loadTodos() { const todos = await apiGet("/api/todos"); const target = document.getElementById("todo-list"); if (!todos.length) { target.innerHTML = '<div class="empty-state">暂无 open todo</div>'; return; } target.innerHTML = todos.map((todo) => `<article class="todo-card"><strong>#${Number(todo.id || 0)} ${escapeHtml(todo.title || "")}</strong><div class="version-meta">${escapeHtml(todo.priority || "")} · ${escapeHtml(todo.type || "")} · 第 ${escapeHtml(String(todo.chapter_id || "-"))} 章</div><div class="todo-actions"><button class="btn btn-secondary" type="button" onclick="todoAction(${Number(todo.id || 0)}, 'done')">完成</button><button class="btn btn-secondary" type="button" onclick="todoAction(${Number(todo.id || 0)}, 'reopen')">重开</button><button class="btn btn-danger" type="button" onclick="todoAction(${Number(todo.id || 0)}, 'cancel')">取消</button></div></article>`).join(""); }
async function addTodo() { const chapterValue = document.getElementById("todo-chapter").value; const body = { title: document.getElementById("todo-title").value, type: document.getElementById("todo-type").value, priority: document.getElementById("todo-priority").value, chapter_id: chapterValue ? Number(chapterValue) : null }; await runAction("添加 Todo", () => apiPost("/api/todos", body)); document.getElementById("todo-title").value = ""; await refreshAll(); }
async function todoAction(todoId, action) { await runAction("更新 Todo", () => apiPost(`/api/todos/${todoId}/${action}`)); await refreshAll(); }
async function askStory() { const body = { mode: document.getElementById("ask-mode").value, question: document.getElementById("ask-question").value, use_vector: document.getElementById("ask-vector").checked, use_llm: document.getElementById("ask-llm").checked }; const result = await apiPost("/api/ask", body); logApiResult("Ask Story", result); document.getElementById("ask-answer").textContent = JSON.stringify((result.result || {}).qa || {}, null, 2); }
async function refreshAll() {
  await runWithBusy(async () => {
    const tasks = [refreshStatus, loadCommittedChapters, loadProjectAssets, loadVersions, loadTodos, loadWritingConstraints];
    for (const task of tasks) {
      try { await task(); } catch (e) { console.error(task.name, e); }
    }
  }, "状态已刷新。");
}

async function loadCommittedChapters() {
  const target = document.getElementById("committed-chapter-list");
  if (!target) return;
  try {
    const data = await apiGet("/api/versions");
    const committed = data.committed || [];
    if (!committed.length) {
      target.innerHTML = '<div class="empty-state">暂无已提交章节</div>';
      return;
    }
    var ids = committed.map(function(c) { return Number(c.version || c.chapter_id || 0); }).sort(function(a,b){return a-b;});
    var maxId = ids[ids.length - 1];
    var idSet = {};
    ids.forEach(function(id) { idSet[id] = true; });
    var missing = [];
    for (var i = 1; i <= maxId; i++) {
      if (!idSet[i]) missing.push(i);
    }
    var summary = '<div class="cc-summary">已提交到第' + maxId + '章';
    if (missing.length) {
      summary += ' · <span class="cc-missing">缺失第' + missing.join('、') + '章</span>';
    }
    summary += '</div>';
    var list = committed.map(function(item) {
      var vid = Number(item.version || 0);
      var title = item.chapter_title || "";
      return '<button class="committed-chapter-row" type="button" onclick="loadVersionContent(&quot;committed&quot;, ' + vid + ')">'
        + '<span class="cc-id">#' + vid + '</span>'
        + '<span class="cc-title">' + title + '</span>'
        + '</button>';
    }).join("");
    target.innerHTML = summary + list;
  } catch (err) {
    target.innerHTML = '<div class="empty-state">读取失败</div>';
  }
}
async function runAction(label, action) { await runWithBusy(async () => { const result = await action(); logApiResult(label, result); }); }
async function runWithBusy(action, successMessage = "") { document.body.classList.add("is-busy"); try { await action(); if (successMessage) logMessage(successMessage, "success"); } catch (error) { logMessage(error.message, "error"); } finally { document.body.classList.remove("is-busy"); } }
function logApiResult(label, result) { const type = result.ok === false ? "error" : result.warnings && result.warnings.length ? "warning" : "success"; logMessage(`${label}：${result.message || "完成"}`, type); (result.warnings || []).forEach((item) => logMessage(`warning: ${item}`, "warning")); (result.errors || []).forEach((item) => logMessage(`error: ${item}`, "error")); }
function logMessage(message, type = "info") { const target = document.getElementById("log-output"); if (!target) return; const now = new Date().toLocaleTimeString(); const line = document.createElement("div"); line.className = `log-${type}`; line.textContent = `[${now}] ${message}`; target.prepend(line); }
function valueOf(id) { return (document.getElementById(id)?.value || "").trim(); }
function listValueOf(id) { return valueOf(id).replace(/，/g, ",").split(/[\n,]/).map((item) => item.trim()).filter(Boolean); }
function versionLabel(item) { if (!item) return "无"; return item.version_label || item.label || `${item.source_type || ""}_v${String(item.version || 0).padStart(3, "0")}`; }
function formatScore(value) { if (value === null || value === undefined || value === "") return "未评估"; const numeric = Number(value); return Number.isFinite(numeric) ? numeric.toFixed(2) : String(value); }
function riskLevel(score) { if (score === null || score === undefined) return "unknown"; const value = Number(score); if (value >= 0.8) return "low"; if (value >= 0.65) return "medium"; return "high"; }
function stageLabel(stage) { return stage || "unknown"; }
function lastItem(items) { return items.length ? items[items.length - 1] : null; }
function escapeHtml(value) { return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char])); }
function escapeJs(value) { return String(value).replace(/\\/g, "\\\\").replace(/'/g, "\\'"); }



async function loadProjectAssets() {
  const panel = document.getElementById("project-assets-panel");
  if (!panel) return;
  try {
    const data = await apiGet("/api/project-assets");
    projectAssets = (data.result && data.result.assets) || [];
    if (!projectAssets.length) {
      setAssetStatus("暂无可编辑项目档案。", "error");
      return;
    }
    if (!projectAssets.some((asset) => asset.id === currentAssetId)) currentAssetId = projectAssets[0].id;
    renderProjectAssetPicker();
    renderProjectAsset(currentAssetId);
    setAssetStatus("项目档案已读取。", "saved");
  } catch (error) {
    setAssetStatus("读取项目档案失败。", "error");
  }
}

function renderProjectAssetPicker() {
  const select = document.getElementById("asset-select");
  const list = document.getElementById("asset-list");
  if (select) {
    select.innerHTML = projectAssets.map((asset) => `<option value="${escapeHtml(asset.id)}" ${asset.id === currentAssetId ? "selected" : ""}>${escapeHtml(asset.label)}</option>`).join("");
  }
  if (list) {
    list.innerHTML = projectAssets.map((asset) => {
      const active = asset.id === currentAssetId ? "active" : "";
      const status = asset.exists ? "已存在" : "未创建";
      return `<button class="asset-card ${active}" type="button" onclick="selectProjectAsset('${escapeJs(asset.id)}')"><strong>${escapeHtml(asset.label)}</strong><span>${escapeHtml(status)} · ${escapeHtml(asset.format)}</span><code>${escapeHtml(asset.path)}</code></button>`;
    }).join("");
  }
}

function selectProjectAsset(assetId) {
  currentAssetId = assetId || currentAssetId;
  renderProjectAssetPicker();
  renderProjectAsset(currentAssetId);
}

function renderProjectAsset(assetId) {
  const asset = projectAssets.find((item) => item.id === assetId);
  if (!asset) return;
  const editor = document.getElementById("asset-editor");
  const meta = document.getElementById("asset-meta");
  if (editor) editor.value = asset.content || "";
  if (meta) meta.textContent = `${asset.exists ? "已存在" : "未创建"} · ${asset.format} · ${asset.path}`;
}

async function saveProjectAsset() {
  const editor = document.getElementById("asset-editor");
  if (!editor || !currentAssetId) return;
  const result = await apiPost(`/api/project-assets/${encodeURIComponent(currentAssetId)}`, { content: editor.value });
  logApiResult("项目档案", result);
  if (result.ok) {
    setAssetStatus("项目档案已保存。", "saved");
    await loadProjectAssets();
  } else {
    setAssetStatus(result.message || "保存失败。", "error");
  }
}

function setAssetStatus(message, type = "") {
  const target = document.getElementById("asset-save-status");
  if (!target) return;
  target.textContent = message;
  target.classList.remove("saved", "error");
  if (type) target.classList.add(type);
}

async function loadWritingConstraints() {
  const panel = document.getElementById("writing-constraints-panel");
  if (!panel) return;
  try {
    const data = await apiGet("/api/writing-constraints");
    const result = data.result || {};
    const words = result.chapter_word_count || {};
    setValue("constraint-word-min", words.min || "");
    setValue("constraint-word-max", words.max || "");
    setValue("constraint-pacing", result.pacing || "");
    setValue("constraint-structure", result.chapter_structure || "");
    setValue("constraint-must-follow", listToLines(result.must_follow));
    setValue("constraint-must-avoid", listToLines(result.must_avoid));
    setValue("constraint-ai-style", listToLines(result.ai_style_limits));
    setConstraintStatus("约束已读取。", "saved");
  } catch (error) {
    setConstraintStatus("读取写作约束失败。", "error");
  }
}

async function saveWritingConstraints() {
  const body = {
    chapter_word_count: {
      min: Number(valueOf("constraint-word-min") || 0),
      max: Number(valueOf("constraint-word-max") || 0),
    },
    pacing: valueOf("constraint-pacing"),
    chapter_structure: valueOf("constraint-structure"),
    must_follow: listValueOf("constraint-must-follow"),
    must_avoid: listValueOf("constraint-must-avoid"),
    ai_style_limits: listValueOf("constraint-ai-style"),
  };
  const result = await apiPost("/api/writing-constraints", body);
  logApiResult("写作约束", result);
  if (result.ok) {
    setConstraintStatus("写作约束已保存。", "saved");
    await loadWritingConstraints();
  } else {
    setConstraintStatus(result.message || "保存失败。", "error");
  }
}

function setValue(id, value) {
  const target = document.getElementById(id);
  if (target) target.value = value == null ? "" : String(value);
}

function listToLines(value) {
  return Array.isArray(value) ? value.join("\n") : "";
}

function setConstraintStatus(message, type = "") {
  const target = document.getElementById("constraint-save-status");
  if (!target) return;
  target.textContent = message;
  target.classList.remove("saved", "error");
  if (type) target.classList.add(type);
}


initializeDesignSystem();
initializeApp();
toggleInspector();

async function runMemoryHealth(full=false){const t=document.getElementById("memoryHealthOutput");if(t)t.textContent="Running memory health check...";try{const d=await apiGet("/api/memory-health"+(full?"?full=true":""));if(!d.ok){if(t)t.textContent="Memory health check failed.";logApiResult("Memory Health",d);return;}renderMemoryHealth(d.result||{});logApiResult("Memory Health",d);await refreshStatus();}catch(e){if(t)t.textContent="Memory health check failed.";logMessage("Memory health check failed.","error");}}
function renderMemoryHealth(report){const t=document.getElementById("memoryHealthOutput");if(!t)return;const s=report.summary||{},issues=Array.isArray(report.issues)?report.issues:[],suggestions=Array.isArray(report.suggestions)?report.suggestions:[];const statusText=report.overall_status==="ok"?"Memory state is healthy.":report.overall_status==="warning"?"Some issues need attention, but work can usually continue.":"Serious consistency issues exist; review them before generating chapters.";t.classList.remove("empty-state");t.innerHTML="<div class=\"health-summary\"><div class=\"health-status "+healthLevelClass(report.overall_status)+"\">"+escapeHtml(healthStatusLabel(report.overall_status))+"</div><div class=\"health-score\">Score: "+escapeHtml(formatScore(report.overall_score))+"</div><div>Errors: "+Number(s.errors||0)+"</div><div>Warnings: "+Number(s.warnings||0)+"</div><div>Infos: "+Number(s.infos||0)+"</div></div><p class=\"health-suggestion\">"+escapeHtml(statusText)+"</p><h3>Issues</h3><div class=\"health-issue-list\">"+(issues.length?issues.map(renderHealthIssue).join(""):"<div class=\"empty-state\">No issues.</div>")+"</div><h3>Suggestions</h3><ul class=\"health-suggestion-list\">"+(suggestions.length?suggestions.map(x=>"<li>"+escapeHtml(String(x))+"</li>").join(""):"<li>Keep the rolling chapter workflow.</li>")+"</ul>";}
function renderHealthIssue(issue){return "<article class=\"health-issue "+healthLevelClass(issue.level||"info")+"\"><strong>"+escapeHtml(issue.id||"issue")+"</strong><span class=\"health-category\">"+escapeHtml(issue.category||"")+"</span><p>"+escapeHtml(issue.message||"")+"</p><code class=\"health-path\">"+escapeHtml(issue.path||"")+"</code><p class=\"health-suggestion\">"+escapeHtml(issue.suggested_action||"")+"</p></article>";}
function healthStatusLabel(status){if(status==="ok")return "OK";if(status==="warning")return "Warning";if(status==="error")return "Error";return "Unknown";}
function healthLevelClass(level){if(level==="error")return "health-status-error health-issue-error";if(level==="warning")return "health-status-warning health-issue-warning";if(level==="ok")return "health-status-ok";return "health-status-info health-issue-info";}


function initializeDesignSystem() {
  document.querySelectorAll(".app-nav-item").forEach((link) => {
    link.addEventListener("click", (event) => {
      event.preventDefault();
      navigateToSection(link.dataset.section || "status-panel", link.dataset.asset || "", link);
    });
  });
  const dialog = document.getElementById("project-switch-dialog");
  if (dialog) dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close("cancel");
  });
}
function updateShellContext(project, progress) {
  const projectName = project.title || "Local Workspace";
  setShellText("topbar-project-name", projectName);
  setShellText("sidebar-project-name", projectName);
  setShellText("topbar-current-chapter", "第 " + (progress.next_chapter || 1) + " 章");
  setShellText("topbar-project-status", stageLabel(progress.current_stage));
}
function setShellText(id, value) {
  const target = document.getElementById(id);
  if (target) target.textContent = value;
}
function navigateToSection(sectionId, assetId = "", sourceLink = null) {
  const target = document.getElementById(sectionId);
  if (!target) return;
  if (target.closest("#context-inspector")) toggleInspector(true);
  if (assetId && typeof selectProjectAsset === "function") selectProjectAsset(assetId);
  document.querySelectorAll(".app-nav-item").forEach((item) => {
    const active = item === sourceLink;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  requestAnimationFrame(() => target.scrollIntoView({ behavior: "smooth", block: "start" }));
}
function toggleInspector(forceOpen = false) {
  const shouldCollapse = forceOpen ? false : !document.body.classList.contains("inspector-collapsed");
  document.body.classList.toggle("inspector-collapsed", shouldCollapse);
  const button = document.getElementById("inspector-toggle");
  if (button) {
    button.setAttribute("aria-expanded", String(!shouldCollapse));
    button.dataset.tooltip = shouldCollapse ? "展开上下文检查器" : "折叠上下文检查器";
  }
}
function openProjectSwitchDialog() {
  const dialog = document.getElementById("project-switch-dialog");
  if (dialog && typeof dialog.showModal === "function") dialog.showModal();
}
function openProjectSettingsFromDialog() {
  const dialog = document.getElementById("project-switch-dialog");
  if (dialog && dialog.open) dialog.close("settings");
  const link = document.querySelector(".app-nav-item[data-asset=story_spec]");
  setTimeout(() => navigateToSection("project-assets-panel", "story_spec", link), 0);
}



// Stage 2 workbench bindings: render only from existing API payloads.
let latestWorkbenchStatus = null;
let committedWorkbenchChapters = [];
let workbenchIssues = [];
let workbenchLogs = [];
let chapterRunInFlight = false;

const legacyRefreshStatus = refreshStatus;
refreshStatus = async function refreshWorkbenchStatus() {
  await legacyRefreshStatus();
  try {
    latestWorkbenchStatus = await apiGet("/api/status");
    renderWorkbenchStatus(latestWorkbenchStatus);
  } catch (error) {
    recordWorkbenchIssue("API 请求失败", error.message || "无法读取项目状态。", "/api/status", "refresh");
  }
};

const legacyLoadCommittedChapters = loadCommittedChapters;
loadCommittedChapters = async function loadWorkbenchChapters() {
  await legacyLoadCommittedChapters();
  try {
    const data = await apiGet("/api/versions");
    committedWorkbenchChapters = Array.isArray(data.committed) ? data.committed : [];
    (data.errors || []).forEach((item) => recordWorkbenchIssue("章节版本读取异常", String(item), "/api/versions", "refresh"));
    renderRecentChapters(committedWorkbenchChapters);
    renderWorkbenchStatus(latestWorkbenchStatus);
  } catch (error) {
    recordWorkbenchIssue("章节文件读取失败", error.message || "无法读取已提交章节。", "/api/versions", "refresh");
    renderRecentChapters([]);
  }
};

const legacyLogMessage = logMessage;
logMessage = function workbenchLogMessage(message, type = "info") {
  legacyLogMessage(message, type);
  workbenchLogs.unshift({ message: String(message || ""), type, time: new Date().toLocaleTimeString() });
  workbenchLogs = workbenchLogs.slice(0, 8);
  renderWorkbenchLogs();
  if (type === "error") recordWorkbenchIssue("运行失败", String(message || "操作失败。"), "运行日志", "refresh", false);
};

runChapter = async function runWorkbenchChapter() {
  if (chapterRunInFlight) {
    logMessage("生成任务正在运行，请等待当前请求完成。", "warning");
    return;
  }
  chapterRunInFlight = true;
  document.querySelectorAll("[data-workbench-generate]").forEach((button) => {
    button.disabled = true;
    button.dataset.originalLabel = button.textContent;
    button.textContent = "正在生成…";
  });
  try {
    await runAction("生成下一章", () => apiPost("/api/run-chapter"));
    await refreshAll();
  } finally {
    chapterRunInFlight = false;
    document.querySelectorAll("[data-workbench-generate]").forEach((button) => {
      button.disabled = false;
      button.textContent = button.dataset.originalLabel || "生成下一章";
    });
  }
};

function renderWorkbenchStatus(status) {
  if (!status) return;
  const project = status.project || {};
  const progress = status.progress || {};
  const nextState = status.next_chapter_state || {};
  const memory = status.memory || {};
  const foreshadows = status.foreshadows || {};
  const quality = status.quality || {};
  const health = status.health || {};
  const actions = Array.isArray(status.next_actions) ? status.next_actions : [];
  const nextChapter = Number(progress.next_chapter || 1);
  const action = actions[0] || {};
  const wordTotal = committedWorkbenchChapters.reduce((sum, item) => sum + Number(item.actual_word_count || 0), 0);
  setWorkbenchHtml("workbench-meta-list",
    "<span class=\"workbench-meta-item\"><strong>" + escapeHtml(project.title || "未命名项目") + "</strong></span>" +
    "<span class=\"workbench-meta-item\">" + escapeHtml(project.genre || "暂无类型") + "</span>" +
    "<span class=\"workbench-meta-item\">卷：暂无数据</span>" +
    "<span class=\"workbench-meta-item\">第 " + nextChapter + " 章</span>" +
    "<span class=\"workbench-meta-item\">" + escapeHtml(String(wordTotal)) + " 字</span>" +
    "<span class=\"workbench-meta-item\">更新时间：暂无数据</span>" +
    "<span class=\"workbench-meta-item\"><span class=\"status-dot is-online\"></span>本地服务</span>");
  setWorkbenchText("workbench-chapter-code", "CHAPTER " + String(nextChapter).padStart(3, "0"));
  setWorkbenchText("workbench-task-title", workbenchTaskTitle(action, nextState));
  setWorkbenchText("workbench-task-description", action.reason || "暂无下一步任务说明。");
  setWorkbenchHtml("workbench-task-facts",
    taskFact("大纲", nextState.plan_exists ? "已读取" : "暂无") +
    taskFact("上下文", memory.context_exists ? "已就绪" : "暂无") +
    taskFact("剧情阶段", stageLabel(progress.current_stage)) +
    taskFact("生成状态", nextState.review_status || "等待"));
  renderStoryState(progress, foreshadows, memory, quality);
  renderWorkbenchPipeline(progress, nextState, memory, health);
  collectHealthIssues(health);
  renderWorkbenchIssues();
}

function workbenchTaskTitle(action, nextState) {
  if (action.command) {
    const command = String(action.command);
    if (command.includes("run-chapter")) return nextState.plan_exists ? "根据当前计划生成下一章" : "准备下一章生成";
    if (command.includes("blueprint")) return "需要先准备故事蓝图";
    return command;
  }
  return nextState.plan_exists ? "准备生成下一章" : "等待下一步创作任务";
}

function taskFact(label, value) {
  return "<span class=\"workbench-task-fact\"><b>" + escapeHtml(label) + "</b>" + escapeHtml(String(value || "暂无数据")) + "</span>";
}

function renderStoryState(progress, foreshadows, memory, quality) {
  const openItems = Array.isArray(foreshadows.open_items) ? foreshadows.open_items : [];
  const cards = [
    ["当前剧情阶段", stageLabel(progress.current_stage), "项目状态接口返回"],
    ["待回收伏笔", openItems.length ? String(openItems.length) + " 项" : "暂无数据", openItems.length ? String(openItems[0].title || openItems[0].name || "待回收伏笔") : "当前接口未返回条目"],
    ["上下文读取", memory.context_exists ? "已读取" : "暂无数据", memory.context_exists ? "已有上下文文件" : "尚未读取到上下文文件"],
    ["质量状态", formatScore(quality.latest_score), quality.latest_score === null || quality.latest_score === undefined ? "暂无质量报告" : "最近质量评估"],
  ];
  setWorkbenchHtml("story-state-grid", cards.map((card) =>
    "<div class=\"story-state-item\"><span>" + escapeHtml(card[0]) + "</span><strong>" + escapeHtml(card[1]) + "</strong><small>" + escapeHtml(card[2]) + "</small></div>"
  ).join(""));
}

function renderRecentChapters(chapters) {
  const target = document.getElementById("chapter-archive-list");
  if (!target) return;
  const current = Number((latestWorkbenchStatus || {}).progress?.current_chapter || 0);
  if (!chapters.length) {
    target.innerHTML = "<div class=\"chapter-table-empty\">暂无已提交章节</div>";
    return;
  }
  const rows = chapters.slice().sort((a, b) => Number(b.chapter_id || b.version || 0) - Number(a.chapter_id || a.version || 0)).map((item) => {
    const id = Number(item.chapter_id || item.version || 0);
    const title = item.chapter_title || "未命名章节";
    const isCurrent = id === current;
    return "<tr class=\"" + (isCurrent ? "chapter-row-current" : "") + "\">" +
      "<td class=\"chapter-number\">#" + String(id).padStart(3, "0") + "</td>" +
      "<td><span class=\"chapter-name\" title=\"" + escapeHtml(title) + "\">" + escapeHtml(title) + "</span></td>" +
      "<td>" + escapeHtml(String(item.actual_word_count || 0)) + " 字</td>" +
      "<td><span class=\"chapter-status\">" + (isCurrent ? "当前" : "已提交") + "</span></td>" +
      "<td title=\"当前接口未提供更新时间\">—</td>" +
      "<td><span class=\"chapter-table-actions\"><button class=\"btn btn-link\" type=\"button\" onclick=\"openCommittedChapter(" + id + ")\">编辑</button><button class=\"btn btn-link\" type=\"button\" onclick=\"openChapterVersions(" + id + ")\">版本</button><details class=\"chapter-more-menu\"><summary class=\"icon-button\" aria-label=\"更多操作\">⋯</summary><div class=\"chapter-more-menu-menu\"><button type=\"button\" onclick=\"archiveChapter(" + id + ")\">归档章节</button></div></details></span></td></tr>";
  }).join("");
  target.innerHTML = "<table class=\"chapter-table\"><thead><tr><th>章节</th><th>标题</th><th>字数</th><th>状态</th><th>更新时间</th><th>操作</th></tr></thead><tbody>" + rows + "</tbody></table>";
}

function renderWorkbenchPipeline(progress, nextState, memory, health) {
  const missing = Array.isArray(health.missing_files) ? health.missing_files.join(" ") : "";
  const pipeline = [
    ["故事蓝图", missing.includes("story_blueprint") ? "异常" : "已检查", missing.includes("story_blueprint") ? "error" : "done"],
    ["读取上下文", memory.context_exists ? "已读取" : "暂无", memory.context_exists ? "done" : "current"],
    ["下一章计划", nextState.plan_exists ? "已读取" : "暂无", nextState.plan_exists ? "done" : "current"],
    ["草稿生成", Number(nextState.draft_versions_count || 0) ? String(nextState.draft_versions_count) + " 个草稿" : "等待", Number(nextState.draft_versions_count || 0) ? "done" : "current"],
    ["审核状态", nextState.review_status || "等待", nextState.review_status === "failed" ? "error" : "current"],
    ["提交章节", Number(progress.current_chapter || 0) ? "已提交至第 " + progress.current_chapter + " 章" : "等待", "current"],
  ];
  setWorkbenchHtml("workbench-pipeline-list", pipeline.map((item) =>
    "<div class=\"pipeline-row is-" + item[2] + "\"><span class=\"status-dot " + (item[2] === "error" ? "is-error" : item[2] === "done" ? "is-online" : "") + "\"></span><strong>" + escapeHtml(item[0]) + "</strong><small>" + escapeHtml(item[1]) + "</small></div>"
  ).join(""));
  setWorkbenchHtml("workbench-run-state",
    "<div class=\"workbench-inline-status\"><span class=\"status-dot " + (chapterRunInFlight ? "is-warning" : "is-online") + "\"></span>" + (chapterRunInFlight ? "正在执行生成请求" : "本地服务可用；等待操作") + "</div>");
}

function collectHealthIssues(health) {
  const issues = [];
  (health.errors || []).forEach((item) => issues.push({ title: "项目状态错误", detail: String(item), source: "状态检查", action: "refresh" }));
  (health.missing_files || []).forEach((item) => {
    const text = String(item);
    issues.push({ title: text.includes("story_blueprint") ? "故事蓝图缺失" : "项目文件缺失", detail: text, source: text, action: text.includes("story_blueprint") ? "outline" : "refresh" });
  });
  (health.warnings || []).forEach((item) => issues.push({ title: "项目状态提醒", detail: String(item), source: "状态检查", action: "refresh" }));
  workbenchIssues = issues.concat(workbenchIssues.filter((item) => item.runtime)).slice(0, 8);
}

function recordWorkbenchIssue(title, detail, source, action = "refresh", runtime = true) {
  const normalized = String(detail || "操作失败。");
  if (!workbenchIssues.some((item) => item.title === title && item.detail === normalized)) {
    workbenchIssues.unshift({ title, detail: normalized, source: source || "运行日志", action, runtime });
    workbenchIssues = workbenchIssues.slice(0, 8);
  }
  renderWorkbenchIssues();
}

function renderWorkbenchIssues() {
  const target = document.getElementById("workbench-error-list");
  if (!target) return;
  if (!workbenchIssues.length) {
    target.innerHTML = "<div class=\"inspector-empty\">暂无错误或提醒</div>";
    return;
  }
  target.innerHTML = workbenchIssues.map((item) =>
    "<article class=\"inspector-error-card\"><strong>" + escapeHtml(item.title) + "</strong><p>" + escapeHtml(item.detail) + "</p><code>" + escapeHtml(item.source) + "</code><div class=\"inspector-error-actions\"><button type=\"button\" onclick=\"workbenchRetry('" + escapeJs(item.action) + "')\">" + (item.action === "outline" ? "打开蓝图" : "重新读取") + "</button><button type=\"button\" onclick=\"navigateToSection('logs-view')\">查看日志</button></div></article>"
  ).join("");
}

function renderWorkbenchLogs() {
  const target = document.getElementById("workbench-log-list");
  if (!target) return;
  target.innerHTML = workbenchLogs.length ? workbenchLogs.slice(0, 4).map((item) =>
    "<div class=\"inspector-log-line " + (item.type === "error" ? "is-error" : "") + "\">[" + escapeHtml(item.time) + "] " + escapeHtml(item.message) + "</div>"
  ).join("") : "<div class=\"inspector-empty\">暂无运行日志</div>";
}

function workbenchRetry(action) {
  if (action === "outline") return openOutlineEditor();
  if (action === "run") return runChapter();
  return refreshAll();
}

function openOutlineEditor() {
  const link = document.querySelector(".app-nav-item[data-asset='story_blueprint']");
  navigateToSection("project-assets-panel", "story_blueprint", link);
}

async function openCommittedChapter(chapterId) {
  await loadVersionContent("committed", chapterId);
  navigateToSection("preview-panel");
}

async function openChapterVersions(chapterId) {
  await loadVersionContent("committed", chapterId);
  const link = document.querySelector(".app-nav-item[href='#versions-panel']");
  navigateToSection("versions-panel", "", link);
}

function setWorkbenchHtml(id, html) {
  const target = document.getElementById(id);
  if (target) target.innerHTML = html;
}

function setWorkbenchText(id, text) {
  const target = document.getElementById(id);
  if (target) target.textContent = text;
}



// Stage 3 chapter management: client-side indexing over existing status and version data.
let chapterManagerRows = [];
let chapterManagerSelectedId = null;
let chapterManagerQuery = "";
let chapterManagerFilter = "all";
let chapterManagerSort = "number-desc";
let chapterManagerLoadError = "";
let chapterManagerArchiveId = null;

const stage2LoadCommittedChapters = loadCommittedChapters;
loadCommittedChapters = async function loadChapterManager() {
  await stage2LoadCommittedChapters();
  try {
    const data = await apiGet("/api/versions");
    chapterManagerLoadError = "";
    chapterManagerRows = buildChapterManagerRows(data, latestWorkbenchStatus || {});
    renderChapterManager();
    renderChapterManagerInspector();
  } catch (error) {
    chapterManagerRows = [];
    chapterManagerLoadError = error.message || "无法读取章节列表。";
    renderChapterManager();
    renderChapterManagerInspector();
  }
};

function buildChapterManagerRows(data, status) {
  const groups = new Map();
  const ensure = (chapterId) => {
    const id = Number(chapterId || 0);
    if (!id) return null;
    if (!groups.has(id)) groups.set(id, { id, title: "", wordCount: 0, committed: null, variants: [], updatedAt: "", hasFailure: false });
    return groups.get(id);
  };
  (data.committed || []).forEach((item) => {
    const row = ensure(item.chapter_id || item.version);
    if (!row) return;
    row.committed = item;
    row.title = item.chapter_title || row.title;
    row.wordCount = Number(item.actual_word_count || 0);
    row.filePath = item.markdown_path || item.json_path || "";
  });
  ["drafts", "edited", "manual"].forEach((type) => {
    (data[type] || []).forEach((item) => {
      const row = ensure(item.chapter_id);
      if (!row) return;
      row.variants.push(item);
      if (!row.title) row.title = item.chapter_title || "";
      if (!row.wordCount) row.wordCount = Number(item.actual_word_count || 0);
      if (item.created_at && (!row.updatedAt || String(item.created_at) > row.updatedAt)) row.updatedAt = String(item.created_at);
      if (item.error || item.failed || item.status === "failed") row.hasFailure = true;
    });
  });
  const current = Number((status.progress || {}).current_chapter || 0);
  return Array.from(groups.values()).map((row) => {
    row.isCurrent = row.id === current;
    row.title = row.title || "";
    row.variantCount = row.variants.length;
    row.openItem = row.committed || row.variants[row.variants.length - 1] || null;
    row.filePath = row.filePath || (row.openItem && (row.openItem.markdown_path || row.openItem.json_path)) || "";
    row.statusKey = row.hasFailure ? "failed" : row.committed ? "completed" : row.variants.length ? "draft" : row.title ? "untitled" : "empty";
    if (!row.title) row.statusKey = row.wordCount ? "untitled" : "empty";
    return row;
  });
}

function renderChapterManager() {
  const target = document.getElementById("chapter-manager-list");
  const countTarget = document.getElementById("chapter-manager-count");
  if (!target) return;
  if (countTarget) countTarget.textContent = chapterManagerRows.length + " 章";
  if (chapterManagerLoadError) {
    target.innerHTML = "<div class=\"chapter-manager-empty\">章节数据读取失败：" + escapeHtml(chapterManagerLoadError) + " <button class=\"btn btn-secondary btn-compact\" type=\"button\" onclick=\"refreshAll()\">重新读取</button></div>";
    return;
  }
  if (!chapterManagerRows.length) {
    target.innerHTML = "<div class=\"chapter-manager-empty\">当前项目尚无可读取章节。</div>";
    return;
  }
  const rows = getVisibleChapterManagerRows();
  if (!rows.length) {
    const message = chapterManagerQuery ? "未找到匹配的章节。" : "当前筛选条件下没有章节。";
    target.innerHTML = "<div class=\"chapter-manager-empty\">" + message + "</div>";
    return;
  }
  target.innerHTML = "<table class=\"chapter-manager-table\"><thead><tr><th>章节</th><th>标题</th><th>字数</th><th>状态</th><th>更新时间</th><th>版本</th><th>操作</th></tr></thead><tbody>" + rows.map(renderChapterManagerRow).join("") + "</tbody></table>";
}

function getVisibleChapterManagerRows() {
  const query = chapterManagerQuery.trim().toLowerCase();
  const rows = chapterManagerRows.filter((row) => {
    const searchable = (String(row.id) + " " + String(row.title || "")).toLowerCase();
    if (query && !searchable.includes(query)) return false;
    if (chapterManagerFilter === "current") return row.isCurrent;
    if (chapterManagerFilter === "all") return true;
    return row.statusKey === chapterManagerFilter;
  }).slice();
  rows.sort((left, right) => {
    if (chapterManagerSort === "number-asc") return left.id - right.id;
    if (chapterManagerSort === "words-desc") return right.wordCount - left.wordCount || right.id - left.id;
    if (chapterManagerSort === "updated-desc") return String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")) || right.id - left.id;
    return right.id - left.id;
  });
  return rows;
}

function renderChapterManagerRow(row) {
  const selected = Number(chapterManagerSelectedId) === row.id;
  const status = chapterManagerStatusLabel(row);
  const title = row.title || "未命名章节";
  const update = row.updatedAt ? escapeHtml(formatChapterManagerTime(row.updatedAt)) : "<span class=\"chapter-manager-muted\" title=\"当前接口未提供更新时间\">—</span>";
  return "<tr class=\"chapter-manager-row " + (row.isCurrent ? "is-current " : "") + (selected ? "is-selected" : "") + "\" data-chapter-manager-id=\"" + row.id + "\" onclick=\"selectChapterManager(" + row.id + ")\">" +
    "<td class=\"chapter-manager-id\">#" + String(row.id).padStart(3, "0") + "</td>" +
    "<td><span class=\"chapter-manager-title\" title=\"" + escapeHtml(title) + "\">" + escapeHtml(title) + "</span></td>" +
    "<td>" + escapeHtml(String(row.wordCount || 0)) + " 字</td>" +
    "<td><span class=\"chapter-manager-status is-" + status.key + "\">" + status.label + "</span></td>" +
    "<td>" + update + "</td>" +
    "<td>" + chapterManagerVersionCount(row) + "</td>" +
    "<td onclick=\"event.stopPropagation()\"><span class=\"chapter-manager-actions\"><button class=\"btn btn-link\" type=\"button\" onclick=\"openChapterManagerEditor(" + row.id + ")\">编辑</button><button class=\"btn btn-link\" type=\"button\" onclick=\"openChapterManagerVersions(" + row.id + ")\">版本</button><details class=\"chapter-manager-more\"><summary class=\"icon-button\" aria-label=\"更多操作\">⋯</summary><div class=\"chapter-manager-more-menu\"><button type=\"button\" onclick=\"openChapterManagerPreview(" + row.id + ")\">预览正文</button><button class=\"danger\" type=\"button\" onclick=\"archiveChapter(" + row.id + ")\">归档章节</button></div></details></span></td></tr>";
}

function chapterManagerVersionCount(row) { if (row.variantCount) return String(row.variantCount); if (!row.isCurrent) return "—"; const nextState = (latestWorkbenchStatus || {}).next_chapter_state || {}; const count = Number(nextState.draft_versions_count || 0) + Number(nextState.edited_versions_count || 0) + Number(nextState.manual_versions_count || 0); return count ? String(count) : "—"; }

function chapterManagerStatusLabel(row) {
  if (row.isCurrent) return { key: "current", label: "当前章节" };
  if (row.statusKey === "draft") return { key: "draft", label: "草稿" };
  if (row.statusKey === "failed") return { key: "failed", label: "生成失败" };
  if (row.statusKey === "untitled") return { key: "untitled", label: "无标题" };
  if (row.statusKey === "empty") return { key: "empty", label: "无正文" };
  return { key: "completed", label: "已完成" };
}

function formatChapterManagerTime(value) {
  const text = String(value || "");
  return text ? text.replace("T", " ").replace(/Z$/, "") : "—";
}

function chapterManagerSetSearch(value) {
  chapterManagerQuery = String(value || "");
  renderChapterManager();
}

function chapterManagerSetFilter(value) {
  chapterManagerFilter = String(value || "all");
  renderChapterManager();
}

function chapterManagerSetSort(value) {
  chapterManagerSort = String(value || "number-desc");
  renderChapterManager();
}

function selectChapterManager(chapterId) {
  chapterManagerSelectedId = Number(chapterId);
  document.querySelectorAll("[data-chapter-manager-id]").forEach((node) => node.classList.toggle("is-selected", Number(node.dataset.chapterManagerId) === chapterManagerSelectedId));
  renderChapterManagerInspector();
}

function getChapterManagerRow(chapterId) {
  return chapterManagerRows.find((row) => row.id === Number(chapterId)) || null;
}

function renderChapterManagerInspector() {
  const target = document.getElementById("chapter-management-inspector-content");
  if (!target) return;
  const row = getChapterManagerRow(chapterManagerSelectedId);
  if (!row) {
    target.innerHTML = "<div class=\"inspector-empty\">选择一个章节查看文件与版本信息。</div>";
    return;
  }
  const status = latestWorkbenchStatus || {};
  const foreshadows = ((status.foreshadows || {}).open_items || []).filter((item) => String(item.introduced_at || "") === "chapter_" + String(row.id).padStart(3, "0"));
  const title = row.title || "未命名章节";
  const selectedVersion = chapterManagerSelectedVersionLabel(row);
  target.innerHTML = "<h3 class=\"chapter-inspector-title\">第 " + String(row.id).padStart(3, "0") + " 章 · " + escapeHtml(title) + "</h3>" +
    "<div class=\"chapter-inspector-meta\"><div><span>字数</span><strong>" + escapeHtml(String(row.wordCount || 0)) + " 字</strong></div><div><span>更新时间</span><strong>" + escapeHtml(row.updatedAt ? formatChapterManagerTime(row.updatedAt) : "暂无数据") + "</strong></div><div><span>文件状态</span><strong>" + (row.filePath ? "已列出" : "暂无正文文件") + "</strong></div><div><span>当前版本</span><strong>" + escapeHtml(selectedVersion) + "</strong></div><div><span>涉及角色</span><strong>暂无角色数据</strong></div><div><span>伏笔</span><strong>" + (foreshadows.length ? String(foreshadows.length) + " 项" : "暂无数据") + "</strong></div><div><span>连贯性状态</span><strong>暂无连贯性检查结果</strong></div></div>" +
    (row.filePath ? "<div class=\"chapter-inspector-file\" title=\"" + escapeHtml(row.filePath) + "\">" + escapeHtml(row.filePath) + "</div>" : "") +
    "<p class=\"chapter-inspector-note\">角色与连贯性结果当前接口未提供，未填充模拟数据。</p><div class=\"chapter-inspector-actions\"><button class=\"btn btn-primary\" type=\"button\" onclick=\"openChapterManagerEditor(" + row.id + ")\">打开编辑器</button><button class=\"btn btn-secondary\" type=\"button\" onclick=\"openChapterManagerVersions(" + row.id + ")\">查看版本</button></div>";
}

function chapterManagerSelectedVersionLabel(row) {
  const selected = selectedVersion || ((latestWorkbenchStatus || {}).versions || {}).selected || null;
  if (!selected) return row.committed ? "已提交章节" : "暂无选中版本";
  const path = String(selected.json_path || selected.markdown_path || "");
  if (path.includes("chapter_" + String(row.id).padStart(3, "0"))) return versionLabel(selected);
  return row.committed ? "已提交章节" : "暂无选中版本";
}

async function openChapterManagerEditor(chapterId) {
  const row = getChapterManagerRow(chapterId);
  if (!row || !row.openItem) return logMessage("该章节暂无可打开正文。", "warning");
  await loadVersionContent(row.openItem.source_type || (row.committed ? "committed" : "draft"), Number(row.openItem.version || row.id));
  navigateToSection("preview-panel");
}

async function openChapterManagerPreview(chapterId) {
  await openChapterManagerEditor(chapterId);
}

async function openChapterManagerVersions(chapterId) {
  const row = getChapterManagerRow(chapterId);
  if (row && row.openItem) await loadVersionContent(row.openItem.source_type || "committed", Number(row.openItem.version || row.id));
  const link = document.querySelector(".app-nav-item[href='#versions-panel']");
  navigateToSection("versions-panel", "", link);
}

const stage2ArchiveChapter = archiveChapter;
archiveChapter = function openChapterArchiveDialog(chapterId) {
  const row = getChapterManagerRow(chapterId);
  if (!row) return logMessage("未找到该章节的当前列表项。", "warning");
  chapterManagerArchiveId = row.id;
  const dialog = document.getElementById("chapter-archive-dialog");
  const body = document.getElementById("chapter-archive-dialog-body");
  if (!dialog || !body) return stage2ArchiveChapter(chapterId);
  body.innerHTML = "<div class=\"chapter-archive-dialog-summary\"><strong>第 " + String(row.id).padStart(3, "0") + " 章 · " + escapeHtml(row.title || "未命名章节") + "</strong><p>归档后，该章节不会参与后续生成、上下文构建和版本列表展示。</p><div class=\"archive-impact\">相关正文、草稿、编辑稿、人工稿和摘要会被移动到归档目录。当前网页没有恢复入口；本操作不会永久删除文件。</div></div>";
  if (typeof dialog.showModal === "function") dialog.showModal();
}

function closeChapterArchiveDialog() {
  const dialog = document.getElementById("chapter-archive-dialog");
  if (dialog && dialog.open) dialog.close();
  chapterManagerArchiveId = null;
}

async function confirmChapterArchive() {
  const chapterId = Number(chapterManagerArchiveId || 0);
  if (!chapterId) return closeChapterArchiveDialog();
  const button = document.getElementById("chapter-archive-confirm");
  if (button) { button.disabled = true; button.textContent = "正在归档…"; }
  try {
    const result = await apiPost("/api/chapters/" + chapterId + "/archive");
    logApiResult("归档章节", result);
    if (result.ok === false) {
      chapterManagerLoadError = result.message || "归档章节失败。";
      renderChapterManager();
      return;
    }
    chapterManagerSelectedId = null;
    closeChapterArchiveDialog();
    await refreshAll();
    logMessage("章节已归档，列表和当前章节状态已更新。", "success");
  } catch (error) {
    chapterManagerLoadError = error.message || "归档章节失败。";
    renderChapterManager();
    logMessage(chapterManagerLoadError, "error");
  } finally {
    if (button) { button.disabled = false; button.textContent = "归档章节"; }
  }
}



// Stage 4 immersive chapter editor: retain the existing textarea and manual-version save contract.
let chapterEditorDirty = false;
let chapterEditorSaving = false;
let chapterEditorBaseline = "";
let chapterEditorLastSavedAt = "";
let chapterEditorPreviewMode = false;
let chapterEditorStatFrame = 0;

const stage4PopulateManualSourceOptions = populateManualSourceOptions;
populateManualSourceOptions = function populateEditorSources(versions) {
  const statusVersions = (latestWorkbenchStatus || {}).versions || {};
  const merged = {
    ...versions,
    drafts: (versions.drafts && versions.drafts.length) ? versions.drafts : (statusVersions.drafts || []),
    edited: (versions.edited && versions.edited.length) ? versions.edited : (statusVersions.edited || []),
    manual: (versions.manual && versions.manual.length) ? versions.manual : (statusVersions.manual || []),
  };
  stage4PopulateManualSourceOptions(merged);
};

const stage4RenderManualEditor = renderManualEditor;
renderManualEditor = function renderImmersiveEditor(data) {
  stage4RenderManualEditor(data);
  const text = getCurrentManualEditorText();
  chapterEditorBaseline = text;
  chapterEditorDirty = false;
  chapterEditorPreviewMode = false;
  document.getElementById("manual-editor-panel")?.classList.remove("is-previewing");
  setChapterEditorText("chapter-editor-code", "CHAPTER " + String((data.chapter_id || currentManualSource?.chapter_id || 0)).padStart(3, "0"));
  setChapterEditorText("chapter-editor-heading", data.title || data.chapter_title || data.version_label || "手动改稿");
  setChapterEditorText("chapter-editor-version", "当前版本：" + (data.version_label || versionLabel(currentManualSource)));
  setChapterEditorText("chapter-editor-file-status", "本地文件：" + (data.json_path || "已载入"));
  setChapterEditorSaveState("saved", "已载入");
  updateChapterEditorStats(true);
  renderChapterEditorInspector();
};

const stage4LoadManualSource = loadManualSource;
loadManualSource = async function guardedManualSource(sourceType = "", version = 0) {
  if (chapterEditorDirty && !window.confirm("当前改稿尚未保存。继续载入其他版本将丢失未保存修改，是否继续？")) return;
  await stage4LoadManualSource(sourceType, version);
};

const stage4ClearManualEditor = clearManualEditor;
clearManualEditor = function clearImmersiveEditor() {
  if (chapterEditorDirty && !window.confirm("确定清空当前未保存改动吗？")) return;
  stage4ClearManualEditor();
  markChapterEditorDirty();
};

const stage4OpenChapterManagerEditor = openChapterManagerEditor;
openChapterManagerEditor = async function openImmersiveChapterEditor(chapterId) {
  const statusVersions = (latestWorkbenchStatus || {}).versions || {};
  const entries = ["manual", "edited", "drafts"].flatMap((type) => (statusVersions[type] || []).map((item) => ({ ...item, source_type: item.source_type || (type === "drafts" ? "draft" : type) }))).filter((item) => Number(item.chapter_id || 0) === Number(chapterId));
  const priority = entries.sort((left, right) => {
    const order = { manual: 3, edited: 2, draft: 1 };
    return (order[right.source_type] || 0) - (order[left.source_type] || 0) || Number(right.version || 0) - Number(left.version || 0);
  })[0];
  if (priority) {
    await loadManualSource(priority.source_type, Number(priority.version));
    navigateToSection("manual-editor-panel");
    return;
  }
  await loadVersionContent("committed", Number(chapterId));
  chapterEditorBaseline = "";
  chapterEditorDirty = false;
  setChapterEditorText("chapter-editor-code", "CHAPTER " + String(chapterId).padStart(3, "0"));
  setChapterEditorText("chapter-editor-heading", "当前章节没有可编辑来源版本");
  setChapterEditorText("chapter-editor-version", "当前版本：已提交章节");
  setChapterEditorText("chapter-editor-file-status", "本地文件：已载入预览");
  setChapterEditorSaveState("error", "当前章节仅可预览");
  renderChapterEditorInspector();
  navigateToSection("preview-panel");
};

openCommittedChapter = async function openCommittedInEditor(chapterId) {
  await openChapterManagerEditor(chapterId);
};

function markChapterEditorDirty() {
  chapterEditorDirty = getCurrentManualEditorText() !== chapterEditorBaseline;
  if (!chapterEditorSaving) setChapterEditorSaveState(chapterEditorDirty ? "dirty" : "saved", chapterEditorDirty ? "有未保存修改" : "已保存");
  updateChapterEditorStats();
}

function updateChapterEditorStats(immediate = false) {
  if (!immediate && chapterEditorStatFrame) return;
  const update = () => {
    chapterEditorStatFrame = 0;
    const editor = document.getElementById("manualEditor");
    if (!editor) return;
    const text = editor.value || "";
    const paragraphs = text.trim() ? text.split(/\n\s*\n/).filter((part) => part.trim()).length : 0;
    const progress = editor.scrollHeight > editor.clientHeight ? Math.round((editor.scrollTop / (editor.scrollHeight - editor.clientHeight)) * 100) : 0;
    setChapterEditorText("manual-word-count", text.trim().length + " 字");
    setChapterEditorText("chapter-editor-word-count", text.trim().length + " 字");
    setChapterEditorText("chapter-editor-paragraph-count", paragraphs + " 段");
    setChapterEditorText("chapter-editor-position", "位置 " + progress + "%");
    const preview = document.getElementById("chapter-editor-preview");
    if (preview && chapterEditorPreviewMode) preview.textContent = text;
  };
  if (immediate) update();
  else chapterEditorStatFrame = requestAnimationFrame(update);
}

function setChapterEditorSaveState(state, label) {
  const target = document.getElementById("chapter-editor-save-status");
  if (!target) return;
  target.className = "chapter-editor-save-status is-" + state;
  target.textContent = label;
  setChapterEditorText("chapter-editor-saved-at", chapterEditorLastSavedAt || "—");
}

function setChapterEditorText(id, value) {
  const target = document.getElementById(id);
  if (target) target.textContent = value;
}

function toggleChapterEditorPreview() {
  const panel = document.getElementById("manual-editor-panel");
  const preview = document.getElementById("chapter-editor-preview");
  if (!panel || !preview) return;
  chapterEditorPreviewMode = !chapterEditorPreviewMode;
  preview.textContent = getCurrentManualEditorText();
  panel.classList.toggle("is-previewing", chapterEditorPreviewMode);
  updateChapterEditorStats(true);
}

function openChapterEditorVersions() {
  const link = document.querySelector(".app-nav-item[href='#versions-panel']");
  navigateToSection("versions-panel", "", link);
}

function chapterEditorBackToList() {
  if (chapterEditorDirty && !window.confirm("当前改稿尚未保存。返回章节列表将保留页面内文本但可能在刷新后丢失，是否继续？")) return;
  const link = document.querySelector(".app-nav-item[href='#chapter-archive-panel']");
  navigateToSection("chapter-archive-panel", "", link);
}

saveManualVersion = async function saveImmersiveManualVersion() {
  const text = getCurrentManualEditorText();
  if (!text.trim()) return logMessage("正文不能为空。", "warning");
  if (!currentManualSource) return logMessage("请选择草稿、编辑稿或人工稿作为改稿来源。", "warning");
  if (currentManualSource.source_type === "committed") {
    setChapterEditorSaveState("error", "已提交正文不可直接改写");
    return logMessage("当前后端只支持从草稿、编辑稿或人工稿创建 manual 版本。", "warning");
  }
  chapterEditorSaving = true;
  const button = document.getElementById("chapter-editor-save");
  if (button) { button.disabled = true; button.textContent = "保存中…"; }
  setChapterEditorSaveState("saving", "保存中");
  try {
    const result = await apiPost("/api/manual/save", {
      chapter_id: currentManualSource.chapter_id,
      source_type: currentManualSource.source_type,
      source_version: currentManualSource.version,
      text,
    });
    logApiResult("保存 manual 版本", result);
    if (result.ok === false || !result.result) {
      setChapterEditorSaveState("error", (result.errors && result.errors[0]) || result.message || "保存失败");
      return;
    }
    currentManualSource = {
      chapter_id: Number(result.result.chapter_id || currentManualSource.chapter_id),
      source_type: "manual",
      version: Number(result.result.version || currentManualSource.version),
      version_label: result.result.version_label || "manual",
    };
    chapterEditorBaseline = text;
    chapterEditorDirty = false;
    chapterEditorLastSavedAt = new Date().toLocaleTimeString();
    setChapterEditorText("chapter-editor-version", "当前版本：" + currentManualSource.version_label);
    setChapterEditorText("chapter-editor-file-status", "本地文件：" + (result.result.markdown_path || result.result.json_path || "已保存"));
    setChapterEditorSaveState("saved", "已保存");
    renderChapterEditorInspector();
    await refreshAll();
  } catch (error) {
    setChapterEditorSaveState("error", error.message || "保存失败");
    logMessage(error.message || "保存失败", "error");
  } finally {
    chapterEditorSaving = false;
    if (button) { button.disabled = false; button.textContent = "保存"; }
  }
};

function renderChapterEditorInspector() {
  const target = document.getElementById("chapter-editor-inspector-content");
  if (!target) return;
  const chapterId = Number(currentManualSource?.chapter_id || 0);
  if (!chapterId) {
    target.innerHTML = "<div class=\"inspector-empty\">载入章节后显示真实上下文。</div>";
    return;
  }
  const status = latestWorkbenchStatus || {};
  const foreshadows = ((status.foreshadows || {}).open_items || []).filter((item) => String(item.introduced_at || "") === "chapter_" + String(chapterId).padStart(3, "0"));
  const continuity = document.getElementById("continuity-output")?.textContent?.trim() || "";
  const wordMin = document.getElementById("constraint-word-min")?.value || "";
  const wordMax = document.getElementById("constraint-word-max")?.value || "";
  const logs = workbenchLogs.slice(0, 3);
  const groups = [
    ["本章大纲", "<p>当前 Web 接口未提供可按章节读取的大纲内容。</p>"],
    ["角色状态", "<p>当前 Web 接口未提供本章涉及角色或角色状态。</p>"],
    ["待回收伏笔", foreshadows.length ? "<ul>" + foreshadows.map((item) => "<li>" + escapeHtml(item.content || item.id || "伏笔") + "</li>").join("") + "</ul>" : "<p>暂无本章可映射伏笔。</p>"],
    ["连贯性检查", "<p>" + escapeHtml(continuity && !continuity.includes("请选择") ? continuity : "尚未运行连贯性检查。") + "</p>"],
    ["AI 写作约束", "<p>" + (wordMin || wordMax ? "单章字数：" + escapeHtml(wordMin || "—") + "–" + escapeHtml(wordMax || "—") : "暂无字数约束数据。") + "</p>"],
    ["当前版本", "<p>" + escapeHtml(versionLabel(currentManualSource)) + "</p>"],
    ["运行日志", logs.length ? "<ul>" + logs.map((item) => "<li>" + escapeHtml(item.message) + "</li>").join("") + "</ul>" : "<p>暂无运行日志。</p>"],
  ];
  target.innerHTML = groups.map((group, index) => "<details class=\"chapter-editor-context-group\" " + (index === 2 || index === 5 ? "open" : "") + "><summary>" + group[0] + "</summary>" + group[1] + "</details>").join("");
}

document.addEventListener("input", (event) => {
  if (event.target?.id === "manualEditor") markChapterEditorDirty();
});
document.addEventListener("scroll", (event) => {
  if (event.target?.id === "manualEditor") updateChapterEditorStats();
}, true);
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveManualVersion();
  }
  if (event.key === "Escape" && chapterEditorPreviewMode) toggleChapterEditorPreview();
});
window.addEventListener("beforeunload", (event) => {
  if (!chapterEditorDirty) return;
  event.preventDefault();
  event.returnValue = "";
});

;Object.assign(window,{toggleChapterEditorPreview,saveManualVersion,clearManualEditor,loadManualSource,openChapterEditorVersions,chapterEditorBackToList});

document.addEventListener("click",(event)=>{if(event.target.closest("[data-chapter-preview]")){toggleChapterEditorPreview();}if(event.target.closest("[data-chapter-save]")){saveManualVersion();}});



// Stage 5 story blueprint workspace: structure-aware editing over the existing project-assets contract.
let blueprintDraft = null;
let blueprintSelectedPath = [];
let blueprintRawDirty = false;
let blueprintAssetExists = false;
let blueprintSaveInFlight = false;

const blueprintLabelMap = {
  project_meta: "基础信息", basic_settings: "基础设定", narrative_settings: "叙事设定",
  world_and_plot: "世界与剧情", core_rules: "核心规则", character_bible: "角色",
  volume_plan: "卷纲", chapter_plan: "章节计划", generation_rules: "生成规则",
  story_phases: "故事阶段", initial_foreshadow_pool: "初始伏笔池",
  rolling_generation_policy: "滚动生成策略", world_direction: "世界方向",
  title: "标题", blueprint_version: "蓝图版本", genre: "类型", length_type: "篇幅",
  target_word_count: "目标字数", core_premise: "核心前提", main_arc: "故事主线",
  core_conflict: "核心冲突", ending_direction: "结局方向"
};

const stage5RenderProjectAsset = renderProjectAsset;
renderProjectAsset = function renderProjectAssetWithBlueprint(assetId) {
  stage5RenderProjectAsset(assetId);
  const panel = document.getElementById("project-assets-panel");
  const workspace = document.getElementById("blueprint-workspace");
  const asset = projectAssets.find((item) => item.id === assetId);
  if (!panel || !workspace) return;
  const isBlueprint = assetId === "story_blueprint";
  panel.classList.toggle("is-blueprint", isBlueprint);
  workspace.classList.toggle("hidden", !isBlueprint);
  if (isBlueprint) renderBlueprintWorkspace(asset || null);
};

function renderBlueprintWorkspace(asset) {
  blueprintAssetExists = Boolean(asset && asset.exists);
  if (!asset || !asset.exists) {
    blueprintDraft = null;
    blueprintSelectedPath = [];
    setBlueprintState("error", "story_blueprint.json 缺失");
    renderBlueprintDirectory();
    setBlueprintNotice("未找到 story_blueprint.json。请通过现有项目初始化/蓝图生成流程修复后重新读取；页面不会自动创建空文件。", "error");
    setBlueprintContentEmpty("蓝图文件缺失，无法安全编辑。");
    renderBlueprintInspector();
    return;
  }
  try {
    const parsed = JSON.parse(asset.content || "");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("蓝图根节点必须是 JSON 对象。");
    blueprintDraft = parsed;
    blueprintSelectedPath = blueprintSelectedPath.length && Object.prototype.hasOwnProperty.call(parsed, blueprintSelectedPath[0]) ? blueprintSelectedPath : [Object.keys(parsed)[0] || ""];
    blueprintRawDirty = false;
    const raw = document.getElementById("blueprint-raw-editor");
    if (raw) raw.value = JSON.stringify(parsed, null, 2);
    setBlueprintState("saved", "已读取");
    setBlueprintNotice("");
    renderBlueprintDirectory();
    renderBlueprintSelectedNode();
    renderBlueprintInspector();
  } catch (error) {
    blueprintDraft = null;
    blueprintSelectedPath = [];
    setBlueprintState("error", "JSON 解析失败");
    renderBlueprintDirectory();
    setBlueprintNotice("story_blueprint.json 无法解析：" + (error.message || "未知 JSON 错误") + "。原文件未被覆盖。", "error");
    setBlueprintContentEmpty("修复 JSON 语法后重新读取。");
    renderBlueprintInspector();
  }
}

function renderBlueprintDirectory() {
  const target = document.getElementById("blueprint-directory");
  if (!target) return;
  if (!blueprintDraft) {
    target.innerHTML = "<div class=\"empty-state\">暂无可用目录</div>";
    return;
  }
  target.innerHTML = Object.keys(blueprintDraft).map((key) => {
    const value = blueprintDraft[key];
    const active = blueprintSelectedPath[0] === key;
    const empty = blueprintValueIsEmpty(value);
    const count = blueprintNodeCount(value);
    return "<button class=\"blueprint-directory-item " + (active ? "is-active " : "") + (empty ? "is-empty" : "") + "\" type=\"button\" data-blueprint-directory=\"" + blueprintPathToken([key]) + "\"><span>" + escapeHtml(blueprintLabel(key)) + "</span><span class=\"directory-count\">" + (empty ? "缺失" : String(count)) + "</span></button>";
  }).join("");
}

function renderBlueprintSelectedNode() {
  const header = document.getElementById("blueprint-content-header");
  const target = document.getElementById("blueprint-content-editor");
  if (!header || !target || !blueprintDraft) return;
  const key = blueprintSelectedPath[0];
  const value = blueprintValueAtPath(blueprintDraft, blueprintSelectedPath);
  header.innerHTML = "<span class=\"eyebrow\">" + escapeHtml(key || "Section") + "</span><h3>" + escapeHtml(blueprintLabel(key || "蓝图节点")) + "</h3>";
  target.innerHTML = renderBlueprintNode(value, blueprintSelectedPath, 0);
}

function renderBlueprintNode(value, path, depth) {
  if (value === null || typeof value !== "object") return renderBlueprintScalar(value, path);
  if (Array.isArray(value)) {
    if (!value.length) return "<div class=\"empty-state\">当前列表为空。</div>";
    return "<ol class=\"blueprint-list\">" + value.map((item, index) => "<li class=\"blueprint-list-item\"><span class=\"blueprint-list-index\">" + String(index + 1).padStart(2, "0") + "</span><div>" + renderBlueprintNode(item, path.concat(index), depth + 1) + "</div></li>").join("") + "</ol>";
  }
  const entries = Object.keys(value);
  if (!entries.length) return "<div class=\"empty-state\">当前对象为空。</div>";
  return entries.map((key) => {
    const child = value[key];
    const childPath = path.concat(key);
    if (child && typeof child === "object") {
      return "<details class=\"blueprint-object\" " + (depth < 1 ? "open" : "") + "><summary class=\"blueprint-object-summary\">" + escapeHtml(blueprintLabel(key)) + "<small>" + escapeHtml(key) + "</small></summary><div class=\"blueprint-object-body\">" + renderBlueprintNode(child, childPath, depth + 1) + "</div></details>";
    }
    return renderBlueprintScalar(child, childPath, key);
  }).join("");
}

function renderBlueprintScalar(value, path, explicitKey = "") {
  const key = explicitKey || String(path[path.length - 1] || "");
  const label = blueprintLabel(key);
  const token = blueprintPathToken(path);
  const stringValue = value === null || value === undefined ? "" : String(value);
  const isLong = typeof value === "string" && (value.length > 110 || value.includes("\n"));
  let control = "";
  if (typeof value === "boolean") control = "<input type=\"checkbox\" data-blueprint-input=\"" + token + "\" " + (value ? "checked" : "") + ">";
  else if (typeof value === "number") control = "<input type=\"number\" data-blueprint-input=\"" + token + "\" value=\"" + escapeHtml(stringValue) + "\">";
  else if (isLong) control = "<textarea data-blueprint-input=\"" + token + "\">" + escapeHtml(stringValue) + "</textarea>";
  else control = "<input type=\"text\" data-blueprint-input=\"" + token + "\" value=\"" + escapeHtml(stringValue) + "\">";
  return "<div class=\"blueprint-field\"><label class=\"blueprint-field-label\">" + escapeHtml(label) + "<span class=\"blueprint-field-key\">" + escapeHtml(key) + "</span></label><div>" + control + "</div></div>";
}

function blueprintValueAtPath(source, path) {
  return path.reduce((value, part) => value == null ? undefined : value[part], source);
}

function blueprintSetAtPath(path, nextValue) {
  if (!blueprintDraft || !path.length) return;
  let target = blueprintDraft;
  for (let index = 0; index < path.length - 1; index += 1) target = target[path[index]];
  target[path[path.length - 1]] = nextValue;
}

function blueprintPathToken(path) {
  return encodeURIComponent(JSON.stringify(path));
}

function blueprintPathFromToken(token) {
  return JSON.parse(decodeURIComponent(token || "[]"));
}

function blueprintLabel(key) {
  const text = String(key || "");
  return blueprintLabelMap[text] || text.replace(/_/g, " ");
}

function blueprintValueIsEmpty(value) {
  if (value === null || value === undefined || value === "") return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value).length === 0;
  return false;
}

function blueprintNodeCount(value) {
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === "object") return Object.keys(value).length;
  return blueprintValueIsEmpty(value) ? 0 : 1;
}

function setBlueprintState(state, label) {
  const target = document.getElementById("blueprint-save-state");
  if (!target) return;
  target.className = "blueprint-save-state is-" + state;
  target.textContent = label;
}

function setBlueprintNotice(message, type = "") {
  const target = document.getElementById("blueprint-notice");
  if (!target) return;
  target.textContent = message || "";
  target.classList.toggle("hidden", !message);
  target.classList.toggle("is-error", type === "error");
}

function setBlueprintContentEmpty(message) {
  const header = document.getElementById("blueprint-content-header");
  const target = document.getElementById("blueprint-content-editor");
  if (header) header.innerHTML = "<span class=\"eyebrow\">Blueprint</span><h3>故事蓝图</h3>";
  if (target) target.innerHTML = "<div class=\"empty-state\">" + escapeHtml(message) + "</div>";
}

function renderBlueprintInspector() {
  const target = document.getElementById("blueprint-inspector-content");
  if (!target) return;
  if (!blueprintDraft) {
    target.innerHTML = "<div class=\"empty-state\">无可检查的蓝图数据。</div>";
    return;
  }
  const selectedKey = blueprintSelectedPath[0] || "";
  const emptyPaths = collectBlueprintEmptyPaths(blueprintDraft).slice(0, 8);
  const totals = blueprintCompleteness(blueprintDraft);
  const foreshadows = ((latestWorkbenchStatus || {}).foreshadows || {}).open_items || [];
  const chapterPlan = Array.isArray(blueprintDraft.chapter_plan) ? blueprintDraft.chapter_plan : [];
  const characterData = blueprintDraft.character_bible || {};
  const sections = [
    ["完整性", "<div class=\"blueprint-completeness\"><span>" + totals.filled + "/" + totals.total + "</span><div class=\"blueprint-completeness-bar\"><span style=\"width:" + totals.percent + "%\"></span></div></div><p>空值、空列表和空对象以当前文件内容计算。</p>"],
    ["缺失字段", emptyPaths.length ? "<ul>" + emptyPaths.map((path) => "<li>" + escapeHtml(path) + "</li>").join("") + "</ul>" : "<p>未发现空字段。</p>"],
    ["关联章节", selectedKey === "chapter_plan" ? "<p>当前章节计划：" + chapterPlan.length + " 项。</p>" : "<p>当前节点没有可直接计算的章节关联。</p>"],
    ["关联角色", selectedKey === "character_bible" ? "<p>主角节点：" + (characterData.protagonist && Object.keys(characterData.protagonist).length ? "已填写" : "暂无数据") + "；关键角色：" + (Array.isArray(characterData.key_characters) ? characterData.key_characters.length : 0) + " 项。</p>" : "<p>当前节点没有可直接计算的角色关联。</p>"],
    ["相关伏笔", foreshadows.length ? "<p>项目当前开放伏笔：" + foreshadows.length + " 项；当前蓝图未提供字段级引用映射。</p>" : "<p>暂无开放伏笔数据。</p>"],
    ["最近修改", "<p>当前资产接口未提供文件修改时间。</p>"],
  ];
  target.innerHTML = sections.map((section) => "<section class=\"blueprint-inspector-section\"><h4>" + section[0] + "</h4>" + section[1] + "</section>").join("");
}

function collectBlueprintEmptyPaths(value, path = [], result = []) {
  if (blueprintValueIsEmpty(value)) {
    if (path.length) result.push(path.join("."));
    return result;
  }
  if (Array.isArray(value)) value.forEach((item, index) => collectBlueprintEmptyPaths(item, path.concat(index), result));
  else if (value && typeof value === "object") Object.keys(value).forEach((key) => collectBlueprintEmptyPaths(value[key], path.concat(key), result));
  return result;
}

function blueprintCompleteness(value) {
  const empty = collectBlueprintEmptyPaths(value);
  let total = 0;
  const countLeaves = (item) => {
    if (item === null || typeof item !== "object") { total += 1; return; }
    if (Array.isArray(item)) { if (!item.length) total += 1; else item.forEach(countLeaves); return; }
    const keys = Object.keys(item); if (!keys.length) total += 1; else keys.forEach((key) => countLeaves(item[key]));
  };
  countLeaves(value);
  const filled = Math.max(0, total - empty.length);
  return { total, filled, percent: total ? Math.round((filled / total) * 100) : 0 };
}

async function saveBlueprintAsset() {
  if (!blueprintAssetExists || !blueprintDraft || blueprintSaveInFlight) return;
  const raw = document.getElementById("blueprint-raw-editor");
  let payload = blueprintDraft;
  if (blueprintRawDirty && raw) {
    try {
      payload = JSON.parse(raw.value || "");
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("蓝图根节点必须是对象。");
    } catch (error) {
      setBlueprintState("error", "JSON 格式错误");
      setBlueprintNotice("原始 JSON 无法保存：" + (error.message || "语法错误") + "。原文件未被覆盖。", "error");
      return;
    }
  }
  blueprintSaveInFlight = true;
  setBlueprintState("saving", "保存中");
  try {
    const content = JSON.stringify(payload, null, 2);
    const result = await apiPost("/api/project-assets/story_blueprint", { content });
    logApiResult("故事蓝图", result);
    if (!result.ok || !result.result?.asset) {
      setBlueprintState("error", (result.errors && result.errors[0]) || result.message || "保存失败");
      setBlueprintNotice((result.errors && result.errors[0]) || result.message || "保存失败。", "error");
      return;
    }
    const savedAsset = result.result.asset;
    const index = projectAssets.findIndex((item) => item.id === "story_blueprint");
    if (index >= 0) projectAssets[index] = savedAsset;
    blueprintRawDirty = false;
    blueprintDraft = JSON.parse(savedAsset.content);
    const rawEditor = document.getElementById("blueprint-raw-editor");
    if (rawEditor) rawEditor.value = JSON.stringify(blueprintDraft, null, 2);
    setBlueprintState("saved", "已保存");
    setBlueprintNotice("");
    renderBlueprintDirectory();
    renderBlueprintSelectedNode();
    renderBlueprintInspector();
  } catch (error) {
    setBlueprintState("error", error.message || "保存失败");
    setBlueprintNotice("保存失败：" + (error.message || "API 请求失败") + "。请检查文件权限后重试。", "error");
  } finally {
    blueprintSaveInFlight = false;
  }
}

document.addEventListener("click", (event) => {
  const directory = event.target.closest("[data-blueprint-directory]");
  if (directory) {
    blueprintSelectedPath = blueprintPathFromToken(directory.dataset.blueprintDirectory);
    renderBlueprintDirectory();
    renderBlueprintSelectedNode();
    renderBlueprintInspector();
    return;
  }
  if (event.target.closest("[data-blueprint-save]")) { saveBlueprintAsset(); return; }
  if (event.target.closest("[data-blueprint-reload]")) { loadProjectAssets(); return; }
  if (event.target.closest("[data-project-asset-save]")) { saveProjectAsset(); }
});

document.addEventListener("input", (event) => {
  const field = event.target.closest("[data-blueprint-input]");
  if (field && blueprintDraft) {
    const path = blueprintPathFromToken(field.dataset.blueprintInput);
    const current = blueprintValueAtPath(blueprintDraft, path);
    const next = typeof current === "boolean" ? field.checked : typeof current === "number" ? Number(field.value) : field.value;
    blueprintSetAtPath(path, Number.isNaN(next) ? current : next);
    blueprintRawDirty = false;
    const raw = document.getElementById("blueprint-raw-editor");
    if (raw) raw.value = JSON.stringify(blueprintDraft, null, 2);
    setBlueprintState("dirty", "有未保存修改");
    renderBlueprintInspector();
    return;
  }
  if (event.target?.id === "blueprint-raw-editor") {
    blueprintRawDirty = true;
    setBlueprintState("dirty", "原始 JSON 已修改");
  }
});
