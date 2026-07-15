let narrativeEvaluationRequest = 0;
let narrativeImprovementReport = null;
let narrativeAdoptionPreview = null;
let narrativePartialAdoptionPreview = null;
let narrativePlanningOverview = null;

function evaluationEscape(value) { return typeof escapeHtml === "function" ? escapeHtml(String(value ?? "")) : String(value ?? ""); }
function evaluationScore(value) { return value === null || value === undefined ? "证据不足" : `${Math.round(Number(value))}`; }
function evaluationGateLabel(value) { return ({pass:"可通过",attention:"需要复核",blocked:"阻塞",invalid:"数据异常"})[value] || "需要复核"; }

async function loadNarrativeEvaluationCenter() {
  const ticket = ++narrativeEvaluationRequest;
  ensureEvaluationUsagePanel();
  const result = await Promise.all([apiGet("/api/evaluations/overview"), apiGet("/api/evaluations?limit=12"), apiGet("/api/evaluations/planning/overview"), apiGet("/api/evaluations/usage/summary")]);
  if (ticket !== narrativeEvaluationRequest) return;
  const overview = result[0].result || {}, history = (result[1].result || {}).evaluations || [];
  renderNarrativeEvaluation(overview.latest_report, overview);
  renderEvaluationPlanning(overview.planning_gate_summary || {});
  renderPlanningEvaluationOverview(result[2].result || {});
  renderEvaluationHistory(history);
  renderEvaluationUsage(result[3].result || {});
}

function ensureEvaluationUsagePanel() {
  if (document.getElementById("evaluation-usage-summary")) return;
  const center = document.getElementById("narrative-evaluation-center"), history = center?.querySelector(".evaluation-history"); if (!center || !history) return;
  const panel = document.createElement("section"); panel.id = "evaluation-usage-summary"; panel.className = "evaluation-usage-summary";
  panel.innerHTML = '<header><span class="eyebrow">Call ledger</span><h3>调用与成本</h3><p>只显示已记录调用；缺失 token 或成本会明确标注。</p></header><div id="evaluation-usage-result" class="evaluation-health-grid"><div class="empty-state">正在读取调用摘要…</div></div>';
  center.insertBefore(panel, history);
}

function renderEvaluationUsage(payload) {
  const target = document.getElementById("evaluation-usage-result"), totals = payload.totals || {}; if (!target) return;
  const tokens = totals.token_status === "unavailable" ? "不可用" : `${totals.input_tokens || 0} / ${totals.output_tokens || 0}`;
  const cost = totals.cost_status === "unavailable" ? "不可用" : String(totals.estimated_cost ?? 0);
  target.innerHTML = [["调用", totals.call_count || 0], ["Token（输入 / 输出）", tokens], ["估算成本", cost], ["Fallback", totals.fallback_count || 0], ["失败", totals.failure_count || 0], ["平均耗时", totals.average_latency_ms == null ? "—" : `${totals.average_latency_ms} ms`]].map(([name, value]) => `<article class="evaluation-health-card"><small>${evaluationEscape(name)}</small><strong>${evaluationEscape(value)}</strong></article>`).join("");
}

async function generateNarrativeEvaluation() {
  const result = await apiPost("/api/evaluations", { target_type: "chapter_draft", chapter_number: currentVersion?.chapter_id || undefined, source_type: currentVersion?.source_type || undefined, source_version: currentVersion?.version || undefined, profile_id: "chapter-default-v1", operation_id: "" });
  if (!result.ok) { if (typeof logApiResult === "function") logApiResult("叙事评估", result); return; }
  renderNarrativeEvaluation((result.result || {}).evaluation || {}, {});
  await loadNarrativeEvaluationCenter();
}

function renderPlanningEvaluationOverview(overview) {
  narrativePlanningOverview = overview || {};
  const select = document.getElementById("planning-evaluation-scope"), button = document.getElementById("planning-evaluation-generate"), scopes = Array.isArray(overview?.available_scopes) ? overview.available_scopes : [];
  if (!select) return;
  [...select.options].forEach((option) => { const scope = scopes.find((item) => item.target_type === option.value); option.disabled = !!scope && !scope.available; option.title = scope?.reason || ""; });
  if (button) button.disabled = ![...select.options].some((option) => !option.disabled);
  const latest = scopes.map((scope) => overview.latest_reports?.find((item) => item.target_type === scope.target_type)).filter(Boolean)[0];
  if (latest) renderPlanningEvaluationReport(latest);
}

