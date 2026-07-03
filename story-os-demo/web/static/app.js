let currentVersion = null;
let currentText = "";
let latestDraft = null;
let latestEdited = null;
let latestManual = null;
let selectedVersion = null;
let currentManualSource = null;

async function apiGet(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`GET ${url} failed: ${response.status}`);
  return response.json();
}

async function apiPost(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`POST ${url} failed: ${response.status}`);
  return response.json();
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
    ["向量库", memory.vector_memory_enabled ? "已启用" : "未启用"],
  ];
  document.getElementById("status-metrics").innerHTML = metrics.map(([label, value]) => `<div class="metric"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(String(value))}</span></div>`).join("");
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

function renderVersions(targetId, items) {
  const target = document.getElementById(targetId);
  if (!items.length) {
    target.innerHTML = '<div class="empty-state">暂无版本</div>';
    return;
  }
  target.innerHTML = items.map((item) => {
    const selected = selectedVersion && selectedVersion.source_type === item.source_type && Number(selectedVersion.version) === Number(item.version);
    return `<article class="version-card ${selected ? "selected" : ""}"><div class="version-title"><strong>${escapeHtml(versionLabel(item))}</strong>${selected ? '<span class="status-token">Selected</span>' : ""}</div><div class="version-meta">${escapeHtml(String(item.actual_word_count || 0))} 字 · ${escapeHtml(item.mode || "unknown")} · score=${escapeHtml(formatScore(item.quality_score))}</div><code>${escapeHtml(item.json_path || "")}</code><div class="card-actions"><button class="btn btn-secondary" type="button" onclick="loadVersionContent('${escapeJs(item.source_type || "")}', ${Number(item.version || 0)})">查看</button><button class="btn btn-primary" type="button" onclick="selectVersion('${escapeJs(item.source_type || "")}', ${Number(item.version || 0)})">选择</button><button class="btn btn-secondary" type="button" onclick="compareWithOpposite('${escapeJs(item.source_type || "")}', ${Number(item.version || 0)})">对比</button></div></article>`;
  }).join("");
}

async function loadVersionContent(sourceType, version) {
  const data = await apiGet(`/api/versions/content?source_type=${encodeURIComponent(sourceType)}&version=${encodeURIComponent(version)}`);
  if (!data.ok) return logApiResult("查看版本", data);
  renderVersionContent(data.result);
  await loadQualityReport(sourceType, version);
}
async function selectVersion(sourceType, version) { await runAction("选择版本", () => apiPost("/api/versions/select", { source_type: sourceType, version })); await refreshAll(); }
async function selectCurrentVersion() { if (!currentVersion) return logMessage("请先查看一个版本。", "warning"); await selectVersion(currentVersion.source_type, currentVersion.version); }
async function compareWithOpposite(sourceType, version) { const other = sourceType === "draft" ? (latestEdited || latestManual) : (latestManual || latestEdited || latestDraft); if (!other || (other.source_type === sourceType && Number(other.version) === Number(version))) return logMessage("缺少可对比的另一类版本。", "warning"); return loadVersionDiff(sourceType, version, other.source_type, other.version); }
async function loadVersionDiff(leftType, leftVersion, rightType, rightVersion) { const data = await apiGet(`/api/versions/diff?left_type=${leftType}&left_version=${leftVersion}&right_type=${rightType}&right_version=${rightVersion}`); if (!data.ok) return logApiResult("Diff 对比", data); renderDiff(data.result); }
async function loadQualityReport(sourceType, version) { const data = await apiGet(`/api/quality-report?source_type=${encodeURIComponent(sourceType)}&version=${encodeURIComponent(version)}`); if (!data.ok) return logApiResult("质量报告", data); renderQualityReport(data.result); }

