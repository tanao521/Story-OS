(function () {
  "use strict";
  // Contract markers: branch mutations remain explicit existing API routes; history and continuation are read-only UI affordances.
  const CONTRACT_ROUTES = ["/api/narrative-branches/create", "/api/narrative-branches/select", "/api/narrative-branches/archive", "/api/narrative-branches/restore"];
  const CONTRACT_SELECTORS = ["data-continue-next-turn", "data-turn-history-item"]; // Continue to next turn
  const $ = (id) => document.getElementById(id);
  const state = { generation: 0, controller: null, readModel: null, branches: [], mutationBusy: false };
  const safe = (value, fallback = "—") => value === null || value === undefined || value === "" ? fallback : String(value);
  const params = () => new URLSearchParams(window.location.search);
  const scope = () => {
    const p = params();
    return { project_id: p.get("project_id") || p.get("project") || "", timeline_id: p.get("timeline_id") || "main", chapter_id: p.get("chapter_id") || "", source_version_id: p.get("source_version_id") || "", branch_id: p.get("branch_id") || "" };
  };
  function announce(message, assertive) {
    const node = $("simulator-loop-status");
    if (node) { node.textContent = message; node.setAttribute("aria-live", assertive ? "assertive" : "polite"); }
  }
  function pushUrl(changes) {
    const next = params(); next.set("mode", "simulator");
    Object.entries(changes).forEach(([key, value]) => { if (value === null || value === "") next.delete(key); else next.set(key, String(value)); });
    window.history.pushState({}, "", `${window.location.pathname}?${next.toString()}${window.location.hash}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
  async function request(url, options) {
    const response = await fetch(url, { headers: { Accept: "application/json", ...(options && options.headers) }, ...(options || {}) });
    let payload = {};
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok || payload.ok === false) {
      const err = payload.error || {};
      const error = new Error(err.message || (payload.errors || ["Request failed"])[0] || "Request failed");
      error.code = err.code || (payload.errors || ["REQUEST_FAILED"])[0]; error.status = response.status; throw error;
    }
    return payload.result || payload;
  }
  function queryFor(scopeValue) {
    return Object.entries(scopeValue).filter(([, value]) => value).map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join("&");
  }
  async function loadBranches() {
    const current = scope();
    if (!current.project_id) return { branches: [], active_branch_id: null, registry_revision: "0" };
    const result = await request(`/api/narrative-branches?project_id=${encodeURIComponent(current.project_id)}&timeline_id=${encodeURIComponent(current.timeline_id)}`);
    state.branches = Array.isArray(result.branches) ? result.branches : [];
    return result;
  }
  function value(label, text, title) {
    const item = document.createElement("div"); item.className = "simulator-context-value";
    const strong = document.createElement("strong"); strong.textContent = label; item.append(strong);
    const span = document.createElement("span"); span.textContent = safe(text); if (title) span.title = title; item.append(span); return item;
  }
  function renderContext(model) {
    const target = $("simulator-context-values"); if (!target) return; target.replaceChildren();
    const s = model.scope || {}, b = model.branch || {};
    target.append(value("Project", s.project_id), value("Timeline", s.timeline_id), value("Chapter", s.chapter_id), value("Source", s.source_version_id), value("Active branch", b.active_branch_id || "none"), value("Viewed branch", s.branch_id), value("Canon", s.canon_revision_id), value("Stage", model.current_stage));
  }
  function renderProgress(model, view) {
    document.querySelectorAll("[data-loop-view]").forEach((button) => button.dataset.active = button.dataset.loopView === view ? "true" : "false");
    document.querySelectorAll("[data-loop-stage]").forEach((button) => button.dataset.active = button.dataset.loopStage === model.current_stage ? "true" : "false");
  }
  function renderEvidence(model) {
    const target = $("simulator-loop-evidence-body"); if (!target) return; target.replaceChildren();
    const rows = [["branch", `${safe(model.branch.lifecycle_status)} · ${safe(model.branch.readiness)}`], ["registry", model.branch.registry_revision], ["turns", model.turn && model.turn.history_summary ? model.turn.history_summary.count : 0], ["candidate", model.candidate && model.candidate.current_candidate ? model.candidate.current_candidate.review_status : "none"], ["commit", model.commit && model.commit.status], ["next", model.chapter_progression && model.chapter_progression.next_chapter_available ? `Chapter ${model.chapter_progression.next_chapter_id}` : "not available"]];
    rows.forEach(([label, text]) => { const row = document.createElement("div"); row.className = "simulator-evidence-row"; const key = document.createElement("strong"); key.textContent = label; const val = document.createElement("span"); val.textContent = safe(text); row.append(key, val); target.append(row); });
  }
  function mutationButton(label, action, disabled) { const button = document.createElement("button"); button.type = "button"; button.className = "btn btn-secondary btn-compact"; button.textContent = label; button.dataset.branchAction = action; button.disabled = !!disabled; return button; }
  function renderBranches(model, branchResult) {
    const list = $("simulator-branch-list"); if (!list) return; list.replaceChildren();
    const activeId = branchResult && branchResult.active_branch_id || (model.branch && model.branch.active_branch_id);
    const branches = (branchResult && branchResult.branches) || state.branches;
    const open = branches.filter((b) => b.lifecycle_status !== "archived");
    const archived = branches.filter((b) => b.lifecycle_status === "archived");
    [...open, ...archived].forEach((branch) => {
      const row = document.createElement("article"); row.className = "simulator-branch-row"; row.dataset.branchRow = branch.branch_id; row.dataset.branchActive = branch.branch_id === activeId ? "true" : "false"; row.dataset.active = row.dataset.branchActive; row.dataset.branchReadiness = branch.branch_id === (model.scope && model.scope.branch_id) && model.branch ? safe(model.branch.readiness) : "unknown";
      const head = document.createElement("div"); head.className = "simulator-branch-row-head"; const name = document.createElement("strong"); name.textContent = `${safe(branch.display_name, branch.branch_id)} · ${branch.branch_id}`; const stateChip = document.createElement("span"); stateChip.textContent = branch.lifecycle_status === "archived" ? "archived" : branch.branch_id === activeId ? "active" : "open / inactive"; head.append(name, stateChip); row.append(head);
      const meta = document.createElement("div"); meta.className = "simulator-branch-row-meta"; meta.append(document.createTextNode(`lifecycle ${safe(branch.lifecycle_status)} · registry ${safe(branchResult && branchResult.registry_revision, "0")}`)); row.append(meta);
      const actions = document.createElement("div"); actions.className = "simulator-branch-row-actions";
      const browse = mutationButton("Browse branch", "browse"); browse.dataset.branchId = branch.branch_id; actions.append(browse);
      if (branch.lifecycle_status === "archived") { const restore = mutationButton("Restore", "restore"); restore.dataset.branchId = branch.branch_id; actions.append(restore); }
      else if (branch.branch_id !== activeId) { const select = mutationButton("Select as Active", "select"); select.dataset.branchId = branch.branch_id; actions.append(select); }
      if (branch.branch_id === activeId && open.length > 1) { const archive = mutationButton("Archive", "archive"); archive.dataset.branchId = branch.branch_id; actions.append(archive); }
      row.append(actions); list.append(row);
    });
    if (!branches.length) { const empty = document.createElement("p"); empty.textContent = "No active branch. Create or restore a branch before starting a Turn."; list.append(empty); }
  }
  function renderHistory(model) {
    const list = $("simulator-turn-history-list"); if (!list) return; list.replaceChildren();
    const history = model.turn && Array.isArray(model.turn.history) ? model.turn.history : [];
    $("simulator-history-count").textContent = `${history.length} entries`;
    history.forEach((item) => { const article = document.createElement("article"); article.className = "simulator-history-item"; article.dataset.turnHistoryItem = item.turn_id; const header = document.createElement("header"); header.append(document.createTextNode(`#${safe(item.sequence)} · ${safe(item.turn_id)}`)); const status = document.createElement("span"); status.textContent = safe(item.lifecycle); header.append(status); article.append(header); const action = document.createElement("p"); action.textContent = `${safe(item.action_summary)} — ${safe(item.result_summary)}`; article.append(action); const delta = document.createElement("p"); delta.textContent = `State delta: ${JSON.stringify(item.state_delta_summary || [])}`; article.append(delta); list.append(article); });
    if (!history.length) { const empty = document.createElement("p"); empty.textContent = "No confirmed Turns in this branch yet."; list.append(empty); }
  }
  function renderResult(model) {
    const panel = $("simulator-turn-result"); const body = $("simulator-turn-result-body"); if (!panel || !body) return;
    const result = model.turn && model.turn.current_result;
    if (!result || model.current_stage === "HISTORY" || model.current_stage === "ENTRY") { panel.classList.add("hidden"); return; }
    panel.classList.remove("hidden"); body.replaceChildren(); const summary = document.createElement("p"); summary.textContent = `${safe(result.action_summary)} — ${safe(result.result_summary)}`; const lifecycle = document.createElement("p"); lifecycle.textContent = `Lifecycle: ${safe(result.lifecycle)} · Turn ${safe(result.turn_id)}`; body.append(summary, lifecycle);
    if (model.recovery && model.recovery.status === "READY_FOR_NEXT_ACTION") { const restored = document.createElement("p"); restored.dataset.recoveryRestored = "true"; restored.textContent = "Durable result restored from authoritative state."; body.append(restored); }
  }
  function applyMutationGuards(model) {
    const branch = model && model.branch || {}, recovery = model && model.recovery || {};
    const blocked = !!(model && (model.current_stage === "BLOCKED" || (recovery.status && recovery.status !== "READY_FOR_NEXT_ACTION") || branch.active !== true || (branch.readiness && branch.readiness !== "ready")));
    const action = $("nt-primary-action");
    if (action) { action.disabled = blocked; action.dataset.simulatorBlocked = blocked ? "true" : "false"; if (blocked) action.setAttribute("aria-describedby", "simulator-loop-status"); else action.removeAttribute("aria-describedby"); }
    const workspace = $("narrative-turn-workspace"); if (workspace) workspace.dataset.recoveryBlocked = blocked ? "true" : "false";
  }
  function renderRecovery(model) {
    const panel = $("simulator-recovery"); const body = $("simulator-recovery-body"); if (!panel || !body) return; const status = model.recovery && model.recovery.status;
    if (!status || status === "READY_FOR_NEXT_ACTION") { panel.classList.add("hidden"); applyMutationGuards(model); return; }
    panel.classList.remove("hidden"); body.textContent = `${status}. This phase only reads durable state; no recovery mutation is available here.`;
    applyMutationGuards(model);
  }
  async function loadState() {
    const current = scope(); if (!current.project_id || !current.chapter_id || !current.branch_id) return null;
    const mine = ++state.generation; if (state.controller) state.controller.abort(); state.controller = new AbortController();
    try {
      const model = await request(`/api/simulator/state?${queryFor(current)}`, { signal: state.controller.signal });
      if (mine !== state.generation) return null; state.readModel = model; renderContext(model); renderEvidence(model); renderHistory(model); renderResult(model); renderRecovery(model); renderProgress(model, params().get("view") || "narrative-turn"); window.dispatchEvent(new CustomEvent("storyos:simulator-state", { detail: model })); announce(`State loaded · ${safe(model.current_stage)}`); return model;
    } catch (error) { if (error.name === "AbortError") return null; announce(`State unavailable · ${safe(error.message, "read failed")}`, true); return null; }
  }
  async function reload() { try { const branchResult = await loadBranches(); renderBranches(state.readModel || { branch: {} }, branchResult); await loadState(); renderBranches(state.readModel || { branch: {} }, branchResult); } catch (error) { announce(`Branch state unavailable · ${safe(error.message)}`, true); } }
  async function postBranch(action, branchId, extra) {
    if (state.mutationBusy) return; state.mutationBusy = true; announce(`${action} in progress…`);
    try {
      const current = scope(); const body = { project_id: current.project_id, timeline_id: current.timeline_id, branch_id: branchId, operation_id: `simulator-${action}-${Date.now()}-${Math.random().toString(16).slice(2)}`, ...(extra || {}) };
      await request(`/api/narrative-branches/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      announce(`Branch ${action} completed`); if (action === "select") pushUrl({ branch_id: branchId, view: "narrative-turn", turn_id: null, action_id: null }); else await reload();
    } catch (error) { announce(`${action} failed · ${safe(error.message)}`, true); } finally { state.mutationBusy = false; }
  }
  function askText(title, initial = "") {
    return new Promise((resolve) => {
      const dialog = document.createElement("dialog"); dialog.className = "simulator-input-dialog";
      dialog.innerHTML = `<form method="dialog"><h2>${title}</h2><label><span>${title}</span><input autofocus value="${String(initial).replace(/"/g, "&quot;")}" /></label><div><button value="cancel" type="button">Cancel</button><button value="ok" type="submit">Continue</button></div></form>`;
      document.body.append(dialog); const form = dialog.querySelector("form"), input = dialog.querySelector("input");
      const finish = (value) => { dialog.close(); dialog.remove(); resolve(value); };
      dialog.addEventListener("cancel", (event) => { event.preventDefault(); finish(null); }, { once: true });
      form.addEventListener("submit", (event) => { event.preventDefault(); finish(input.value.trim() || null); }, { once: true });
      dialog.querySelector("button[value=cancel]").addEventListener("click", () => finish(null), { once: true });
      if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", "");
    });
  }
  function askConfirm(title) { return askText(title, "confirm") .then((value) => value === "confirm"); }
  async function onBranchAction(event) {
    const button = event.target.closest("[data-branch-action]"); if (!button || button.disabled) return; const action = button.dataset.branchAction; const branchId = button.dataset.branchId;
    if (action === "browse") { pushUrl({ branch_id: branchId, view: "history", turn_id: null, action_id: null }); return; }
    if (action === "select") { if (await askConfirm(`Select ${branchId} as the active branch? Type confirm to continue.`)) postBranch("select", branchId); return; }
    if (action === "restore") { if (await askConfirm(`Restore ${branchId} as an open inactive branch? Type confirm to continue.`)) postBranch("restore", branchId); return; }
    if (action === "archive") { const replacement = await askText("Replacement active branch id", state.readModel && state.readModel.branch ? state.readModel.branch.active_branch_id || "" : ""); if (!replacement) return; postBranch("archive", branchId, { replacement_branch_id: replacement }); }
  }
  async function createBranch() { const branchId = await askText("New inactive branch id"); if (!branchId) return; const display = await askText("Branch display name", branchId) || branchId; postBranch("create", branchId, { display_name: display }); }
  function continueNextTurn() { pushUrl({ view: "narrative-turn", turn_id: null, action_id: null }); }
  function onView(event) { const button = event.target.closest("[data-loop-view]"); if (button) pushUrl({ view: button.dataset.loopView, turn_id: null, action_id: null }); }
  function ensureEntry() {
    const current = scope(); if (!current.project_id || !current.chapter_id || current.branch_id) return;
    // A missing branch is a setup state; never silently select the registry's first/active branch.
    announce("BRANCH_SETUP · explicitly select a branch before starting", true);
  }
  function apply() {
    const current = scope(); const shell = $("simulator-loop-shell"); if (!shell || params().get("mode") !== "simulator") return;
    shell.classList.remove("hidden"); ensureEntry();
    if (current.project_id && current.chapter_id && !current.branch_id) loadBranches().then((result) => renderBranches(state.readModel || { branch: {} }, result)).catch(() => {});
    if (current.branch_id && current.chapter_id) reload();
  }
  function init() {
    $("simulator-branch-list")?.addEventListener("click", onBranchAction); $("simulator-branch-create")?.addEventListener("click", createBranch); $("simulator-continue-next-turn")?.addEventListener("click", continueNextTurn); $("simulator-progress-rail")?.addEventListener("click", onView); $("simulator-recovery-refresh")?.addEventListener("click", reload);
    window.addEventListener("popstate", apply); window.addEventListener("storyos:panel-context-ready", () => setTimeout(apply, 0)); window.addEventListener("storyos:dashboard-ready", apply); window.addEventListener("storyos:narrative-turn-confirmed", reload); apply();
  }
  window.StoryOSSimulatorLoop = { init, loadState, loadBranches, getState: () => state.readModel };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
