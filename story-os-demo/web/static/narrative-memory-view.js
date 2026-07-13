(() => {
  const $ = (selector) => document.querySelector(selector);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  const output = () => $("#narrative-memory-output");
  const chapterId = () => Math.max(1, Number($("#narrative-chapter-id")?.value || 1));

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    const body = await response.json();
    if (!body.ok) throw new Error((body.errors || [body.message || "Request failed."])[0]);
    return body.result || {};
  }

  function eventRow(event) {
    const status = event.confirmation_status || "unreviewed";
    const controls = status === "unreviewed"
      ? `<div class="narrative-row-actions"><button class="btn btn-secondary btn-compact" data-event-confirm="${esc(event.event_id)}">Confirm</button><button class="btn btn-link btn-compact" data-event-reject="${esc(event.event_id)}">Reject</button></div>`
      : `<span class="narrative-state narrative-state-${esc(status)}">${esc(status)}</span>`;
    return `<article class="narrative-event"><div class="narrative-event-marker" aria-hidden="true"></div><div class="narrative-event-copy"><b>${esc(event.event_type || "event")}</b><p>${esc(event.summary || "No event summary.")}</p><small>Chapter ${esc(event.chapter_id)} · ${esc(event.extraction_method || "rule")} candidate</small></div>${controls}</article>`;
  }

  function render(data) {
    const overview = data.overview || {};
    const events = data.events || [];
    const timeline = data.timeline || [];
    const conflicts = data.conflicts || [];
    output().innerHTML = `
      <div class="narrative-metrics">
        <div><b>${Number(overview.events || 0)}</b><span>active candidates</span></div>
        <div><b>${Number(overview.confirmed_events || 0)}</b><span>confirmed canon facts</span></div>
        <div><b>${timeline.length}</b><span>timeline entries</span></div>
        <div class="${conflicts.length ? "has-conflicts" : ""}"><b>${conflicts.length}</b><span>open conflicts</span></div>
      </div>
      <div class="narrative-ledger-grid">
        <section><header><span class="eyebrow">Event inbox</span><h3>Confirm what belongs to canon</h3></header><div class="narrative-event-list">${events.length ? events.map(eventRow).join("") : '<p class="empty-state">No candidates yet. Choose a chapter and extract candidates from its active canon text.</p>'}</div></section>
        <section><header><span class="eyebrow">Continuity watch</span><h3>Timeline and conflicts</h3></header><div class="narrative-timeline">${timeline.length ? timeline.slice(-8).map((item) => `<div><b>Ch. ${esc(item.chapter_id)}</b><span>${esc(item.summary)}</span></div>`).join("") : '<p class="empty-state">Confirmed events will form a chronological ledger here.</p>'}</div>${conflicts.length ? `<div class="narrative-conflicts">${conflicts.map((item) => `<p><b>${esc(item.severity)}</b> ${esc(item.type)}: ${esc(item.entity_id)}</p>`).join("")}</div>` : '<p class="narrative-clear">No blocking continuity conflicts.</p>'}</section>
      </div>`;
    output().querySelectorAll("[data-event-confirm]").forEach((button) => button.addEventListener("click", () => confirm(button.dataset.eventConfirm, "confirmed")));
    output().querySelectorAll("[data-event-reject]").forEach((button) => button.addEventListener("click", () => confirm(button.dataset.eventReject, "rejected")));
  }

  async function load() {
    try {
      const [overview, eventResult, timelineResult, conflictResult] = await Promise.all([
        api("/api/narrative-memory/overview"), api("/api/narrative-memory/events"),
        api("/api/narrative-memory/timeline"), api("/api/narrative-memory/conflicts"),
      ]);
      render({overview, events: eventResult.events, timeline: timelineResult.timeline, conflicts: conflictResult.conflicts});
    } catch (error) { output().textContent = `Narrative memory could not be loaded: ${error.message}`; }
  }

  async function confirm(eventId, decision) {
    try {
      await api(`/api/narrative-memory/events/${encodeURIComponent(eventId)}/confirm`, {method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({decision})});
      await load();
    } catch (error) { output().textContent = `Event was not changed: ${error.message}`; }
  }

  async function extract() {
    try {
      const result = await api(`/api/narrative-memory/chapters/${chapterId()}/extract`, {method:"POST"});
      await load();
      output().insertAdjacentHTML("afterbegin", `<p class="narrative-notice">Extracted ${result.events?.length || 0} candidates. Review them before they affect context.</p>`);
    } catch (error) { output().textContent = `Candidates were not extracted: ${error.message}`; }
  }

  async function preview() {
    try {
      const result = await api(`/api/narrative-memory/context-preview?chapter_id=${chapterId()}`);
      const selected = result.preview?.selected || [];
      output().insertAdjacentHTML("afterbegin", `<div class="narrative-preview"><b>Context preview for chapter ${chapterId()}</b><pre>${esc(JSON.stringify(selected, null, 2))}</pre></div>`);
    } catch (error) { output().textContent = `Context preview was not created: ${error.message}`; }
  }

  function init() {
    if (!output()) return;
    $("[data-narrative-refresh]")?.addEventListener("click", load);
    $("[data-narrative-extract]")?.addEventListener("click", extract);
    $("[data-narrative-preview]")?.addEventListener("click", preview);
    load();
  }
  document.addEventListener("DOMContentLoaded", init);
  window.addEventListener("storyos:project-changed", load);
  window.addEventListener("storyos:refresh-narrative-memory", load);
  window.addEventListener("storyos:project-cleared", () => { if (output()) output().textContent = "Project changed. Narrative memory will reload for the selected project."; });
})();
