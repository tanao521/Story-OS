(() => {
  const byId = (id) => document.getElementById(id);
  let selected = null;

  async function api(path, options) {
    const response = await fetch(path, options);
    const body = await response.json();
    if (!body.ok) throw new Error((body.errors || [body.message || "Request failed."])[0]);
    return body.result || {};
  }
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));

  async function refresh() {
    const [revisionData, archiveData] = await Promise.all([api("/api/revisions"), api("/api/archive")]);
    const sessions = byId("revision-session-list");
    sessions.innerHTML = (revisionData.revisions || []).length ? revisionData.revisions.map((item) => `<button class="revision-row" data-revision-open="${escape(item.revision_id)}"><b>第 ${item.chapter_id} 章</b><span>${escape(item.status)}</span><small>${escape(item.reason || "无修订原因")}</small></button>`).join("") : "<p class=\"empty-state\">暂无修订会话。选择已提交章节后发起修订。</p>";
    sessions.querySelectorAll("[data-revision-open]").forEach((button) => button.addEventListener("click", () => openRevision(button.dataset.revisionOpen)));
    const archive = byId("revision-archive-list");
    archive.innerHTML = (archiveData.items || []).length ? archiveData.items.map((item) => `<article class="archive-row"><b>${escape(item.item_type)}</b><span>第 ${escape(item.chapter_id || "—")} 章</span><small>${escape(item.reason || "无说明")}</small>${item.restorable ? `<button class="btn btn-secondary btn-compact" data-archive-restore="${escape(item.archive_id)}">恢复副本</button>` : ""}</article>`).join("") : "<p class=\"empty-state\">暂无可恢复归档内容。</p>";
    archive.querySelectorAll("[data-archive-restore]").forEach((button) => button.addEventListener("click", async () => {
      try { await api(`/api/archive/${button.dataset.archiveRestore}/restore`, {method:"POST"}); await refresh(); } catch (error) { alert(error.message); }
    }));
  }

  async function openRevision(id) {
    selected = id;
    const data = await api(`/api/revisions/${encodeURIComponent(id)}`);
    const revision = data.revision; const candidates = data.candidates || [];
    const detail = byId("revision-detail");
    detail.innerHTML = `<p><b>第 ${revision.chapter_id} 章</b> · ${escape(revision.status)} · 基线 ${escape(revision.base_canon_version_id)}</p><div class="revision-candidates">${candidates.map((item) => `<button class="revision-row" data-candidate="${escape(item.candidate_version_id)}">${escape(item.candidate_version_id)} <small>${item.word_count} 字</small></button>`).join("")}</div><textarea id="revision-content" rows="10" placeholder="输入修订正文；保存会创建新候选，不会覆盖正史。"></textarea><div class="revision-actions"><button class="btn btn-secondary btn-compact" data-candidate-save>保存为新候选</button><button class="btn btn-secondary btn-compact" data-revision-diff>与正史比较</button><button class="btn btn-secondary btn-compact" data-revision-quality>质量检查</button><button class="btn btn-secondary btn-compact" data-revision-continuity>连续性检查</button><button class="btn btn-secondary btn-compact" data-revision-impact>影响分析</button><button class="btn btn-primary btn-compact" data-revision-approve>人工批准</button><button class="btn btn-danger btn-compact" data-revision-apply>应用已批准修订</button></div><pre id="revision-output" class="revision-output">候选与报告将在这里显示。</pre>`;
    const active = candidates.find((item) => item.candidate_version_id === revision.active_candidate_version_id) || candidates.at(-1);
    if (active) byId("revision-content").value = active.content || "";
    detail.querySelector("[data-candidate-save]").onclick = () => task(`/api/revisions/${id}/candidates`, {content: byId("revision-content").value}, openRevision);
    detail.querySelector("[data-revision-diff]").onclick = async () => { const out = await api(`/api/revisions/${id}/diff`); byId("revision-output").textContent = (out.diff.unified_diff || []).join("\n") || "No text changes."; };
    detail.querySelector("[data-revision-quality]").onclick = () => task(`/api/revisions/${id}/quality-check`, null, showTask);
    detail.querySelector("[data-revision-continuity]").onclick = () => task(`/api/revisions/${id}/continuity-check`, null, showTask);
    detail.querySelector("[data-revision-impact]").onclick = () => task(`/api/revisions/${id}/impact-analysis`, null, showTask);
    detail.querySelector("[data-revision-approve]").onclick = () => task(`/api/revisions/${id}/review`, {decision:"approve", confirmed_risks:true}, openRevision);
    detail.querySelector("[data-revision-apply]").onclick = () => task(`/api/revisions/${id}/apply`, null, showTask);
  }
  async function task(path, payload, next) {
    try { const result = await api(path, {method:"POST", headers:{"Content-Type":"application/json"}, body: payload ? JSON.stringify(payload) : undefined}); if (next === openRevision) await next(selected); else next(result); } catch (error) { alert(error.message); }
  }
  function showTask(result) { byId("revision-output").textContent = result.job ? `任务已创建：${result.job.job_id}` : JSON.stringify(result, null, 2); refresh(); }
  function init() {
    const create = byId("revision-center-panel"); if (!create) return;
    create.querySelector("[data-revision-refresh]").onclick = () => refresh().catch((error) => { byId("revision-session-list").textContent = error.message; });
    create.querySelector("[data-revision-create]").onclick = () => { const chapter = Number(byId("revision-chapter-id").value); if (!chapter) return; task("/api/revisions", {chapter_id:chapter, reason:byId("revision-reason").value}, (data) => { refresh(); openRevision(data.revision.revision_id); }); };
    refresh().catch((error) => { byId("revision-session-list").textContent = error.message; });
  }
  window.addEventListener("storyos:project-changed", () => { selected = null; refresh().catch(() => {}); });
  window.addEventListener("storyos:project-cleared", () => { selected = null; const detail = byId("revision-detail"); if (detail) detail.textContent = "Project changed. Select a revision in the current project."; const sessions = byId("revision-session-list"); if (sessions) sessions.textContent = "Loading current project revisions?"; });
  document.addEventListener("DOMContentLoaded", init);
})();