function renderVersionContent(data) {
  currentVersion = { source_type: data.source_type, version: data.version };
  currentText = data.text || "";
  const generation = data.generation || {};
  const quality = data.quality || {};
  document.getElementById("preview-meta").classList.remove("empty-state");
  document.getElementById("preview-meta").innerHTML = [["标题", data.version_label || ""], ["字数", data.word_count || 0], ["生成模式", generation.mode || "unknown"], ["Fallback", generation.fallback_used ? "true" : "false"], ["质量评分", formatScore(quality.score)], ["风险等级", quality.risk_level || "unknown"], ["源文件", data.json_path || ""], ["质量报告", quality.report_path || "未生成"]].map(([label, value]) => `<div class="meta-item"><b>${escapeHtml(label)}</b><span>${escapeHtml(String(value))}</span></div>`).join("");
  document.getElementById("text-preview").textContent = currentText || "该版本暂无正文内容。";
}
function renderDiff(data) { const summary = data.summary || {}; document.getElementById("diff-summary").classList.remove("empty-state"); document.getElementById("diff-summary").innerHTML = [["对比", `${versionLabel(data.left)} -> ${versionLabel(data.right)}`], ["左侧字数", summary.left_chars || 0], ["右侧字数", summary.right_chars || 0], ["新增", summary.added_count || 0], ["删除", summary.removed_count || 0], ["变化比例", `${Math.round((summary.changed_ratio || 0) * 100)}%`]].map(([label, value]) => `<div class="meta-item"><b>${escapeHtml(label)}</b><span>${escapeHtml(String(value))}</span></div>`).join(""); document.getElementById("diff-output").innerHTML = data.diff_html || ""; }
function renderQualityReport(data) { if (!data.exists) { document.getElementById("quality-output").classList.add("empty-state"); document.getElementById("quality-output").innerHTML = '<p>当前版本尚未生成质量报告。</p><button class="btn btn-secondary" type="button" onclick="qualityCheck()">生成质量评估</button>'; return; } document.getElementById("quality-output").classList.remove("empty-state"); const risk = riskLevel(data.overall_score); const scores = Object.entries(data.scores || {}).map(([key, value]) => `<li>${escapeHtml(key)}：${escapeHtml(formatScore(value))}</li>`).join("") || "<li>暂无</li>"; const flags = (data.flags || []).map((item, index) => `<li>${index + 1}. [${escapeHtml(item.severity || "")}][${escapeHtml(item.type || "")}] ${escapeHtml(item.message || "")}</li>`).join("") || "<li>暂无</li>"; const suggestions = (data.suggestions || []).map((item) => `<li>${escapeHtml(String(item))}</li>`).join("") || "<li>暂无</li>"; document.getElementById("quality-output").innerHTML = `<div class="quality-score risk-${risk}">总分：${escapeHtml(formatScore(data.overall_score))} · 风险：${risk}</div><h3>分项评分</h3><ul>${scores}</ul><h3>问题</h3><ol>${flags}</ol><h3>建议</h3><ul>${suggestions}</ul>`; }


