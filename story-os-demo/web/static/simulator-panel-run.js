(function () {
  "use strict";
  const MAX = 5;
  const $ = (id) => document.getElementById(id);
  let plan = null;
  let busy = false;
  let controller = null;
  let generation = 0;
  function status(message, tone = "") { const target = $("simulator-panel-plan-output"); if (target) { target.textContent = message; target.dataset.tone = tone; } }
  function selected() { return Array.from(document.querySelectorAll("input[data-simulator-persona]:checked"), (input) => input.value); }
  function updateCount() { const count = selected().length; const target = $("simulator-panel-persona-count"); if (target) target.textContent = `${count} / ${MAX}`; $("simulator-panel-plan-button")?.toggleAttribute("disabled", count < 1 || count > MAX || busy); }
  function params() { return new URLSearchParams(window.location.search); }
  function requestBody(personaIds) {
    const query = params();
    const scope = window.__storyosSimulatorContext || {};
    return { project_key: query.get("project") || "", project_id: scope.scope_project_id || "", timeline_id: query.get("timeline_id") || "main", chapter_id: Number(query.get("chapter_id") || 0), source_version_id: query.get("source_version_id") || null, persona_ids: personaIds, mode: "mock", execution_profile: "mock", max_provider_calls: 0 };
  }
  async function planRun() {
    const personaIds = selected();
    if (personaIds.length < 1 || personaIds.length > MAX) { status("Select between 1 and 5 enabled Personas.", "error"); return; }
    const body = requestBody(personaIds);
    if (!body.project_key || !body.project_id || !body.chapter_id) { status("A valid project, timeline, and chapter context is required.", "error"); return; }
    if (window.__storyosSimulatorContext && window.__storyosSimulatorContext.source_available === false) { status("Source context is missing; Mock Run was not planned.", "error"); return; }
    busy = true; plan = null; generation += 1; if (controller) controller.abort(); controller = new AbortController(); $("simulator-panel-run-button")?.setAttribute("disabled", "disabled"); status("Planning Mock Run…");
    try {
      const response = await window.storyosApiRequest("/api/reader-persona/model-panel/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal: controller.signal });
      plan = response.result || {};
      const ordered = (plan.ordered_persona_ids || []).join(" → ");
      status(`Plan ready · order: ${ordered || "not provided"} · cache hit ${plan.cache_hit_persona_ids?.length || 0} · expected live provider calls ${plan.expected_provider_calls ?? "not provided"} · mode mock`, plan.can_execute ? "ready" : "error");
      if (plan.can_execute) $("simulator-panel-run-button")?.removeAttribute("disabled");
    } catch (error) { if (error.name !== "AbortError") status(`Plan blocked: ${error.message || "request failed"}`, "error"); }
    finally { busy = false; updateCount(); }
  }
  async function executeRun() {
    if (!plan || !plan.can_execute || busy) return;
    busy = true; generation += 1; if (controller) controller.abort(); controller = new AbortController(); $("simulator-panel-run-button")?.setAttribute("disabled", "disabled"); status("Creating immutable Mock Panel Run…");
    try {
      const response = await window.storyosApiRequest("/api/reader-persona/model-panel/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(requestBody(selected())), signal: controller.signal });
      const result = response.result || {};
      if (result.status === "blocked") throw new Error(result.error_code || "MOCK_RUN_BLOCKED");
      const executionId = result.panel_execution_id;
      if (!executionId) throw new Error("Execution id was not returned");
      const next = params(); next.set("panel_execution_id", executionId);
      window.history.pushState({}, "", `${window.location.pathname}?${next.toString()}${window.location.hash}`);
      status(`Mock Panel Run created · ${executionId} · provider calls 0`, "ready");
      window.dispatchEvent(new CustomEvent("storyos:panel-run-created", { detail: { executionId } }));
      window.dispatchEvent(new PopStateEvent("popstate"));
    } catch (error) { if (error.name !== "AbortError") status(`Run failed: ${error.message || "request failed"}. No retry was performed.`, "error"); }
    finally { busy = false; updateCount(); }
  }
  async function loadPersonas() {
    try {
      const response = await window.storyosApiGet("/api/reader-persona/options");
      const personas = (response.result?.personas || []).filter((item) => item && item.enabled === true).sort((a, b) => Number(a.deterministic_order || 0) - Number(b.deterministic_order || 0));
      const target = $("simulator-panel-persona-options"); if (!target) return;
      target.replaceChildren();
      personas.forEach((persona) => {
        const label = document.createElement("label"); label.className = "storyos-panel-persona-option";
        const input = document.createElement("input"); input.type = "checkbox"; input.value = persona.persona_id; input.dataset.simulatorPersona = "true"; input.addEventListener("change", updateCount);
        const copy = document.createElement("span"); const name = document.createElement("strong"); name.textContent = `${persona.deterministic_order}. ${persona.display_name}`; const description = document.createElement("small"); description.textContent = persona.short_description || "Not provided"; copy.append(name, description); label.append(input, copy); target.append(label);
      });
      updateCount();
    } catch (error) { status(`Persona options unavailable: ${error.message || "request failed"}`, "error"); }
  }
  function updateScope() { const query = params(); const target = $("simulator-panel-run-scope"); if (target) target.textContent = `Read-only scope · project ${query.get("project") || "not selected"} · timeline ${query.get("timeline_id") || "not selected"} · chapter ${query.get("chapter_id") || "not selected"}`; }
  function init() {
    $("simulator-panel-run-open")?.addEventListener("click", () => { $("simulator-panel-run-drawer")?.classList.toggle("hidden"); updateScope(); });
    $("simulator-panel-plan-button")?.addEventListener("click", planRun);
    $("simulator-panel-run-button")?.addEventListener("click", executeRun);
    window.addEventListener("popstate", updateScope);
    window.addEventListener("storyos:dashboard-ready", () => { updateScope(); loadPersonas(); });
    window.addEventListener("storyos:panel-context-ready", (event) => { window.__storyosSimulatorContext = event.detail || {}; updateScope(); });
    updateScope(); loadPersonas();
  }
  window.StoryOSSimulatorPanelRun = { init, reset: () => { plan = null; status(""); updateCount(); } };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