async function generatePlanningEvaluation() {
  const select = document.getElementById("planning-evaluation-scope"), button = document.getElementById("planning-evaluation-generate"); if (!select || select.selectedOptions[0]?.disabled) return;
  const targetType = select.value, scope = (narrativePlanningOverview?.available_scopes || []).find((item) => item.target_type === targetType) || {};
  if (button) button.disabled = true;
  try { const response = await apiPost("/api/evaluations/planning", {target_type: targetType, scope_ref: scope.scope_ref || {}, profile_id: "planning-default-v1", operation_id: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-planning`}); renderPlanningEvaluationReport(response.result?.evaluation); await loadNarrativeEvaluationCenter(); } catch (error) { const target = document.getElementById("planning-evaluation-result"); if (target) target.textContent = `规划评估未完成：${error.message}`; } finally { if (button) button.disabled = false; }
}

function renderPlanningEvaluationReport(report, requestTicket = narrativeEvaluationRequest) {
  const target = document.getElementById("planning-evaluation-result"); if (!target) return;
  if (!report) { target.innerHTML = '<div class="empty-state">尚未生成长篇规划评估。</div>'; return; }
  const gate = report.gate_status || "attention", dimensions = Array.isArray(report.dimensions) ? report.dimensions : [], issues = Array.isArray(report.priority_issues) ? report.priority_issues.slice(0, 5) : [];
  target.innerHTML = `<section class="planning-evaluation-report"><div class="evaluation-summary"><article class="evaluation-gate ${evaluationEscape(gate)}"><span>硬性门禁</span><strong>${evaluationEscape(evaluationGateLabel(gate))}</strong><p>${evaluationEscape((report.gate_reasons || []).join("；") || "未发现阻塞原因")}</p></article><article class="evaluation-stat"><span>综合规划评分</span><strong>${evaluationEscape(evaluationScore(report.overall_score))}</strong></article><article class="evaluation-stat"><span>证据覆盖率</span><strong>${evaluationEscape(Math.round(Number(report.overall_coverage || 0) * 100))}%</strong></article><article class="evaluation-stat"><span>置信度</span><strong>${evaluationEscape(Math.round(Number(report.overall_confidence || report.confidence || 0) * 100))}%</strong></article></div><div class="evaluation-table-wrap"><table class="evaluation-table"><thead><tr><th>维度</th><th>分数</th><th>权重</th><th>覆盖率</th><th>置信度</th><th>状态</th><th>主要问题</th></tr></thead><tbody>${dimensions.map((item) => `<tr><td>${evaluationEscape(item.display_name)}</td><td>${evaluationEscape(evaluationScore(item.score))}</td><td>${evaluationEscape(Math.round(Number(item.weight || 0) * 100))}%</td><td>${evaluationEscape(Math.round(Number(item.coverage || 0) * 100))}%</td><td>${evaluationEscape(Math.round(Number(item.confidence || 0) * 100))}%</td><td>${evaluationEscape(item.status)}</td><td><details><summary>${evaluationEscape((item.issues || []).length)} 项</summary>${renderEvaluationIssueList(item.issues || [])}<ul>${(item.evidence || []).map((evidence) => `<li>${evaluationEscape(evidence.summary)}</li>`).join("")}</ul></details></td></tr>`).join("")}</tbody></table></div><section><h4>最高优先级问题</h4>${issues.length ? `<ol class="evaluation-issues">${issues.map((item) => `<li><b>${evaluationEscape(item.severity)}</b> · ${evaluationEscape(item.title)}<p>${evaluationEscape(item.suggestion || "请作者检查相关规划对象。")}</p></li>`).join("")}</ol>` : "<p>暂无高优先级规划问题。</p>"}</section></section>`;
  if (report.evaluation_id) loadPlanningComparisonWorkspace(report, requestTicket).catch(() => {});
}

function planningDelta(value) { return value === null || value === undefined ? "证据不足" : `${Number(value) > 0 ? "+" : ""}${Math.round(Number(value) * 100) / 100}`; }
function planningComparisonLabel(value) { return ({ improved:"改善", unchanged:"持平", worsened:"退化", not_comparable:"不可比较", insufficient_evidence:"证据不足" })[value] || value || "—"; }
async function loadPlanningComparisonWorkspace(report, requestTicket = narrativeEvaluationRequest) {
  const [history, proposals] = await Promise.all([apiGet(`/api/evaluations/${encodeURIComponent(report.evaluation_id)}/comparable-reports`), apiGet(`/api/evaluations/${encodeURIComponent(report.evaluation_id)}/planning-proposals`)]);
  if (requestTicket !== narrativeEvaluationRequest) return;
  const select = document.getElementById("planning-comparison-baseline"), items = history.result?.reports || [];
  if (select) { select.innerHTML = `<option value="">最近可比较报告</option>${items.map(item => `<option value="${evaluationEscape(item.evaluation_id)}">${evaluationEscape(item.created_at)} · ${evaluationEscape(item.gate_status)} · ${evaluationEscape(evaluationScore(item.overall_score))}</option>`).join("")}`; select.onchange = () => loadPlanningComparison(report.evaluation_id, select.value, requestTicket); }
  renderPlanningProposals(proposals.result || {}); await loadPlanningComparison(report.evaluation_id, "", requestTicket);
}
async function loadPlanningComparison(evaluationId, baselineId, requestTicket = narrativeEvaluationRequest) {
  const query = baselineId ? `?baseline_evaluation_id=${encodeURIComponent(baselineId)}` : "";
  try { const response = await apiGet(`/api/evaluations/${encodeURIComponent(evaluationId)}/comparison${query}`); if (requestTicket === narrativeEvaluationRequest) renderPlanningComparison(response.result?.comparison || {}); } catch (error) { const target = document.getElementById("planning-comparison-result"); if (requestTicket === narrativeEvaluationRequest && target) target.textContent = `无法读取历史对比：${error.message}`; }
}
function renderPlanningComparison(item) {
  const target = document.getElementById("planning-comparison-result"); if (!target) return;
  if (item.comparison_status === "no_baseline") { target.innerHTML = '<div class="empty-state">暂无可比较的历史评估。</div>'; return; }
  const dimensions = Array.isArray(item.dimension_deltas) ? item.dimension_deltas : [], changed = item.changed_issues || [], persistent = item.persistent_issues || [];
  target.innerHTML = `<section class="planning-comparison-card ${evaluationEscape(item.comparison_status)}"><div class="planning-comparison-lede"><span>Gate ${evaluationEscape(evaluationGateLabel(item.gate_before))} → ${evaluationEscape(evaluationGateLabel(item.gate_after))}</span><b>${evaluationEscape(planningComparisonLabel(item.gate_change))}</b><small>总分 ${evaluationEscape(evaluationScore(item.overall_score_before))} → ${evaluationEscape(evaluationScore(item.overall_score_after))}（${evaluationEscape(planningDelta(item.overall_delta))}）</small></div>${item.historical_reference_only ? '<p class="warning">该比较基于旧规划来源，仅供历史参考。</p>' : ""}<div class="evaluation-table-wrap"><table class="evaluation-table"><thead><tr><th>维度</th><th>上次</th><th>本次</th><th>变化</th><th>覆盖率变化</th><th>状态</th></tr></thead><tbody>${dimensions.map(row => `<tr><td>${evaluationEscape(row.display_name)}</td><td>${evaluationEscape(evaluationScore(row.score_before))}</td><td>${evaluationEscape(evaluationScore(row.score_after))}</td><td>${evaluationEscape(planningDelta(row.score_delta))}</td><td>${evaluationEscape(planningDelta(row.coverage_delta))}</td><td>${evaluationEscape(planningComparisonLabel(row.comparison_status))}</td></tr>`).join("")}</tbody></table></div><div class="planning-issue-columns"><article><h5>新增 ${evaluationEscape((item.new_issues || []).length)}</h5></article><article><h5>已解决 ${evaluationEscape((item.resolved_issues || []).length)}</h5></article><article><h5>持续 ${evaluationEscape(persistent.length)}</h5><p>${persistent.map(issue => evaluationEscape(issue.title)).join("；") || "—"}</p></article><article><h5>变化 ${evaluationEscape(changed.length)}</h5></article></div></section>`;
}
function renderPlanningProposals(payload) {
  const target = document.getElementById("planning-proposals-result"); if (!target) return;
  if (payload.proposal_status === "source_stale") { target.innerHTML = '<div class="empty-state">报告已过期；不生成当前改进建议。</div>'; return; }
  const proposals = Array.isArray(payload.proposals) ? payload.proposals : [];
  target.innerHTML = proposals.length ? `<ol class="planning-proposal-list">${proposals.slice(0, 5).map(item => `<li><header><b>${evaluationEscape(item.priority)}</b><strong>${evaluationEscape(item.title)}</strong></header><p>${evaluationEscape(item.reason)}</p><p>影响：${evaluationEscape((item.affected_dimensions || []).join("、") || "规划范围")}；持续 ${evaluationEscape(item.persistence_count || 0)} 次</p><p>建议检查：${evaluationEscape((item.suggested_actions || []).join("；"))}</p><small>风险：${evaluationEscape(item.risk)}；仅供作者决策</small></li>`).join("")}</ol>` : '<div class="empty-state">当前报告没有可生成的确定性建议。</div>';
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