function populateManualSourceOptions(versions) {
  const select = document.getElementById("manual-source-select");
  if (!select) return;
  const items = [...(versions.drafts || []), ...(versions.edited || []), ...(versions.manual || [])];
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
  await runAction("保存 manual 版本", async () => {
    const result = await apiPost("/api/manual/save", {
      chapter_id: currentManualSource.chapter_id,
      source_type: currentManualSource.source_type,
      source_version: currentManualSource.version,
      text,
    });
    if (result.ok && result.result) {
      logMessage(`${result.result.version_label || "manual"} 已保存并选中。`, "success");
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
async function qualityCheck() { await runAction("质量评估", () => apiPost("/api/quality-check")); await refreshAll(); if (currentVersion) await loadQualityReport(currentVersion.source_type, currentVersion.version); }
async function approveReview(force = false) { const result = await apiPost("/api/review/approve", { force }); if (result.need_confirm && !force) { const confirmed = window.confirm(result.message || "当前版本质量评分较低，是否仍然提交？"); if (confirmed) return approveReview(true); } logApiResult("审核通过", result); await refreshAll(); }
async function rejectReview() { await runAction("拒绝审核", () => apiPost("/api/review/reject")); await refreshAll(); }
async function laterReview() { await runAction("稍后审核", () => apiPost("/api/review/later")); await refreshAll(); }
async function syncObsidian() { await runAction("同步 Obsidian", () => apiPost("/api/sync-obsidian")); await refreshAll(); }
async function indexVault() { await runAction("更新向量库", () => apiPost("/api/index-vault")); await refreshAll(); }
async function loadTodos() { const todos = await apiGet("/api/todos"); const target = document.getElementById("todo-list"); if (!todos.length) { target.innerHTML = '<div class="empty-state">暂无 open todo</div>'; return; } target.innerHTML = todos.map((todo) => `<article class="todo-card"><strong>#${Number(todo.id || 0)} ${escapeHtml(todo.title || "")}</strong><div class="version-meta">${escapeHtml(todo.priority || "")} · ${escapeHtml(todo.type || "")} · 第 ${escapeHtml(String(todo.chapter_id || "-"))} 章</div><div class="todo-actions"><button class="btn btn-secondary" type="button" onclick="todoAction(${Number(todo.id || 0)}, 'done')">完成</button><button class="btn btn-secondary" type="button" onclick="todoAction(${Number(todo.id || 0)}, 'reopen')">重开</button><button class="btn btn-danger" type="button" onclick="todoAction(${Number(todo.id || 0)}, 'cancel')">取消</button></div></article>`).join(""); }
async function addTodo() { const chapterValue = document.getElementById("todo-chapter").value; const body = { title: document.getElementById("todo-title").value, type: document.getElementById("todo-type").value, priority: document.getElementById("todo-priority").value, chapter_id: chapterValue ? Number(chapterValue) : null }; await runAction("添加 Todo", () => apiPost("/api/todos", body)); document.getElementById("todo-title").value = ""; await refreshAll(); }
async function todoAction(todoId, action) { await runAction("更新 Todo", () => apiPost(`/api/todos/${todoId}/${action}`)); await refreshAll(); }
async function askStory() { const body = { mode: document.getElementById("ask-mode").value, question: document.getElementById("ask-question").value, use_vector: document.getElementById("ask-vector").checked, use_llm: document.getElementById("ask-llm").checked }; const result = await apiPost("/api/ask", body); logApiResult("Ask Story", result); document.getElementById("ask-answer").textContent = JSON.stringify((result.result || {}).qa || {}, null, 2); }
async function refreshAll() { await runWithBusy(async () => { await refreshStatus(); await loadVersions(); await loadTodos(); }, "状态已刷新。"); }
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

initializeApp();

async function runMemoryHealth(full=false){const t=document.getElementById("memoryHealthOutput");if(t)t.textContent="Running memory health check...";try{const d=await apiGet("/api/memory-health"+(full?"?full=true":""));if(!d.ok){if(t)t.textContent="Memory health check failed.";logApiResult("Memory Health",d);return;}renderMemoryHealth(d.result||{});logApiResult("Memory Health",d);await refreshStatus();}catch(e){if(t)t.textContent="Memory health check failed.";logMessage("Memory health check failed.","error");}}
function renderMemoryHealth(report){const t=document.getElementById("memoryHealthOutput");if(!t)return;const s=report.summary||{},issues=Array.isArray(report.issues)?report.issues:[],suggestions=Array.isArray(report.suggestions)?report.suggestions:[];const statusText=report.overall_status==="ok"?"Memory state is healthy.":report.overall_status==="warning"?"Some issues need attention, but work can usually continue.":"Serious consistency issues exist; review them before generating chapters.";t.classList.remove("empty-state");t.innerHTML="<div class=\"health-summary\"><div class=\"health-status "+healthLevelClass(report.overall_status)+"\">"+escapeHtml(healthStatusLabel(report.overall_status))+"</div><div class=\"health-score\">Score: "+escapeHtml(formatScore(report.overall_score))+"</div><div>Errors: "+Number(s.errors||0)+"</div><div>Warnings: "+Number(s.warnings||0)+"</div><div>Infos: "+Number(s.infos||0)+"</div></div><p class=\"health-suggestion\">"+escapeHtml(statusText)+"</p><h3>Issues</h3><div class=\"health-issue-list\">"+(issues.length?issues.map(renderHealthIssue).join(""):"<div class=\"empty-state\">No issues.</div>")+"</div><h3>Suggestions</h3><ul class=\"health-suggestion-list\">"+(suggestions.length?suggestions.map(x=>"<li>"+escapeHtml(String(x))+"</li>").join(""):"<li>Keep the rolling chapter workflow.</li>")+"</ul>";}
function renderHealthIssue(issue){return "<article class=\"health-issue "+healthLevelClass(issue.level||"info")+"\"><strong>"+escapeHtml(issue.id||"issue")+"</strong><span class=\"health-category\">"+escapeHtml(issue.category||"")+"</span><p>"+escapeHtml(issue.message||"")+"</p><code class=\"health-path\">"+escapeHtml(issue.path||"")+"</code><p class=\"health-suggestion\">"+escapeHtml(issue.suggested_action||"")+"</p></article>";}
function healthStatusLabel(status){if(status==="ok")return "OK";if(status==="warning")return "Warning";if(status==="error")return "Error";return "Unknown";}
function healthLevelClass(level){if(level==="error")return "health-status-error health-issue-error";if(level==="warning")return "health-status-warning health-issue-warning";if(level==="ok")return "health-status-ok";return "health-status-info health-issue-info";}
