let narrativeEvaluationRequest = 0;
let narrativeImprovementReport = null;
let narrativeAdoptionPreview = null;
let narrativePartialAdoptionPreview = null;

function evaluationEscape(value) { return typeof escapeHtml === "function" ? escapeHtml(String(value ?? "")) : String(value ?? ""); }
function evaluationScore(value) { return value === null || value === undefined ? "证据不足" : `${Math.round(Number(value))}`; }
function evaluationGateLabel(value) { return ({pass:"可通过",attention:"需要复核",blocked:"阻塞",invalid:"数据异常"})[value] || "需要复核"; }

async function loadNarrativeEvaluationCenter() {
  const ticket = ++narrativeEvaluationRequest;
  const result = await Promise.all([apiGet("/api/evaluations/overview"), apiGet("/api/evaluations?limit=12")]);
  if (ticket !== narrativeEvaluationRequest) return;
  const overview = result[0].result || {}, history = (result[1].result || {}).evaluations || [];
  renderNarrativeEvaluation(overview.latest_report, overview);
  renderEvaluationPlanning(overview.planning_gate_summary || {});
  renderEvaluationHistory(history);
}

async function generateNarrativeEvaluation() {
  const result = await apiPost("/api/evaluations", { target_type: "chapter_draft", chapter_number: currentVersion?.chapter_id || undefined, source_type: currentVersion?.source_type || undefined, source_version: currentVersion?.version || undefined, profile_id: "chapter-default-v1", operation_id: "" });
  if (!result.ok) { if (typeof logApiResult === "function") logApiResult("叙事评估", result); return; }
  renderNarrativeEvaluation((result.result || {}).evaluation || {}, {});
  await loadNarrativeEvaluationCenter();
}

