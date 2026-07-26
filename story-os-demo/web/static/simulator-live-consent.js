(function () {
  "use strict";

  const PROFILE_URL = "/api/reader-persona/live/profiles";
  const CONSENT_URL = "/api/reader-persona/model-panel/live/consent";
  const RUN_URL = "/api/reader-persona/model-panel/live/runs";
  const STATUS_URL = "/api/reader-persona/model-panel/live/status/";
  const CONSENT_TEXT_VERSION = "0D3C2-B-1";
  const ids = {
    open: "simulator-live-consent-open", openReason: "simulator-live-consent-open-reason", dialog: "simulator-live-consent-dialog", close: "simulator-live-consent-close",
    summary: "simulator-live-consent-summary", error: "simulator-live-consent-error", scope: "simulator-live-consent-scope",
    profile: "simulator-live-profile", profileDetail: "simulator-live-profile-detail", budget: "simulator-live-budget",
    personas: "simulator-live-persona-options", personaCount: "simulator-live-persona-count", check: "simulator-live-consent-checkbox",
    submit: "simulator-live-consent-submit", submitReason: "simulator-live-consent-submit-reason", status: "simulator-live-consent-status",
    ticket: "simulator-live-ticket-result", reset: "simulator-live-consent-reset", execution: "simulator-live-execution", capability: "simulator-live-execution-capability", executionCheck: "simulator-live-execution-checkbox", executionSubmit: "simulator-live-execution-submit", executionReason: "simulator-live-execution-submit-reason", executionStatus: "simulator-live-execution-status", recovery: "simulator-live-recovery"
  };
  const $ = (key) => document.getElementById(ids[key]);
  let profiles = [];
  let personas = [];
  let selectedProfile = "";
  let selectedPersonaIds = [];
  let maxCalls = 0;
  let privateTicket = null;
  let privateProjectKey = "";
  let privateExecutionScope = null;
  let privateExecutionContextKey = "";
  let contextFingerprint = "";
  let generation = 0;
  let controller = null;
  let opener = null;
  let busy = false;
  let ticketExpiryTimer = null;
  let authoritativeContextReady = false;
  let issuedSelectionFingerprint = "";
  let consentIssuedForFingerprint = "";
  let consentState = "idle";
  let capabilityEnabled = false;
  let capabilityStatus = "disabled";
  let capabilityCode = "LIVE_EXECUTION_DISABLED";
  let executionState = "disabled";
  let executionController = null;
  let executionGeneration = 0;

  function context() {
    const value = window.__storyosSimulatorContext || {};
    const query = new URLSearchParams(window.location.search);
    const projectKey = String(value.scope_project_id || value.project_id || query.get("project") || "").trim();
    const timelineId = String(value.timeline_id || query.get("timeline_id") || "main").trim();
    const chapterRaw = value.chapter_id || query.get("chapter_id") || "";
    const chapterId = Number(chapterRaw);
    const sourceVersionId = String(query.get("source_version_id") || "").trim();
    const sourceAvailable = value.source_available !== false;
    return { projectKey, timelineId, chapterId: Number.isInteger(chapterId) ? chapterId : 0, sourceVersionId, sourceAvailable };
  }
  function key(scope) { return [scope.projectKey, scope.timelineId, scope.chapterId, scope.sourceVersionId, scope.sourceAvailable, window.__storyosSimulatorContext?.source_fingerprint || ""].join("|"); }
  function text(node, value) { if (node) node.textContent = value == null ? "" : String(value); }
  function safeId(value) { const raw = String(value || ""); return raw.length > 10 ? `${raw.slice(0, 6)}…${raw.slice(-4)}` : "private ticket"; }
  function safeDate(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? "Not provided" : date.toLocaleString(); }
  function resultOf(payload) { return payload && payload.result ? payload.result : payload || {}; }
  function errorMessage(error) { return error && error.message ? String(error.message) : "Request failed"; }
  function setError(message) { text($("error"), message || ""); }
  function setStatus(message) { text($("status"), message || ""); }
  function setState(next) { consentState = next; const ticket = $("ticket"); if (ticket) ticket.dataset.state = next; }
  function setBusy(value) { busy = value; const button = $("submit"); if (button) button.disabled = value || !canSubmit(); }
  function scopeReady(scope) { return Boolean(authoritativeContextReady && scope.projectKey && scope.timelineId && scope.chapterId > 0 && scope.sourceAvailable); }
  function currentProfile() { return profiles.find((item) => item.profile_id === selectedProfile) || null; }
  function selectedPersonas() { return personas.filter((item) => selectedPersonaIds.includes(item.persona_id)); }
  function selectionFingerprint() {
    const scope = context(); const profile = currentProfile();
    return JSON.stringify({ project: scope.projectKey, timeline: scope.timelineId, chapter: scope.chapterId, source: scope.sourceVersionId, source_available: scope.sourceAvailable, source_fingerprint: window.__storyosSimulatorContext?.source_fingerprint || null, personas: selectedPersonaIds, profile: profile?.profile_id || "", max_calls: Number(document.getElementById("simulator-live-call-limit")?.value || maxCalls || 0), consent_text_version: CONSENT_TEXT_VERSION });
  }
  function entryReady() { return scopeReady(context()); }
  function canSubmit() { const profile = currentProfile(); const fingerprint = selectionFingerprint(); return Boolean(!busy && entryReady() && profile && profile.ready_for_consent === true && selectedPersonaIds.length >= 1 && selectedPersonaIds.length <= 5 && $("check")?.checked && consentIssuedForFingerprint !== fingerprint); }

  function renderScope() {
    const scope = context();
    const source = scope.sourceAvailable ? (scope.sourceVersionId || "automatic current") : "source_missing";
    text($("scope"), `Scope · project ${scope.projectKey || "not selected"} · timeline ${scope.timelineId || "not selected"} · chapter ${scope.chapterId || "not selected"} · source ${source}`);
    const open = $("open"); if (open) open.disabled = !entryReady();
    text($("openReason"), entryReady() ? "Authoritative context ready; review remains read-only." : (authoritativeContextReady ? (scope.sourceAvailable ? "Select a project, timeline, and chapter." : "Source is unavailable; Live consent is blocked.") : "Waiting for authoritative project context."));
  }
  function renderProfile() {
    const select = $("profile");
    if (!select) return;
    select.replaceChildren();
    if (!profiles.length) { select.append(new Option("No public Live profiles", "")); select.disabled = true; selectedProfile = ""; }
    profiles.forEach((profile) => {
      const option = new Option(profile.display_name || profile.profile_id, profile.profile_id);
      option.disabled = profile.ready_for_consent !== true;
      select.append(option);
    });
    const firstReady = profiles.find((item) => item.ready_for_consent === true);
    if (!firstReady) { selectedProfile = ""; select.value = ""; select.disabled = true; }
    else { selectedProfile = profiles.some((item) => item.profile_id === selectedProfile && item.ready_for_consent === true) ? selectedProfile : firstReady.profile_id; select.value = selectedProfile; select.disabled = false; }
    updateProfileDetail();
  }
  function updateProfileDetail() {
    const profile = currentProfile();
    if (!profile) { text($("profileDetail"), "Live is blocked: INPUT_TOKEN_BUDGET_UNAVAILABLE until the server exposes an exact input-token counter."); text($("budget"), "No ready profile. The server will not estimate tokens or cost in the client."); maxCalls = 0; updateSubmitState(); return; }
    const readiness = profile.ready_for_consent === true ? "Provider readiness passed" : `Blocked: ${profile.safe_readiness_code || profile.readiness_code || "profile not ready"}`;
    if (profile.token_budget_mode === "conservative") {
      text($("profileDetail"), `${profile.provider_label || "DeepSeek"} · ${profile.model_label || "deepseek-v4-flash"} · 保守 Token 预算 · 不是 Provider 精确计数 · Strict Policy · ${readiness} · 生产 Live 仍关闭`);
      maxCalls = Number(profile.max_provider_calls || 0);
      const conservativeBudget = [
        "保守 Token 预算",
        "不是 Provider 精确计数",
        "Strict Policy",
        `文本上限：${profile.max_text_tokens == null ? "未提供" : profile.max_text_tokens}`,
        `保守输入上限：${profile.max_conservative_input_tokens == null ? "未提供" : profile.max_conservative_input_tokens}`,
        `输出上限：${profile.max_output_tokens == null ? "未提供" : profile.max_output_tokens}`,
        "Thinking：明确关闭",
        "Structured Output：JSON Object",
        "费用估算不可用",
        "生产 Live 仍关闭",
      ];
      const conservativeTarget = $("budget");
      conservativeTarget.replaceChildren();
      conservativeBudget.forEach((line) => {
        const item = document.createElement("div");
        item.textContent = line;
        conservativeTarget.append(item);
      });
      updateSubmitState();
      return;
    }
    const counter = profile.exact_token_counter_available === true ? `exact counter ${profile.counter_label || "available"} ${profile.counter_revision_short || ""}`.trim() : "exact counter unavailable";
    const capability = profile.ready_for_consent === true && profile.ready_for_live_execution !== true ? "Production Live remains disabled" : "";
    text($("profileDetail"), `${profile.provider_label || "Provider"} · ${profile.model_label || "model"} · ${counter} · timeout ${profile.timeout_seconds}s · registry ${String(profile.registry_revision || "").slice(0, 12)} · ${readiness}${capability ? ` · ${capability}` : ""}`);
    maxCalls = Number(profile.max_provider_calls || 0);
    const budget = [
      `Max Provider calls: ${maxCalls || "not provided"}`,
      `Max input tokens: ${profile.max_input_tokens == null ? "not provided" : profile.max_input_tokens}`,
      `Max output tokens: ${profile.max_output_tokens == null ? "not provided" : profile.max_output_tokens}`,
      `Max total tokens: ${profile.max_total_tokens == null ? "not provided" : profile.max_total_tokens}`,
      `Timeout: ${profile.timeout_seconds == null ? "not provided" : `${profile.timeout_seconds}s`}`,
      "Retry: 0 · Fallback: none",
      profile.cost_estimate_available === true ? `Max estimated cost: ${profile.max_estimated_cost}` : "Cost estimate unavailable"
    ];
    const target = $("budget"); target.replaceChildren(); budget.forEach((line) => { const item = document.createElement("div"); item.textContent = line; target.append(item); });
    updateSubmitState();
  }
  function renderPersonas() {
    const target = $("personas"); if (!target) return; target.replaceChildren();
    personas.slice(0, 5).forEach((persona, index) => {
      const label = document.createElement("label"); label.className = "storyos-live-persona-option";
      const input = document.createElement("input"); input.type = "checkbox"; input.value = persona.persona_id; input.checked = selectedPersonaIds.includes(persona.persona_id); input.disabled = persona.enabled === false; input.addEventListener("change", () => {
        selectedPersonaIds = Array.from(target.querySelectorAll("input:checked")).map((item) => item.value).slice(0, 5); invalidateConsent("Persona selection changed; create a new consent ticket."); renderPersonas(); updateSubmitState();
      });
      const copy = document.createElement("span"); copy.textContent = `${index + 1}. ${persona.display_name || persona.persona_id}`; const detail = document.createElement("small"); detail.textContent = persona.short_description || "Server-ordered Persona"; copy.append(detail); label.append(input, copy); target.append(label);
    });
    text($("personaCount"), `${selectedPersonaIds.length} / 5`);
  }
  function renderCalls() {
    const profile = currentProfile();
    const requested = Number($("submit")?.dataset.maxCalls || maxCalls || 0);
    if (!profile || !maxCalls) return;
    const old = document.getElementById("simulator-live-call-limit"); if (old) old.remove();
    const select = document.createElement("select"); select.id = "simulator-live-call-limit"; select.setAttribute("aria-label", "Requested maximum Provider calls");
    for (let value = 1; value <= maxCalls; value += 1) select.append(new Option(String(value), String(value)));
    select.value = String(Math.min(Math.max(requested || maxCalls, 1), maxCalls)); select.addEventListener("change", () => { $("submit").dataset.maxCalls = select.value; invalidateConsent("Requested call limit changed; create a new consent ticket."); updateSubmitState(); });
    const budget = $("budget"); if (budget) { const row = document.createElement("div"); row.className = "storyos-live-call-limit-row"; row.append(document.createTextNode("Requested calls (can only lower policy): "), select); budget.append(row); }
  }
  function updateSubmitState() {
    const ready = canSubmit(); const button = $("submit"); if (button) button.disabled = !ready; const reason = $("submitReason");
    if (reason) text(reason, ready ? "Explicit consent is required once; no execution follows." : (consentIssuedForFingerprint === selectionFingerprint() ? "Ticket already created for this selection. Change a selection or start a new review." : (currentProfile() && currentProfile().readiness_code ? `Blocked: ${currentProfile().readiness_code}` : "Select a ready profile, personas, and explicit consent.")));
  }
  function executionCanSubmit() { const fingerprint = selectionFingerprint(); return Boolean(capabilityEnabled && privateTicket && privateTicket.status === "issued" && issuedSelectionFingerprint === fingerprint && executionState === "ready" && $("executionCheck")?.checked); }
  function renderExecution() {
    const area = $("execution"); if (!area) return;
    area.classList.toggle("hidden", !privateTicket && !["response_uncertain", "recovering", "in_progress"].includes(executionState));
    text($("capability"), capabilityEnabled ? "Server capability enabled. A second confirmation is still required." : "Live execution is currently disabled by the server capability gate.");
    const check = $("executionCheck"); if (check) check.disabled = !capabilityEnabled || !privateTicket || executionState !== "ready";
    const submit = $("executionSubmit"); if (submit) submit.disabled = !executionCanSubmit();
    const reason = $("executionReason"); if (reason) text(reason, capabilityEnabled ? (executionState === "ready" ? "This submits exactly one Live Panel Run; no retry or fallback follows." : "Execution is already submitted or awaiting recovery.") : "LIVE_EXECUTION_DISABLED: server capability must be enabled.");
    const recovery = $("recovery"); if (recovery) recovery.classList.toggle("hidden", !["response_uncertain", "in_progress", "reconciling"].includes(executionState));
  }
  function setExecutionStatus(message) { text($("executionStatus"), message || ""); }
  function clearExecutionState() { executionGeneration += 1; if (executionController) executionController.abort(); executionController = null; executionState = capabilityEnabled ? "ready" : "disabled"; setExecutionStatus(""); if ($("executionCheck")) $("executionCheck").checked = false; renderExecution(); }
  function clearTicketExpiryTimer() { if (ticketExpiryTimer !== null) { window.clearTimeout(ticketExpiryTimer); ticketExpiryTimer = null; } }
  function clearTicketDom() { const ticket = $("ticket"); if (ticket) { ticket.classList.add("hidden"); ticket.replaceChildren(); delete ticket.dataset.state; } $("reset")?.classList.add("hidden"); clearExecutionState(); $("execution")?.classList.add("hidden"); }
  function invalidateConsent(reason) {
    const preserveRecovery = privateTicket && ["submitting", "in_progress", "response_uncertain", "recovering", "reconciling"].includes(executionState);
    generation += 1; if (controller) controller.abort(); controller = null; busy = false; clearTicketExpiryTimer();
    if (preserveRecovery) { executionGeneration += 1; if (executionController) executionController.abort(); executionController = null; executionState = "response_uncertain"; if ($("executionCheck")) $("executionCheck").checked = false; setExecutionStatus("Context changed while execution was submitted. The server may still be running; use recovery, never submit again."); renderExecution(); setState("invalidated"); setStatus(reason || "Context changed; execution handle preserved for recovery."); return; }
    privateTicket = null; privateProjectKey = ""; privateExecutionScope = null; privateExecutionContextKey = ""; issuedSelectionFingerprint = ""; consentIssuedForFingerprint = ""; clearTicketDom(); if ($("check")) $("check").checked = false; setState("invalidated"); setStatus(reason || "Selection changed; create a new consent ticket."); updateSubmitState();
  }
  function clearPrivateState(reason) { invalidateConsent(reason || "Live preparation reset for the new context."); setError(""); }
  function invalidateIfContextChanged() { const next = key(context()); if (next === contextFingerprint) return; contextFingerprint = next; profiles = []; personas = []; selectedPersonaIds = []; selectedProfile = ""; clearPrivateState("Context changed; create a new consent ticket."); renderScope(); renderProfile(); renderPersonas(); updateSubmitState(); text($("summary"), "Live preparation reset for the new context. Mock remains local-only."); }
  function expireTicket() { if (!privateTicket) return; clearTicketExpiryTimer(); privateTicket = null; privateProjectKey = ""; privateExecutionScope = null; privateExecutionContextKey = ""; issuedSelectionFingerprint = ""; consentIssuedForFingerprint = ""; clearTicketDom(); if ($("check")) $("check").checked = false; setState("expired"); setStatus("Consent ticket expired; create a new consent ticket."); text($("summary"), "Consent ticket expired; no execution was performed."); updateSubmitState(); }
  function scheduleTicketExpiry(expiresAt) {
    clearTicketExpiryTimer(); const timestamp = Date.parse(expiresAt); if (!Number.isFinite(timestamp)) { expireTicket(); return; }
    const delay = timestamp - Date.now(); if (delay <= 0) { expireTicket(); return; }
    const nextDelay = Math.min(delay, 2147483647); ticketExpiryTimer = window.setTimeout(() => { ticketExpiryTimer = null; if (delay > nextDelay) scheduleTicketExpiry(expiresAt); else expireTicket(); }, nextDelay);
  }
  function reconcileTicketExpiry() { if (!privateTicket) return; const timestamp = Date.parse(privateTicket.expires_at); if (!Number.isFinite(timestamp) || timestamp <= Date.now()) expireTicket(); else scheduleTicketExpiry(privateTicket.expires_at); }
  async function loadPlanData() {
    invalidateIfContextChanged(); const scope = context(); if (!scopeReady(scope)) { setError(scope.sourceAvailable ? "Select a project, timeline, and chapter before reviewing Live Plan." : "SOURCE_MISSING: Live consent is unavailable for this context."); return; }
    const mine = ++generation; if (controller) controller.abort(); controller = new AbortController(); setState("loading"); setError(""); setStatus("Loading safe profiles and Persona options…");
    try {
      const [profilePayload, personaPayload] = await Promise.all([window.storyosApiRequest(PROFILE_URL, { signal: controller.signal }), window.storyosApiRequest("/api/reader-persona/options", { signal: controller.signal })]);
      if (mine !== generation) return;
      const profileResult = resultOf(profilePayload); const personaResult = resultOf(personaPayload);
      const capability = profileResult.capability || {};
      capabilityEnabled = capability.enabled === true;
      capabilityStatus = String(capability.status || (capabilityEnabled ? "enabled" : "disabled"));
      capabilityCode = String(capability.safe_error_code || (capabilityEnabled ? "" : "LIVE_EXECUTION_DISABLED"));
      profiles = Array.isArray(profileResult.profiles) ? profileResult.profiles : []; personas = (Array.isArray(personaResult.personas) ? personaResult.personas : []).filter((item) => item && item.persona_id && item.enabled !== false).slice(0, 5);
      selectedPersonaIds = personas.map((item) => item.persona_id); renderProfile(); renderPersonas(); renderCalls(); setState("reviewing"); setStatus(profiles.length ? "Safe server projections loaded. Review before explicit consent." : "No public Live profile is available."); updateSubmitState(); renderExecution();
    } catch (error) { if (error.name !== "AbortError" && mine === generation) { setState("error"); setError(errorMessage(error)); setStatus(""); } }
  }
  function open() { opener = $("open"); invalidateIfContextChanged(); reconcileTicketExpiry(); if (!entryReady()) { renderScope(); return; } const dialog = $("dialog"); if (!dialog) return; dialog.showModal(); loadPlanData(); $("close")?.focus(); }
  function close() { clearTicketExpiryTimer(); const dialog = $("dialog"); if (dialog?.open) dialog.close(); opener?.focus(); }
  function startNewConsentReview() { invalidateConsent("New consent review started; confirm again before creating a ticket."); setError(""); if (!$("dialog")?.open) $("dialog")?.showModal(); $("check")?.focus(); }
  async function submitConsent() {
    if (!canSubmit() || busy) return; const scope = context(); const mine = generation; const profile = currentProfile(); const calls = Number(document.getElementById("simulator-live-call-limit")?.value || maxCalls); const fingerprint = selectionFingerprint();
    setBusy(true); setState("submitting"); setError(""); setStatus("Creating a server-owned consent ticket; no model call will be made…");
    try {
      const payload = await window.storyosApiRequest(CONSENT_URL, { method: "POST", signal: controller?.signal, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_key: scope.projectKey, chapter_id: scope.chapterId, source_version_id: scope.sourceVersionId || null, persona_ids: selectedPersonaIds.slice(0, 5), profile_id: profile.profile_id, max_provider_calls: calls, consent_text_version: CONSENT_TEXT_VERSION }) });
      if (mine !== generation) return; const result = resultOf(payload); privateTicket = result.ticket || null; if (!privateTicket) throw new Error("LIVE_CONSENT_REJECTED");
      const expiresAt = Date.parse(privateTicket.expires_at); if (!Number.isFinite(expiresAt) || expiresAt <= Date.now()) { expireTicket(); return; }
      privateProjectKey = scope.projectKey; privateExecutionScope = { projectKey: scope.projectKey, timelineId: scope.timelineId, chapterId: scope.chapterId }; privateExecutionContextKey = key(scope); issuedSelectionFingerprint = fingerprint; consentIssuedForFingerprint = fingerprint; if ($("check")) $("check").checked = false; executionState = capabilityEnabled ? "ready" : "disabled"; setState("issued"); scheduleTicketExpiry(privateTicket.expires_at);
      const ticket = $("ticket"); ticket.replaceChildren(); const lines = [`Consent ticket created · ${safeId(privateTicket.ticket_id)}`, `Status: ${privateTicket.status || "issued"}`, `Issued: ${safeDate(privateTicket.issued_at)} · Expires: ${safeDate(privateTicket.expires_at)}`, `Server order: ${(privateTicket.ordered_persona_ids || []).join(", ") || "Not provided"}`, "Provider calls: 0 · Token usage: 0 · No model executed", "Private ticket and request key remain memory-only in this panel."]; lines.forEach((line) => { const item = document.createElement("div"); item.textContent = line; ticket.append(item); }); ticket.classList.remove("hidden"); setStatus("Live consent ticket created; Live Run remains disabled in this phase."); text($("summary"), "Consent ticket created · no model executed · Provider calls 0 · Token 0.");
      $("reset")?.classList.remove("hidden"); renderExecution();
    } catch (error) { if (error.name !== "AbortError" && mine === generation) { setState("error"); setError(errorMessage(error)); } } finally { if (mine === generation) { setBusy(false); updateSubmitState(); } }
  }
  function finalExecutionStatus(status) { return ["completed", "partially_completed", "failed", "blocked", "expired", "cancelled", "cancel_requested"].includes(status); }
  function safeExecutionId(value) { const raw = String(value || ""); return /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(raw) ? raw : ""; }
  function clearPrivateExecutionHandle() { clearTicketExpiryTimer(); privateTicket = null; privateProjectKey = ""; privateExecutionScope = null; privateExecutionContextKey = ""; issuedSelectionFingerprint = ""; consentIssuedForFingerprint = ""; if ($("executionCheck")) $("executionCheck").checked = false; }
  function handoffFinal(result) {
    const status = String(result.status || "failed"); const executionId = safeExecutionId(result.panel_execution_id);
    const issuedScope = privateExecutionScope; const issuedContextKey = privateExecutionContextKey; const contextStillCurrent = Boolean(issuedScope && issuedContextKey && issuedContextKey === key(context()));
    clearPrivateExecutionHandle(); executionState = status; setExecutionStatus(executionId ? `Live Run ${executionId} is ${status}. Loading explicit Review…` : `Live Run is ${status}. No automatic retry will be attempted.`); renderExecution();
    if (!executionId) return;
    if (!contextStillCurrent) { setExecutionStatus(`Live Run ${executionId} is ${status}, but the context changed. Return to the original context and use Saved Runs; no cross-context handoff was performed.`); return; }
    const url = new URL(window.location.href); url.searchParams.set("mode", "simulator"); url.searchParams.set("view", "reader-panel-review"); url.searchParams.set("project", issuedScope.projectKey); url.searchParams.set("timeline_id", issuedScope.timelineId); url.searchParams.set("chapter_id", String(issuedScope.chapterId)); url.searchParams.set("panel_execution_id", executionId); window.history.pushState({}, "", url); window.dispatchEvent(new CustomEvent("storyos:panel-run-created", { detail: { execution_id: executionId, mode: "live" } })); window.dispatchEvent(new PopStateEvent("popstate"));
  }
  function handleExecutionResult(result) {
    const status = String(result && result.status || "unknown");
    if (finalExecutionStatus(status)) { handoffFinal(result || {}); return; }
    if (status === "in_progress") { executionState = "in_progress"; setExecutionStatus("Live Panel Run is in progress. Do not submit again; use recovery if the response was lost."); renderExecution(); return; }
    if (status === "reconciliation_required") { executionState = "reconciling"; setExecutionStatus("Execution result is uncertain and requires reconciliation. Do not retry; use recovery or human review."); renderExecution(); return; }
    executionState = status === "issued" ? "response_uncertain" : "failed"; setExecutionStatus(status === "issued" ? "No execution ownership was confirmed. Do not submit again; use recovery." : `Live execution returned ${status}. No automatic retry or fallback will run.`); renderExecution();
  }
  async function executeLiveRun() {
    if (!executionCanSubmit() || !privateTicket || !privateTicket.idempotency_key) return;
    const mine = ++executionGeneration; const ticketId = privateTicket.ticket_id; const idempotencyKey = privateTicket.idempotency_key; const projectKey = privateProjectKey; executionState = "submitting"; if ($("executionCheck")) $("executionCheck").checked = false; setExecutionStatus("Submitting exactly one Live Panel Run…"); renderExecution(); executionController = new AbortController();
    try {
      const payload = await window.storyosApiRequest(RUN_URL, { method: "POST", signal: executionController.signal, headers: { "Content-Type": "application/json", "X-StoryOS-Idempotency-Key": idempotencyKey }, body: JSON.stringify({ project_key: projectKey, ticket_id: ticketId }) });
      if (mine !== executionGeneration) return; handleExecutionResult(resultOf(payload));
    } catch (error) {
      if (mine !== executionGeneration) return; executionState = "response_uncertain"; setExecutionStatus(error.name === "AbortError" ? "Stopped waiting for the execution response. The server may still be running; use recovery." : "Execution result is uncertain. Do not submit again; use recovery to query the server."); renderExecution();
    } finally { if (mine === executionGeneration) executionController = null; }
  }
  async function recoverLiveRun() {
    if (!privateTicket || !privateTicket.idempotency_key || !privateProjectKey || executionState === "recovering") return;
    const mine = ++executionGeneration; const ticketId = privateTicket.ticket_id; const idempotencyKey = privateTicket.idempotency_key; executionState = "recovering"; setExecutionStatus("Reading the existing Live execution state; no POST will be sent…"); renderExecution(); executionController = new AbortController();
    try {
      const url = `${STATUS_URL}${encodeURIComponent(ticketId)}?project_key=${encodeURIComponent(privateProjectKey)}`;
      const payload = await window.storyosApiRequest(url, { signal: executionController.signal, headers: { "X-StoryOS-Idempotency-Key": idempotencyKey } });
      if (mine !== executionGeneration) return; handleExecutionResult(resultOf(payload));
    } catch (error) { if (mine === executionGeneration) { executionState = "response_uncertain"; setExecutionStatus("Recovery could not confirm the execution. Do not submit another POST."); renderExecution(); } }
    finally { if (mine === executionGeneration) executionController = null; }
  }
  function handleAuthoritativeContext(event) {
    const detail = event?.detail || window.__storyosSimulatorContext || {};
    const project = String(detail.scope_project_id || detail.project_id || "").trim(); const timeline = String(detail.timeline_id || "").trim(); const chapter = Number(detail.chapter_id);
    authoritativeContextReady = Boolean(project && timeline && Number.isInteger(chapter) && chapter > 0 && typeof detail.source_available === "boolean");
    if (authoritativeContextReady) { window.__storyosSimulatorContext = detail; invalidateIfContextChanged(); renderScope(); updateSubmitState(); }
  }
  function init() {
    if (!$("open")) return; contextFingerprint = key(context()); renderScope(); renderPersonas(); updateSubmitState(); renderExecution(); $("open").addEventListener("click", open); $("close")?.addEventListener("click", close); $("reset")?.addEventListener("click", startNewConsentReview); $("submit")?.addEventListener("click", submitConsent); $("executionSubmit")?.addEventListener("click", executeLiveRun); $("recovery")?.addEventListener("click", recoverLiveRun); $("profile")?.addEventListener("change", (event) => { selectedProfile = event.target.value; invalidateConsent("Profile selection changed; create a new consent ticket."); renderProfile(); renderCalls(); }); $("executionCheck")?.addEventListener("change", renderExecution); $("check")?.addEventListener("change", updateSubmitState); $("dialog")?.addEventListener("cancel", (event) => { event.preventDefault(); close(); }); window.addEventListener("popstate", () => { authoritativeContextReady = false; invalidateIfContextChanged(); renderScope(); }); window.addEventListener("storyos:panel-context-ready", handleAuthoritativeContext); document.addEventListener("visibilitychange", () => { if (!document.hidden) { reconcileTicketExpiry(); renderScope(); updateSubmitState(); renderExecution(); } });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
