(() => {
  const byId = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>\"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  const get = async (url) => { const response = await fetch(url); const payload = await response.json(); if (!response.ok) throw new Error(payload.message || "Request failed"); return payload.result || {}; };
  function render(data) {
    const totals = data.usage.totals || {};
    byId("model-center-summary").innerHTML = `<div><small>Tracked runs</small><strong>${esc(totals.runs || 0)}</strong></div><div><small>Tokens</small><strong>${esc(totals.total_tokens || 0)}</strong></div><div><small>Known cost</small><strong>${totals.cost == null ? "—" : "$" + esc(totals.cost)}</strong></div><div><small>Unknown cost</small><strong>${esc(totals.unknown_cost_runs || 0)}</strong></div>`;
    byId("model-route-list").innerHTML = Object.entries(data.routes.routes || {}).map(([task, route]) => `<article class="model-row"><b>${esc(task)}</b><span>${esc(route.primary)}${route.fallbacks?.length ? " → " + esc(route.fallbacks.join(", ")) : ""}</span><small>${route.local_only ? "local only" : "fallback enabled"}</small></article>`).join("") || '<div class="empty-state">No task routes configured.</div>';
    byId("model-definition-list").innerHTML = (data.models.models || []).map((model) => `<article class="model-row"><b>${esc(model.display_name || model.model_key)}</b><span>${esc(model.provider)} / ${esc(model.model)}</span><small>${model.local ? "local" : "cloud"} · ${model.api_key_configured ? "credential configured" : "credential missing"}</small></article>`).join("") || '<div class="empty-state">No models configured.</div>';
    byId("model-run-list").innerHTML = (data.runs.runs || []).map((run) => `<article class="model-row"><b>${esc(run.task_type)}</b><span>${esc(run.model_key)} · ${esc(run.status)}</span><small>${esc(run.usage?.total_tokens || 0)} tokens${run.cost?.amount == null ? " · cost unknown" : " · $" + esc(run.cost.amount)}</small></article>`).join("") || '<div class="empty-state">No model calls recorded for this project.</div>';
  }
  async function refresh() {
    const root = byId("model-center-panel"); if (!root) return;
    try { const [routes, models, runs, usage] = await Promise.all([get("/api/models/routes"), get("/api/models"), get("/api/models/runs?limit=12"), get("/api/models/usage")]); render({routes, models, runs, usage}); }
    catch (error) { byId("model-center-summary").textContent = `Unable to read model centre: ${error.message}`; }
  }
  document.addEventListener("DOMContentLoaded", () => { byId("model-center-panel")?.querySelector("[data-model-center-refresh]")?.addEventListener("click", refresh); refresh(); });
  window.addEventListener("storyos:project-changed", refresh);
  window.refreshModelCenter = refresh;
})();