function renderNarrativeEvaluation(report, overview) {
  narrativeImprovementReport = report || null;
  const improvementButton = document.getElementById("narrative-improvement-open");
  if (improvementButton) improvementButton.disabled = !report || report.status !== "current" || !improvementEligibleIssues(report).length;
  const target = document.getElementById("evaluation-chapter-result"); if (!target) return;
  if (!report) { target.innerHTML = '<div class="empty-state">当前章节尚未生成统一报告。该操作只聚合既有证据，不运行检查器或模型。</div>'; return; }
  const dimensions = Array.isArray(report.dimensions) ? report.dimensions : [];
  const issues = Array.isArray(report.priority_issues) ? report.priority_issues : [];
  const gate = report.gate_status || "attention";
  target.innerHTML = `<div class="evaluation-summary"><article class="evaluation-gate ${evaluationEscape(gate)}"><span>硬性状态</span><strong>${evaluationEscape(evaluationGateLabel(gate))}</strong><p>${evaluationEscape((report.gate_reasons || []).join("；") || "未发现阻断性问题。")}</p></article><article class="evaluation-stat"><span>综合评分</span><strong>${evaluationEscape(evaluationScore(report.overall_score))}</strong></article><article class="evaluation-stat"><span>报告置信度</span><strong>${evaluationEscape(Math.round(Number(report.confidence || 0) * 100))}%</strong></article><article class="evaluation-stat"><span>报告状态</span><strong>${evaluationEscape(report.status || (overview.latest_report_stale ? "stale" : "current"))}</strong></article></div><div class="evaluation-table-wrap"><table class="evaluation-table"><thead><tr><th>维度</th><th>分数</th><th>权重</th><th>置信度</th><th>主要问题</th><th>建议</th></tr></thead><tbody>${dimensions.map(d => `<tr><td>${evaluationEscape(d.display_name)}</td><td>${evaluationEscape(evaluationScore(d.score))}</td><td>${evaluationEscape(Math.round(Number(d.weight || 0) * 100))}%</td><td>${evaluationEscape(Math.round(Number(d.confidence || 0) * 100))}%</td><td>${renderEvaluationIssueList(d.issues || [])}</td><td>${evaluationEscape((d.suggestions || []).join("；") || "—")}</td></tr>`).join("")}</tbody></table></div><section><h3>优先问题</h3>${issues.length ? `<ol class="evaluation-issues">${issues.map(item => `<li><b>${evaluationEscape(item.severity)}</b> · ${evaluationEscape(item.title)} <span class="evaluation-tag">${evaluationEscape(item.fixability)}</span></li>`).join("")}</ol>` : "<p>暂无优先问题。</p>"}</section>`;
}
function improvementEligibleIssues(report) { return (report?.priority_issues || []).filter(item => item.fixability === "auto_low_risk" && ["high", "medium", "low"].includes(item.severity)); }
function openNarrativeImprovement() {
  const report = narrativeImprovementReport, eligible = improvementEligibleIssues(report);
  if (!report || report.status !== "current" || !eligible.length) { alert("当前报告没有可安全自动处理的低风险问题。请先生成当前统一报告，或由作者处理需要决定的问题。"); return; }
  let dialog = document.getElementById("narrative-improvement-dialog");
  if (!dialog) { dialog = document.createElement("dialog"); dialog.id = "narrative-improvement-dialog"; dialog.className = "dialog confirm-dialog"; document.body.appendChild(dialog); }
  const all = report.priority_issues || [];
  dialog.innerHTML = `<form method="dialog" class="dialog-surface"><div class="dialog-header"><div><span class="eyebrow">Restricted candidate</span><h2>刷新质量</h2></div><button class="icon-button" value="cancel" aria-label="关闭">×</button></div><div class="dialog-body"><p>仅会生成局部候选与对比，不会覆盖、提交或采用正文。</p><fieldset><legend>可选低风险问题</legend>${eligible.map(item => `<label><input type="checkbox" name="issue" value="${evaluationEscape(item.issue_id)}" checked> ${evaluationEscape(item.title)} (${evaluationEscape(item.severity)})</label>`).join("<br>")}</fieldset><fieldset><legend>需要作者决定（不可选）</legend>${all.filter(item => !eligible.includes(item)).map(item => `<p><input type="checkbox" disabled> ${evaluationEscape(item.title)}：需要作者决定</p>`).join("") || "<p>无</p>"}</fieldset><label>预算 <select name="budget"><option value="conservative">保守</option><option value="standard" selected>标准</option><option value="enhanced">增强</option></select></label><p>标准预算：最多 8 段、12% 变更、10 个补丁；禁止改标题、结尾、事实、新命名实体和世界设定。</p><div id="narrative-improvement-result"></div></div><div class="dialog-actions"><button class="btn btn-secondary" value="cancel">取消</button><button class="btn btn-primary" type="button" onclick="confirmNarrativeImprovement()">确认生成候选</button></div></form>`;
  dialog.showModal();
}
async function confirmNarrativeImprovement() {
  const dialog = document.getElementById("narrative-improvement-dialog"), issues = [...dialog.querySelectorAll('input[name="issue"]:checked')].map(item => item.value), budget = dialog.querySelector('select[name="budget"]').value;
  let result; try { result = await apiPost(`/api/evaluations/${encodeURIComponent(narrativeImprovementReport.evaluation_id)}/improvements`, {issue_ids: issues, budget, operation_id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}`}); } catch (error) { document.getElementById("narrative-improvement-result").textContent = "任务未创建：" + error.message; return; }
  const target = document.getElementById("narrative-improvement-result");
  if (!result.ok) { target.textContent = "任务未创建：" + ((result.errors || []).join(", ") || "请求失败"); return; }
  const data = result.result || {}, improvement = data.improvement || {}; target.innerHTML = `<p>候选任务：${evaluationEscape(data.job?.job_id || "已回放")}</p><p>状态：${evaluationEscape(improvement.state || "planning")}；完成后仅可查看候选、差异与建议。</p>`;
  if (data.job?.job_id) pollNarrativeImprovement(improvement.improvement_id, data.job.job_id, target);
}
async function pollNarrativeImprovement(improvementId, jobId, target) {
  const timer = setInterval(async () => { try { const job = await apiGet(`/api/jobs/${encodeURIComponent(jobId)}`); const detail = await apiGet(`/api/evaluations/improvements/${encodeURIComponent(improvementId)}`); const item = detail.result?.improvement; const status = job.result?.job?.status || job.result?.status; if (item) { target.innerHTML = `<p>步骤：${evaluationEscape(job.result?.job?.current_step || job.result?.current_step || "处理中")}</p><p>候选状态：${evaluationEscape(item.state)}</p>${item.comparison ? `<p>建议：${evaluationEscape(item.comparison.recommendation)}（不会自动采用）</p>` : ""}`; if (["completed","failed","cancelled"].includes(status)) { clearInterval(timer); renderCandidateAdoptionActions(item, target); } } } catch (_) { clearInterval(timer); } }, 1200);
}
function partialPatchState(patch) {
  if (!patch?.patch_id || !patch?.replacement_text) return "缺少已持久化的候选替换内容";
  if (patch?.risk !== "low") return "非低风险 Patch";
  if (!patch?.anchor || !patch?.paragraph_start || !patch?.paragraph_end) return "缺少精确来源定位";
  return "";
}
function renderPartialPatchSelection(item) {
  const patches = Array.isArray(item?.plan?.patches) ? item.plan.patches : [];
  if (!["qualified", "review_required"].includes(item?.state) || !patches.length) return "";
  const rows = patches.map((patch) => { const reason = partialPatchState(patch), disabled = reason ? "disabled" : ""; return `<label class="partial-adoption-patch"><input type="checkbox" data-partial-patch="${evaluationEscape(patch.patch_id)}" ${disabled}> <b>${evaluationEscape(patch.patch_id)}</b> · ${evaluationEscape(patch.action)} · 段落 ${evaluationEscape(patch.paragraph_start)}${reason ? ` <span class="warning">${evaluationEscape(reason)}</span>` : ""}<small>风险：${evaluationEscape(patch.risk)}；问题：${evaluationEscape((patch.issue_ids || []).join(", ") || "—")}；依赖：${evaluationEscape((patch.depends_on_patch_ids || []).join(", ") || "无")}；冲突：${evaluationEscape((patch.conflicts_with_patch_ids || []).join(", ") || "无")}</small><small>原文：${evaluationEscape(patch.original_anchor || patch.anchor || "—")}</small><small>候选文本：${evaluationEscape(patch.replacement_text || "—")}</small></label>`; }).join("<br>");
  return `<section class="evaluation-partial-adoption"><h4>采用所选修改</h4><p>仅能选择服务端已持久化且可验证的低风险 Patch。不能编辑替换文本、范围或锚点。</p><fieldset>${rows}</fieldset><button class="btn btn-secondary" type="button" onclick="openPartialAdoption('${evaluationEscape(item.improvement_id)}')">采用所选修改</button></section>`;
}
function renderCandidateAdoptionActions(item, target) {
  const comparison = item?.comparison || {}, adoptable = ["qualified", "review_required"].includes(item?.state), rejected = item?.state === "rejected";
  const actions = `<section class="evaluation-adoption-actions"><h3>候选操作</h3><p>候选正文、Diff 与评估证据将被保留。采用会创建新的工作正文版本，不会覆盖旧版本或提交正史。</p><p>来源：${evaluationEscape(item?.source_ref?.source_type)}_v${evaluationEscape(item?.source_ref?.source_version)}；评分：${evaluationEscape(comparison.baseline_score)} → ${evaluationEscape(comparison.candidate_score)}；Gate：${evaluationEscape(comparison.gate_before)} → ${evaluationEscape(comparison.gate_after)}</p>${item?.state === "review_required" ? "<p class=\"warning\">该候选存在需作者复核的退化或新增事实风险；采用时必须确认并填写原因。</p>" : ""}${renderPartialPatchSelection(item)}<div class="dialog-actions">${adoptable ? `<button class="btn btn-primary" type="button" onclick="openCandidateAdoption('${evaluationEscape(item.improvement_id)}')">采用整稿</button>` : ""}<button class="btn btn-secondary" type="button" onclick="openCandidateDiscard('${evaluationEscape(item.improvement_id)}')">放弃候选</button></div>${rejected ? "<p>已拒绝候选不能采用，只能放弃。</p>" : ""}</section>`;
  target.insertAdjacentHTML("beforeend", actions);
}
async function openPartialAdoption(requestId) {
  const selectedPatchIds = [...document.querySelectorAll("input[data-partial-patch]:checked")].map((input) => input.dataset.partialPatch);
  if (!selectedPatchIds.length) { alert("请至少选择一个可用 Patch。"); return; }
  let result; try { result = await apiPost(`/api/evaluations/improvements/${encodeURIComponent(requestId)}/partial-adoption-preview`, {selected_patch_ids: selectedPatchIds}); } catch (error) { alert(`无法生成部分采用预览：${error.message}`); return; }
  const preview = result.result?.preview; if (!preview) return; narrativePartialAdoptionPreview = preview;
  let dialog = document.getElementById("narrative-partial-adoption-dialog"); if (!dialog) { dialog = document.createElement("dialog"); dialog.id = "narrative-partial-adoption-dialog"; dialog.className = "dialog confirm-dialog"; document.body.appendChild(dialog); }
  const review = preview.candidate_status === "review_required", selected = (preview.selected_patch_ids || []).map(evaluationEscape).join(", "), unselected = (preview.unselected_patch_ids || []).map(evaluationEscape).join(", ");
  dialog.innerHTML = `<form method="dialog" class="dialog-surface"><div class="dialog-header"><div><span class="eyebrow">Partial adoption preview</span><h2>采用所选修改</h2></div><button class="icon-button" value="cancel" aria-label="关闭">×</button></div><div class="dialog-body"><p>当前工作版本：${evaluationEscape(preview.current_version_id)}（revision ${evaluationEscape(preview.current_version_revision)}）</p><p>候选来源版本：${evaluationEscape(preview.expected_source_version_id)}</p><p>已选：${selected || "—"}</p><p>未选：${unselected || "—"}</p><p>已解决问题：${evaluationEscape((preview.resolved_issue_ids || []).join(", ") || "—")}；仍保留：${evaluationEscape((preview.remaining_issue_ids || []).join(", ") || "—")}</p><p>修改段落：${evaluationEscape((preview.changed_paragraphs || []).join(", ") || "—")}；新增：${evaluationEscape(preview.change_statistics?.added_count)}；删除：${evaluationEscape(preview.change_statistics?.removed_count)}；比例：${evaluationEscape(preview.change_statistics?.changed_ratio)}。仅创建新工作正文版本，不会提交正史。</p><details><summary>合并后完整 Diff</summary>${preview.result_diff?.diff_html || "—"}</details>${review ? `<label><input id="partial-review-confirm" type="checkbox"> 我已复核风险，仍要采用所选修改。</label><label>复核原因 <textarea id="partial-review-reason" required></textarea></label>` : ""}</div><div class="dialog-actions"><button class="btn btn-secondary" value="cancel">取消</button><button id="partial-adopt-confirm" class="btn btn-primary" type="button" onclick="confirmPartialAdoption('${evaluationEscape(requestId)}')">确认采用所选修改</button></div></form>`;
  dialog.showModal();
}
async function confirmPartialAdoption(requestId) {
  const preview = narrativePartialAdoptionPreview, dialog = document.getElementById("narrative-partial-adoption-dialog"); if (!preview) return;
  const review = preview.candidate_status === "review_required", confirmed = !review || !!document.getElementById("partial-review-confirm")?.checked, reason = review ? String(document.getElementById("partial-review-reason")?.value || "").trim() : "";
  if (review && (!confirmed || !reason)) { alert("请确认已复核风险并填写复核原因。"); return; }
  const button = document.getElementById("partial-adopt-confirm"); if (button) button.disabled = true;
  try { const result = await apiPost(`/api/evaluations/improvements/${encodeURIComponent(requestId)}/partial-adopt`, {preview_id: preview.preview_id, candidate_id: preview.candidate_id, selected_patch_ids: preview.selected_patch_ids, expected_current_version_id: preview.current_version_id, expected_current_version_revision: preview.current_version_revision, expected_current_content_hash: preview.current_content_hash, expected_candidate_hash: preview.candidate_content_hash, expected_result_content_hash: preview.result_content_hash, author_confirm: confirmed, review_reason: reason, operation_id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-partial-adopt`}); alert(`已将 ${preview.selected_patch_ids.length} 个所选修改创建为新的工作正文版本：${result.result?.new_version?.version_id || ""}；${preview.unselected_patch_ids.length} 个未选 Patch 已保留，正史未更新。`); dialog.close(); await loadNarrativeEvaluationCenter(); } catch (error) { alert(`部分采用未完成：${error.message}`); if (button) button.disabled = false; }
}
async function openCandidateAdoption(requestId) {
  let result; try { result = await apiPost(`/api/evaluations/improvements/${encodeURIComponent(requestId)}/adoption-preview`, {}); } catch (error) { alert(`无法生成采用预览：${error.message}`); return; }
  const preview = result.result?.preview; if (!preview) return; narrativeAdoptionPreview = preview;
  let dialog = document.getElementById("narrative-adoption-dialog"); if (!dialog) { dialog = document.createElement("dialog"); dialog.id = "narrative-adoption-dialog"; dialog.className = "dialog confirm-dialog"; document.body.appendChild(dialog); }
  const review = preview.candidate_status === "review_required";
  dialog.innerHTML = `<form method="dialog" class="dialog-surface"><div class="dialog-header"><div><span class="eyebrow">Adoption preview</span><h2>采用整稿</h2></div><button class="icon-button" value="cancel" aria-label="关闭">×</button></div><div class="dialog-body"><p>当前工作版本：${evaluationEscape(preview.current_version_id)}（revision ${evaluationEscape(preview.current_version_revision)}）</p><p>候选来源：${evaluationEscape(preview.expected_source_version_id)}；评分：${evaluationEscape(preview.overall_score_before)} → ${evaluationEscape(preview.overall_score_after)}；Gate：${evaluationEscape(preview.gate_before)} → ${evaluationEscape(preview.gate_after)}</p><p>修改：${evaluationEscape(preview.change_statistics?.changed_ratio)}；采用会创建新工作正文版本，不会覆盖旧版本，也不会自动提交正史。</p>${review ? `<label><input id="candidate-review-confirm" type="checkbox"> 我已复核风险，仍要创建新的工作正文版本。</label><label>复核原因 <textarea id="candidate-review-reason" required></textarea></label>` : ""}</div><div class="dialog-actions"><button class="btn btn-secondary" value="cancel">取消</button><button id="candidate-adopt-confirm" class="btn btn-primary" type="button" onclick="confirmCandidateAdoption('${evaluationEscape(requestId)}')">确认采用整稿</button></div></form>`;
  dialog.showModal();
}
async function confirmCandidateAdoption(requestId) {
  const preview = narrativeAdoptionPreview, dialog = document.getElementById("narrative-adoption-dialog"); if (!preview) return;
  const review = preview.candidate_status === "review_required", confirmed = !review || !!document.getElementById("candidate-review-confirm")?.checked, reason = review ? String(document.getElementById("candidate-review-reason")?.value || "").trim() : "";
  if (review && (!confirmed || !reason)) { alert("请确认已复核风险并填写复核原因。"); return; }
  const button = document.getElementById("candidate-adopt-confirm"); if (button) button.disabled = true;
  try { const result = await apiPost(`/api/evaluations/improvements/${encodeURIComponent(requestId)}/adopt`, {preview_id: preview.preview_id, candidate_id: preview.candidate_id, expected_current_version_id: preview.current_version_id, expected_current_version_revision: preview.current_version_revision, expected_current_content_hash: preview.current_content_hash, expected_candidate_hash: preview.candidate_content_hash, author_confirm: confirmed, review_reason: reason, operation_id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-adopt`}); alert(`已创建新的工作正文版本：${result.result?.new_version?.version_id || ""}。正史未更新。`); dialog.close(); await loadNarrativeEvaluationCenter(); } catch (error) { alert(`采用未完成：${error.message}`); if (button) button.disabled = false; }
}
async function openCandidateDiscard(requestId) {
  const detail = await apiGet(`/api/evaluations/improvements/${encodeURIComponent(requestId)}`); const item = detail.result?.improvement, candidate = item?.candidate; if (!item || !candidate) return;
  if (!confirm("放弃不会删除候选、Diff 或评估证据，当前正文和正史不会变化。继续吗？")) return;
  try { await apiPost(`/api/evaluations/improvements/${encodeURIComponent(requestId)}/discard`, {candidate_id: candidate.candidate_id, expected_candidate_hash: candidate.content_hash, reason: "作者放弃候选", operation_id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-discard`}); alert("候选已放弃，历史证据仍保留。"); await loadNarrativeEvaluationCenter(); } catch (error) { alert(`放弃未完成：${error.message}`); }
}
function renderEvaluationIssueList(items) { if (!items.length) return "—"; return `<details><summary>${evaluationEscape(items.length)} 项</summary><ul class="evaluation-issues">${items.map(item => `<li>${evaluationEscape(item.title)} · ${evaluationEscape(item.severity)} · ${evaluationEscape(item.fixability)}</li>`).join("")}</ul></details>`; }
function renderEvaluationPlanning(summary) { const target = document.getElementById("evaluation-planning-health"); if (!target) return; const health = summary.health || {}; target.innerHTML = Object.keys(health).length ? Object.entries(health).map(([name, value]) => `<article class="evaluation-health-card"><small>${evaluationEscape(name)}</small><strong>${evaluationEscape(value.status || value.overall_status || value.health || "unknown")}</strong></article>`).join("") : '<div class="empty-state">尚无可读的规划健康记录。</div>'; }
function renderEvaluationHistory(items) { const target = document.getElementById("evaluation-history-list"); if (!target) return; target.innerHTML = items.length ? items.map(item => `<article class="evaluation-history-item"><div><b>${evaluationEscape(item.target_type)} · 第 ${evaluationEscape(item.target_ref?.chapter_number || "?")} 章</b><p>${evaluationEscape(item.created_at || "")}</p></div><div><span class="evaluation-tag">${evaluationEscape(item.status)}</span> <b>${evaluationEscape(evaluationScore(item.overall_score))}</b></div></article>`).join("") : '<div class="empty-state">暂无统一评估报告。</div>'; }
document.addEventListener("DOMContentLoaded", () => { if (document.getElementById("narrative-evaluation-center")) { const actions = document.querySelector("#narrative-evaluation-center .evaluation-actions"); if (actions && !document.getElementById("narrative-improvement-open")) { const button = document.createElement("button"); button.id = "narrative-improvement-open"; button.className = "btn btn-secondary"; button.type = "button"; button.textContent = "刷新质量"; button.onclick = openNarrativeImprovement; actions.appendChild(button); } loadNarrativeEvaluationCenter().catch(() => {}); } });
