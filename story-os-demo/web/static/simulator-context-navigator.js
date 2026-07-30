(function () {
  "use strict";
  const ids = { project: "simulator-context-project", timeline: "simulator-context-timeline", chapter: "simulator-context-chapter", source: "simulator-context-source", run: "simulator-context-run", status: "simulator-context-navigator-status" };
  let generation = 0;
  let controller = null;
  const el = (key) => document.getElementById(ids[key]);
  const label = (value, fallback = "Not provided") => value === null || value === undefined || value === "" ? fallback : String(value);
  function setOptions(select, values, selected, emptyLabel) {
    if (!select) return;
    select.replaceChildren();
    if (!values.length) { select.append(new Option(emptyLabel, "")); select.disabled = true; return; }
    values.forEach((item) => select.append(new Option(item.label, item.value)));
    select.value = values.some((item) => item.value === selected) ? selected : values[0].value;
    select.disabled = false;
  }
  function params() { return new URLSearchParams(window.location.search); }
  function readCanonicalProjectIdentity(search = window.location.search) {
    const current = search instanceof URLSearchParams ? search : new URLSearchParams(search);
    const project = current.get("project") || "";
    const projectId = current.get("project_id") || "";
    const mismatch = !!project && !!projectId && project !== projectId;
    return {
      project,
      project_id: projectId,
      canonical_project_id: mismatch ? "" : (projectId || project),
      consistent: !mismatch,
      mismatch,
    };
  }
  function canonicalContext(search = window.location.search) {
    const current = search instanceof URLSearchParams ? search : new URLSearchParams(search);
    const identity = readCanonicalProjectIdentity(current);
    return [
      identity.mismatch ? `__inconsistent__:${identity.project}:${identity.project_id}` : identity.canonical_project_id,
      current.get("timeline_id") || "",
      current.get("branch_id") || "",
      current.get("chapter_id") || "",
    ].join("|");
  }

  // The navigator is the single owner of simulator URL context notifications.
  // Several simulator panels write intentional history entries directly. A
  // native pushState does not emit popstate, so synthesize the existing
  // context-change signal only when the canonical context actually changed.
  function installHistoryContextBridge() {
    const nativePushState = window.history.pushState;
    window.history.pushState = function (...args) {
      const before = canonicalContext();
      const result = nativePushState.apply(this, args);
      if (before !== canonicalContext()) {
        window.dispatchEvent(new PopStateEvent("popstate"));
      }
      return result;
    };
  }
  function updateUrl(changes) {
    const next = params();
    next.set("mode", "simulator");
    const currentView = next.get("view");
    if (!currentView) {
      next.set("view", "reader-panel-review");
    }
    const identityValue = Object.prototype.hasOwnProperty.call(changes, "project")
      ? changes.project
      : (Object.prototype.hasOwnProperty.call(changes, "project_id") ? changes.project_id : undefined);
    if (identityValue !== undefined) {
      if (identityValue) {
        next.set("project", String(identityValue));
        next.set("project_id", String(identityValue));
      } else {
        next.delete("project");
        next.delete("project_id");
      }
    }
    Object.entries(changes).forEach(([key, value]) => {
      if (key === "project" || key === "project_id") return;
      if (key === "view") {
        if (value) next.set("view", value); else next.delete("view");
      } else if (value) {
        next.set(key, value);
      } else {
        next.delete(key);
      }
    });
    window.history.pushState({}, "", `${window.location.pathname}?${next.toString()}${window.location.hash}`);
  }
  async function get(url, signal) {
    const response = await fetch(url, { headers: { Accept: "application/json" }, signal });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) throw new Error((payload.errors || [payload.message || "Request failed"])[0]);
    return payload.result || payload;
  }
  function bindChanges() {
    el("project")?.addEventListener("change", (event) => updateUrl({ project: event.target.value, project_id: event.target.value, timeline_id: "main", chapter_id: "", source_version_id: "", panel_execution_id: "" }));
    el("timeline")?.addEventListener("change", (event) => updateUrl({ timeline_id: event.target.value, chapter_id: "", source_version_id: "", panel_execution_id: "" }));
    el("chapter")?.addEventListener("change", (event) => updateUrl({ chapter_id: event.target.value, source_version_id: "", panel_execution_id: "" }));
    el("source")?.addEventListener("change", (event) => updateUrl({ source_version_id: event.target.value, panel_execution_id: "" }));
    el("run")?.addEventListener("change", (event) => updateUrl({ panel_execution_id: event.target.value }));
  }
  async function load() {
    const mine = ++generation;
    if (params().get("mode") !== "simulator") return;
    if (controller) controller.abort();
    controller = new AbortController();
    const status = el("status"); if (!status) return;
    try {
      const projectData = await get("/api/projects", controller.signal);
      const projects = (projectData.projects || []).filter((item) => item && item.valid === true && item.project_id);
      const identity = readCanonicalProjectIdentity();
      if (identity.mismatch) {
        status.textContent = "Project context is inconsistent; progression requests were skipped";
        ["project", "timeline", "chapter", "source", "run"].forEach((key) => setOptions(el(key), [], "", "Context is inconsistent"));
        window.dispatchEvent(new CustomEvent("storyos:canonical-context-invalid", { detail: identity }));
        return;
      }
      const current = identity.canonical_project_id;
      setOptions(el("project"), projects.map((item) => ({ value: String(item.project_id), label: label(item.title, item.project_id) })), current || (projects.length === 1 ? String(projects[0].project_id) : ""), "No valid project");
      const projectId = current || (projects.length === 1 ? String(projects[0].project_id) : "");
      if (!projectId) { status.textContent = "No valid project; downstream context requests were skipped"; ["timeline", "chapter", "source", "run"].forEach((key) => setOptions(el(key), [], "", "Select a project first")); return; }
      const chapter = params().get("chapter_id");
      const suffix = chapter ? `&chapter_id=${encodeURIComponent(chapter)}` : "";
      const result = await get(`/api/simulator/context?project_id=${encodeURIComponent(projectId)}&timeline_id=main${suffix}`, controller.signal);
      if (mine !== generation) return;
      const currentParams = params();
      window.__storyosSimulatorContext = { scope_project_id: result.project?.scope_project_id || "", source_available: result.source_available !== false, project_id: projectId, timeline_id: currentParams.get("timeline_id") || "main", chapter_id: result.selected_chapter_id || null };
      window.dispatchEvent(new CustomEvent("storyos:panel-context-ready", { detail: window.__storyosSimulatorContext }));
      setOptions(el("timeline"), (result.timelines || []).map((item) => ({ value: item.timeline_id, label: label(item.title, item.timeline_id) })), currentParams.get("timeline_id"), "No timeline");
      setOptions(el("chapter"), (result.chapters || []).map((item) => ({ value: String(item.chapter_id), label: `Chapter ${item.chapter_id}${item.title ? ` · ${item.title}` : ""}` })), currentParams.get("chapter_id") || String(result.selected_chapter_id || ""), "No chapter");
      const sourceOptions = (result.source_versions || []).filter((item) => item.source_version_id).map((item) => ({ value: item.source_version_id, label: `${item.source_type} · ${item.version_label || item.version}` }));
      setOptions(el("source"), [{ value: "", label: "Automatic current source" }].concat(sourceOptions), currentParams.get("source_version_id"), "No selectable source version");
      setOptions(el("run"), [{ value: "", label: "Automatic" }].concat((result.panel_runs || []).map((item) => ({ value: item.panel_execution_id, label: `${item.panel_execution_id} · ${item.status}/${item.staleness}` }))), currentParams.get("panel_execution_id"), "No saved run");
      status.textContent = `Current project: ${label(result.project && result.project.title)} · read-only navigator`;
      if (!currentParams.get("project") || !currentParams.get("chapter_id")) {
        const view = currentParams.get("view");
        updateUrl({
          project: projectId,
          project_id: projectId,
          timeline_id: "main",
          chapter_id: String(result.selected_chapter_id || ""),
          source_version_id: "",
          panel_execution_id: "",
          ...(view ? { view } : {}),
        });
      }
    } catch (error) {
      if (error.name !== "AbortError") status.textContent = `Context load failed: ${label(error.message, "unknown error")}`;
    }
  }
  function rebind(changes) {
    const allowed = {};
    ["project", "project_id", "timeline_id", "branch_id", "chapter_id", "source_version_id", "panel_execution_id", "view", "turn_id", "action_id"].forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(changes || {}, key)) allowed[key] = changes[key];
    });
    if (allowed.project_id && !allowed.project) allowed.project = allowed.project_id;
    updateUrl(allowed);
  }
  function init() { installHistoryContextBridge(); bindChanges(); window.addEventListener("popstate", load); window.addEventListener("storyos:dashboard-ready", load); window.addEventListener("storyos:panel-run-created", load); load(); }
  window.StoryOSContextNavigator = { rebind, load, readCanonicalProjectIdentity };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
