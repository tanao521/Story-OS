(function () {
  "use strict";

  // Phase 0D6-C-B: one explicit durable-start intent layered on the sealed
  // readiness surface. No authority is derived or persisted in the browser.
  const $ = (id) => document.getElementById(id);
  const state = {
    controller: null,
    startController: null,
    epoch: 0,
    contextKey: "",
    context: null,
    model: null,
    readiness: null,
    status: "UNAVAILABLE",
    errorCode: "",
    scheduled: null,
    scheduledForce: false,
    startIntent: null,
    activeStartPromise: null,
    startedResult: null,
    handoff: null,
    modelEpoch: 0,
    readinessModelEpoch: -1,
  };

  const PRESENTATION = {
    READY_TO_START_TURN: { category: "READY", title: "Next chapter is ready", message: "Starting will create the next chapter's initial action plan. It will not confirm any action automatically.", retryAllowed: false, existingTurnAllowed: false, severity: "positive" },
    TURN_ALREADY_STARTED: { category: "EXISTING_TURN", title: "An initial Turn already exists", message: "A durable initial Turn already exists for the next chapter. Continue it from the authoritative Turn workspace.", retryAllowed: false, existingTurnAllowed: true, severity: "positive" },
    BLOCKED_PREVIOUS_CHAPTER_NOT_COMPLETE: { category: "BLOCKED", title: "Previous chapter is not complete", message: "Complete and commit the current chapter before progression can continue.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_COMPLETION_RECOVERY_REQUIRED: { category: "RECOVERY_REQUIRED", title: "Completion recovery is required", message: "The chapter completion record is incomplete. Recheck the authoritative state after recovery.", retryAllowed: true, existingTurnAllowed: false, severity: "warning" },
    BLOCKED_TURN_START_INCOMPLETE: { category: "RECOVERY_REQUIRED", title: "Progression recovery is required", message: "A prior progression record is incomplete. Recheck the authoritative state before continuing.", retryAllowed: true, existingTurnAllowed: false, severity: "warning" },
    BLOCKED_LIFECYCLE_NOT_CREATED: { category: "BLOCKED", title: "Successor lifecycle is not available", message: "The successor chapter lifecycle has not been published by the authority.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_LIFECYCLE_INCOMPLETE: { category: "RECOVERY_REQUIRED", title: "Successor lifecycle is incomplete", message: "The successor lifecycle still requires recovery before its status can be used.", retryAllowed: true, existingTurnAllowed: false, severity: "warning" },
    BLOCKED_LIFECYCLE_CONFLICT: { category: "CORRUPT", title: "Lifecycle authority needs review", message: "Conflicting lifecycle records were detected. Recheck the authoritative state; no mutation is available here.", retryAllowed: true, existingTurnAllowed: false, severity: "error" },
    BLOCKED_SUCCESSOR_NOT_VISIBLE: { category: "BLOCKED", title: "Successor is not visible", message: "The authoritative successor is not visible in the current scope.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_SUCCESSOR_ASSETS_INCOMPLETE: { category: "BLOCKED", title: "Successor assets are incomplete", message: "The successor assets are not complete enough for a safe progression status.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_BRANCH_NOT_ACTIVE: { category: "BLOCKED", title: "Active branch required", message: "Select an active branch in Simulator mode before reading progression status.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_BRANCH_ARCHIVED: { category: "BLOCKED", title: "Branch is archived", message: "The current branch is archived and cannot advance this progression scope.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_BRANCH_AUTHORITY_CHANGED: { category: "BLOCKED", title: "Branch authority changed", message: "The branch authority changed since this context was read. Recheck status.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_PLANNING_MISSING: { category: "BLOCKED", title: "Planning context is missing", message: "The successor planning context is not available in the authoritative scope.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_PLANNING_STALE: { category: "BLOCKED", title: "Planning context is stale", message: "Refresh the authoritative context before progression can be considered ready.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_SOURCE_MISSING: { category: "BLOCKED", title: "Source is missing", message: "The authoritative source required for progression is unavailable.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_SOURCE_CHANGED: { category: "BLOCKED", title: "Source changed", message: "The source changed since the current context was read. Recheck status.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_CANON_CHANGED: { category: "BLOCKED", title: "Canon changed", message: "Canon changed since the current context was read. Recheck status.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_SCOPE_MISMATCH: { category: "BLOCKED", title: "Scope does not match", message: "The selected context does not match the progression authority.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_TIMELINE_UNSUPPORTED: { category: "BLOCKED", title: "Timeline is unsupported", message: "Cross-chapter progression is currently available only on the main timeline.", retryAllowed: true, existingTurnAllowed: false, severity: "blocked" },
    BLOCKED_EXISTING_TURN_CORRUPT: { category: "CORRUPT", title: "Existing Turn authority needs review", message: "The authority reports an invalid existing Turn record. Recheck status; no continuation is offered.", retryAllowed: true, existingTurnAllowed: false, severity: "error" },
    BLOCKED_CORRUPT_AUTHORITY: { category: "CORRUPT", title: "Progression authority needs review", message: "The progression authority could not be validated. Recheck status; no mutation is available here.", retryAllowed: true, existingTurnAllowed: false, severity: "error" },
    TURN_START_RECOVERY_REQUIRED: { category: "RECOVERY_REQUIRED", title: "Progression recovery is required", message: "A durable progression record needs review before its status can be trusted.", retryAllowed: true, existingTurnAllowed: false, severity: "warning" },
    CORRUPT_OPERATION: { category: "START_TERMINAL_ERROR", title: "Progression record is corrupt", message: "The durable start record could not be validated. Recheck readiness; do not repeat this intent.", retryAllowed: false, existingTurnAllowed: false, severity: "error" },
    TURN_START_SOURCE_CHANGED: { category: "STALE", title: "Progression context changed", message: "The authority changed while this start was being prepared. Recheck readiness before trying again.", retryAllowed: false, existingTurnAllowed: false, severity: "warning" },
    TURN_START_READINESS_CHANGED: { category: "STALE", title: "Progression readiness changed", message: "Readiness changed before the start completed. Recheck readiness before trying again.", retryAllowed: false, existingTurnAllowed: false, severity: "warning" },
    OPERATION_CONFLICT: { category: "START_TERMINAL_ERROR", title: "Start intent conflicts", message: "This operation ID is bound to another request. Recheck readiness before starting a new intent.", retryAllowed: false, existingTurnAllowed: false, severity: "error" },
  };

  const FALLBACK = {
    UNAVAILABLE: { category: "UNAVAILABLE", title: "Progression status unavailable", message: "Select a valid Simulator context on the main timeline with an active branch.", retryAllowed: false, existingTurnAllowed: false, severity: "muted" },
    LOADING_READINESS: { category: "LOADING_READINESS", title: "Reading progression status", message: "Checking the authoritative cross-chapter readiness record.", retryAllowed: false, existingTurnAllowed: false, severity: "muted" },
    STARTING: { category: "STARTING", title: "Preparing the next chapter", message: "The durable start is in progress. Repeated clicks are ignored.", retryAllowed: false, existingTurnAllowed: false, severity: "warning" },
    STARTED: { category: "STARTED", title: "Initial Turn started", message: "The successor context is opening with its initial Turn. No action is being confirmed automatically.", retryAllowed: false, existingTurnAllowed: false, severity: "positive" },
    HANDOFF_COMPLETE: { category: "HANDOFF_COMPLETE", title: "Initial Turn is active", message: "The successor Turn owns the workspace until its chapter is authoritatively completed.", retryAllowed: false, existingTurnAllowed: false, severity: "positive" },
    START_RETRYABLE_ERROR: { category: "START_RETRYABLE_ERROR", title: "Start result is unconfirmed", message: "The server may have completed the start. Retry safely with the same frozen request when ready.", retryAllowed: true, existingTurnAllowed: false, severity: "warning" },
    START_TERMINAL_ERROR: { category: "START_TERMINAL_ERROR", title: "Start needs attention", message: "The start intent ended without a safe result. Recheck readiness before creating a new intent.", retryAllowed: true, existingTurnAllowed: false, severity: "error" },
    STALE: { category: "STALE", title: "Progression context changed", message: "Recheck the current readiness before starting again.", retryAllowed: false, existingTurnAllowed: false, severity: "warning" },
    NETWORK_OR_ROUTE_ERROR: { category: "NETWORK_OR_ROUTE_ERROR", title: "Progression status could not be read", message: "The status request failed. Recheck readiness when the route is available.", retryAllowed: true, existingTurnAllowed: false, severity: "error" },
    CORRUPT: { category: "CORRUPT", title: "Progression authority needs review", message: "The response was not safe to use. Recheck status; no automatic repair is available here.", retryAllowed: true, existingTurnAllowed: false, severity: "error" },
  };

  function text(value, fallback = "") { return value === null || value === undefined || value === "" ? fallback : String(value); }
  function mode() { return new URLSearchParams(window.location.search).get("mode") || "traditional"; }
  function urlProjectIdentity() {
    const reader = window.StoryOSContextNavigator && window.StoryOSContextNavigator.readCanonicalProjectIdentity;
    if (typeof reader === "function") return reader();
    const params = new URLSearchParams(window.location.search);
    const project = params.get("project") || "";
    const projectId = params.get("project_id") || "";
    const mismatch = !!project && !!projectId && project !== projectId;
    return { project, project_id: projectId, canonical_project_id: mismatch ? "" : (projectId || project), consistent: !mismatch, mismatch };
  }
  function urlScope() {
    const params = new URLSearchParams(window.location.search);
    const identity = urlProjectIdentity();
    return { project_id: identity.consistent ? identity.canonical_project_id : "", timeline_id: params.get("timeline_id") || "", branch_id: params.get("branch_id") || "", chapter_id: Number(params.get("chapter_id") || 0), identity_consistent: identity.consistent };
  }
  function contextFromModel(model) {
    const scope = model && model.scope || {};
    const branch = model && model.branch || {};
    const url = urlScope();
    const context = {
      project_id: url.identity_consistent ? text(url.project_id, text(scope.project_id)) : "",
      timeline_id: text(url.timeline_id, text(scope.timeline_id, "main")),
      branch_id: text(url.branch_id, text(scope.branch_id)),
      previous_chapter_id: Number(url.chapter_id || scope.chapter_id || 0),
      active_branch: branch.active === true && (!branch.active_branch_id || String(branch.active_branch_id) === String(url.branch_id || scope.branch_id)),
    };
    context.key = [context.project_id, context.timeline_id, context.branch_id, context.previous_chapter_id].join("|");
    return context;
  }
  function validContext(context) { return mode() === "simulator" && !!context.project_id && context.timeline_id === "main" && !!context.branch_id && context.previous_chapter_id > 0 && context.active_branch === true; }
  function modelMatchesContext(context) {
    const scope = state.model && state.model.scope || {};
    return String(scope.project_id || "") === String(context.project_id)
      && String(scope.timeline_id || "main") === String(context.timeline_id)
      && String(scope.branch_id || "") === String(context.branch_id)
      && Number(scope.chapter_id || 0) === Number(context.previous_chapter_id);
  }
  function activeTurnOwnsWorkspace(context) {
    if (!modelMatchesContext(context)) return false;
    const chapter = state.model && state.model.chapter_progression || {};
    const currentTurn = state.model && state.model.turn && state.model.turn.current_turn || null;
    return chapter.completed !== true && !!currentTurn && Number(currentTurn.chapter_id) === Number(context.previous_chapter_id);
  }
  function handoffMatches(context) {
    return !!state.handoff && state.handoff.contextKey === context.key && !!state.handoff.turn_id;
  }
  function completionReleasesHandoff(context) {
    const chapter = state.model && state.model.chapter_progression || {};
    return handoffMatches(context) && modelMatchesContext(context) && chapter.completed === true;
  }
  function canOwnReadiness(context) {
    if (!validContext(context)) return false;
    if (handoffMatches(context) || !modelMatchesContext(context)) return false;
    // The sealed readiness endpoint remains the completion authority. The
    // read model decides only whether an active Turn already owns this scope.
    return !activeTurnOwnsWorkspace(context);
  }
  function announce(message, urgent) {
    const node = $("simulator-loop-status");
    if (node) { node.textContent = message; node.setAttribute("aria-live", urgent ? "assertive" : "polite"); }
  }
  function presentation() { return PRESENTATION[state.errorCode] || FALLBACK[state.status] || FALLBACK.CORRUPT; }
  function setStatus(status, errorCode = "") { state.status = status; state.errorCode = errorCode; render(); }
  function safeReason(code) { return (PRESENTATION[code] || FALLBACK.CORRUPT).message; }
  function scopeMatches(result, context) {
    return result && String(result.project_id) === String(context.project_id) && String(result.timeline_id || "main") === String(context.timeline_id) && String(result.branch_id) === String(context.branch_id) && Number(result.previous_chapter_id) === Number(context.previous_chapter_id);
  }
  function responseStillOwnsCurrentContext(epoch, context) {
    // The URL is the live navigation authority.  Rebuild the full context at
    // response time so a response cannot survive a same-project branch switch
    // merely because the previous simulator read model has not returned yet.
    if (epoch !== state.epoch || state.contextKey !== context.key) return false;
    return contextFromModel(state.model).key === context.key;
  }
  function startFieldsValid(result, intent) {
    return !!result && String(result.operation_id) === String(intent.snapshot.operation_id) && String(result.project_id) === String(intent.snapshot.project_id) && String(result.timeline_id || "main") === String(intent.snapshot.timeline_id) && String(result.branch_id) === String(intent.snapshot.branch_id) && Number(result.previous_chapter_id) === Number(intent.snapshot.previous_chapter_id) && Number(result.successor_chapter_id) === Number(intent.snapshot.successor_chapter_id) && String(result.readiness_fingerprint) === String(intent.snapshot.expected_readiness_fingerprint) && !!result.turn_id && result.turn_status === "awaiting_action";
  }
  async function parseResponse(response, fallbackCode) {
    const body = await response.text();
    let payload;
    try { payload = body ? JSON.parse(body) : null; } catch (_) { payload = null; }
    if (!payload) {
      const error = new Error("Response could not be read safely"); error.code = "RESPONSE_UNREADABLE"; error.ambiguous = true; error.status = response.status; throw error;
    }
    if (!response.ok || payload.ok === false) {
      const error = new Error(text(payload.message, text(payload.error && payload.error.message, "Start request failed")));
      error.code = text((payload.errors || [])[0], text(payload.error && payload.error.code, fallbackCode));
      error.status = response.status;
      error.ambiguous = response.status >= 500 && !["CORRUPT_OPERATION", "OPERATION_CONFLICT"].includes(error.code);
      throw error;
    }
    return payload.result || payload;
  }
  async function requestReadiness(context, signal) {
    const query = new URLSearchParams({ project_id: context.project_id, timeline_id: context.timeline_id, branch_id: context.branch_id, previous_chapter_id: String(context.previous_chapter_id) });
    const response = await fetch(`/api/chapter-progression/readiness?${query.toString()}`, { headers: { Accept: "application/json" }, cache: "no-store", signal });
    const result = await parseResponse(response, "NETWORK_OR_ROUTE_ERROR");
    if (!result || !scopeMatches(result, context) || typeof result.readiness_code !== "string") { const error = new Error("Readiness response could not be validated"); error.code = "CORRUPT"; throw error; }
    return result;
  }
  async function requestStart(snapshot, signal) {
    const response = await fetch("/api/chapter-progression/start-turn", { method: "POST", headers: { "Content-Type": "application/json", Accept: "application/json" }, body: JSON.stringify(snapshot), signal });
    return parseResponse(response, "START_REQUEST_FAILED");
  }
  function clearTransient() { state.readiness = null; state.errorCode = ""; }
  function clearStartIntent() { if (state.startController) state.startController.abort(); state.startController = null; state.startIntent = null; state.activeStartPromise = null; }
  function beginReadiness(context) {
    if (state.controller) state.controller.abort();
    const epoch = ++state.epoch;
    state.context = context;
    state.contextKey = context.key;
    clearTransient();
    state.status = "LOADING_READINESS";
    render();
    state.controller = new AbortController();
    requestReadiness(context, state.controller.signal).then((result) => {
      if (!responseStillOwnsCurrentContext(epoch, context)) return;
      state.readiness = result;
      state.errorCode = result.readiness_code;
      const safe = PRESENTATION[result.readiness_code];
      state.status = safe ? safe.category : "CORRUPT";
      if (state.status === "READY" && (!result.ready_to_start_turn || !result.successor_chapter_id || !/^[0-9a-f]{64}$/.test(String(result.authority_fingerprint || "")))) { state.status = "CORRUPT"; state.errorCode = "CORRUPT"; }
      if (!safe) state.errorCode = "CORRUPT";
      render(); announce(`Progression status: ${presentation().title}`);
    }).catch((error) => {
      if (error && error.name === "AbortError") return;
      if (!responseStillOwnsCurrentContext(epoch, context)) return;
      state.readiness = null;
      state.errorCode = PRESENTATION[error && error.code] ? error.code : "";
      state.status = state.errorCode ? PRESENTATION[state.errorCode].category : (error && error.code === "CORRUPT" ? "CORRUPT" : "NETWORK_OR_ROUTE_ERROR");
      render(); announce(`Progression status: ${presentation().title}`, true);
    });
  }
  function sync(force) {
    if (mode() !== "simulator") {
      if (state.controller) state.controller.abort();
      clearStartIntent(); state.context = null; state.contextKey = ""; state.model = null; state.readiness = null; state.startedResult = null;
      setStatus("UNAVAILABLE");
      return;
    }
    const context = contextFromModel(state.model);
    if (completionReleasesHandoff(context)) state.handoff = null;
    if (!canOwnReadiness(context)) {
      const changed = context.key !== state.contextKey;
      if (state.controller) state.controller.abort();
      if (changed) state.epoch += 1;
      clearStartIntent(); state.context = context; state.contextKey = context.key; state.startedResult = null; clearTransient();
      setStatus(handoffMatches(context) || activeTurnOwnsWorkspace(context) ? "HANDOFF_COMPLETE" : "UNAVAILABLE");
      return;
    }
    const changed = context.key !== state.contextKey;
    if (changed) {
      clearStartIntent(); state.startedResult = null;
      if (state.controller) state.controller.abort();
    }
    if (!changed && ["STARTING", "START_RETRYABLE_ERROR"].includes(state.status)) return;
    if (!force && !changed && context.key === state.contextKey && ["LOADING_READINESS", "READY", "EXISTING_TURN", "BLOCKED", "RECOVERY_REQUIRED", "CORRUPT", "NETWORK_OR_ROUTE_ERROR", "STARTING", "START_RETRYABLE_ERROR"].includes(state.status)) return;
    if (context.key !== state.contextKey || force || (state.status === "UNAVAILABLE" && state.readinessModelEpoch !== state.modelEpoch)) {
      state.readinessModelEpoch = state.modelEpoch;
      beginReadiness(context);
    }
  }
  function schedule(force) {
    state.scheduledForce = state.scheduledForce || !!force;
    if (state.scheduled) window.clearTimeout(state.scheduled);
    state.scheduled = window.setTimeout(() => { const requestedForce = state.scheduledForce; state.scheduled = null; state.scheduledForce = false; sync(requestedForce); }, 0);
  }
  function render() {
    const panel = $("simulator-chapter-progression");
    if (!panel) return;
    const view = presentation();
    const available = state.status !== "UNAVAILABLE" && mode() === "simulator";
    panel.classList.toggle("hidden", !available || state.status === "HANDOFF_COMPLETE");
    panel.dataset.progressionState = state.status;
    panel.setAttribute("aria-busy", String(state.status === "LOADING_READINESS" || state.status === "STARTING"));
    const title = $("simulator-chapter-progression-title");
    const status = $("simulator-chapter-progression-status");
    const badge = $("simulator-chapter-progression-badge");
    const scope = $("simulator-chapter-progression-scope");
    const reasons = $("simulator-chapter-progression-reasons");
    const existing = $("simulator-chapter-progression-existing");
    const existingSummary = $("simulator-chapter-progression-existing-summary");
    const start = $("simulator-chapter-progression-start");
    const refresh = $("simulator-chapter-progression-refresh");
    const legacyNext = document.querySelector("[data-legacy-next-chapter]");
    if (title) title.textContent = view.title;
    if (status) status.textContent = view.message;
    if (badge) { badge.textContent = view.category; badge.dataset.severity = view.severity; }
    if (scope) scope.textContent = state.context ? `Project ${text(state.context.project_id)} · main · Branch ${text(state.context.branch_id)} · Previous chapter ${text(state.context.previous_chapter_id)}` : "";
    if (reasons) {
      reasons.replaceChildren();
      const codes = state.readiness && Array.isArray(state.readiness.blocking_reasons) ? state.readiness.blocking_reasons : [];
      const shown = codes.map((code) => safeReason(String(code))).filter(Boolean).slice(0, 3);
      shown.forEach((message) => { const item = document.createElement("p"); item.textContent = message; reasons.append(item); });
    }
    const existingAllowed = state.status === "EXISTING_TURN" && view.existingTurnAllowed && state.readiness && state.readiness.existing_turn_id && state.readiness.successor_chapter_id;
    if (existing) existing.classList.toggle("hidden", !existingAllowed);
    if (existingSummary && existingAllowed) existingSummary.textContent = `Turn ${text(state.readiness.existing_turn_id)} · ${text(state.readiness.existing_turn_status, "status available")}`;
    const readyAllowed = state.status === "READY" && state.readiness && state.readiness.ready_to_start_turn === true && state.readiness.successor_chapter_id && /^[0-9a-f]{64}$/.test(String(state.readiness.authority_fingerprint || ""));
    const retryAllowed = state.status === "START_RETRYABLE_ERROR" && !!state.startIntent;
    if (start) { start.classList.toggle("hidden", !readyAllowed && !retryAllowed); start.disabled = state.status === "STARTING" || (!readyAllowed && !retryAllowed); start.textContent = retryAllowed ? "Retry start safely" : "Start next chapter"; }
    if (refresh) refresh.classList.toggle("hidden", (!view.retryAllowed && state.status !== "START_TERMINAL_ERROR") || state.status === "LOADING_READINESS" || state.status === "STARTING");
    if (legacyNext) legacyNext.classList.toggle("hidden", available);
  }
  function frozenSnapshot() {
    const context = state.context;
    const result = state.readiness;
    if (!context || !result || result.readiness_code !== "READY_TO_START_TURN" || result.ready_to_start_turn !== true || !result.successor_chapter_id || !/^[0-9a-f]{64}$/.test(String(result.authority_fingerprint || ""))) return null;
    const operationId = window.crypto && typeof window.crypto.randomUUID === "function" ? window.crypto.randomUUID() : `progression-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return Object.freeze({ operation_id: operationId, project_id: context.project_id, timeline_id: context.timeline_id, branch_id: context.branch_id, previous_chapter_id: context.previous_chapter_id, successor_chapter_id: Number(result.successor_chapter_id), expected_readiness_fingerprint: result.authority_fingerprint });
  }
  function startIntentForClick() {
    if (state.status === "START_RETRYABLE_ERROR" && state.startIntent) return state.startIntent;
    if (state.status !== "READY" || state.startIntent) return null;
    const snapshot = frozenSnapshot();
    if (!snapshot) { state.status = "START_TERMINAL_ERROR"; state.errorCode = "CORRUPT_OPERATION"; render(); return null; }
    state.startIntent = { snapshot, contextKey: state.contextKey, epoch: state.epoch };
    return state.startIntent;
  }
  function sameCurrentContext(intent) { return !!intent && mode() === "simulator" && state.context && state.contextKey === intent.contextKey && contextFromModel(state.model).key === intent.contextKey; }
  function focusTurnWorkspace() {
    [0, 120, 400].forEach((delay) => window.setTimeout(() => { const heading = $("nt-heading"); const workspace = $("narrative-turn-workspace"); if (heading && !heading.classList.contains("hidden")) heading.focus(); else if (workspace) workspace.focus(); }, delay));
  }
  function handoffToSuccessor(scope, successorChapterId, turnId) {
    const rebind = window.StoryOSContextNavigator && window.StoryOSContextNavigator.rebind;
    if (typeof rebind !== "function") { state.status = "START_TERMINAL_ERROR"; state.errorCode = "CORRUPT_OPERATION"; state.startedResult = null; render(); announce("The successor context rebind helper is unavailable.", true); return false; }
    const successorContext = { project_id: scope.project_id, timeline_id: scope.timeline_id, branch_id: scope.branch_id, previous_chapter_id: Number(successorChapterId) };
    successorContext.key = [successorContext.project_id, successorContext.timeline_id, successorContext.branch_id, successorContext.previous_chapter_id].join("|");
    state.status = "STARTED"; state.errorCode = ""; state.readiness = null;
    state.handoff = { contextKey: successorContext.key, turn_id: String(turnId), epoch: state.epoch + 1 };
    if (state.controller) state.controller.abort(); state.epoch += 1;
    clearStartIntent();
    render(); announce("Initial Turn started. Loading the successor Turn workspace.");
    rebind({ project: scope.project_id, project_id: scope.project_id, timeline_id: scope.timeline_id, branch_id: scope.branch_id, chapter_id: Number(successorChapterId), view: "narrative-turn", turn_id: turnId, action_id: null });
    focusTurnWorkspace();
    return true;
  }
  function rebindStarted(result, intent) {
    state.startedResult = result;
    handoffToSuccessor(intent.snapshot, result.successor_chapter_id, result.turn_id);
  }
  function handleStartError(error, intent) {
    if (!sameCurrentContext(intent)) { clearStartIntent(); state.startedResult = null; schedule(true); return; }
    const code = text(error && error.code, "START_REQUEST_FAILED");
    if (error && (error.ambiguous || !error.status || code === "RESPONSE_UNREADABLE" || code === "NETWORK_ERROR")) {
      state.status = "START_RETRYABLE_ERROR"; state.errorCode = ""; render(); announce("Start result is unconfirmed. The same frozen request can be retried safely.", true); return;
    }
    if (code === "TURN_ALREADY_STARTED" || code === "TURN_START_SOURCE_CHANGED" || code === "TURN_START_READINESS_CHANGED") {
      clearStartIntent(); state.status = "STALE"; state.errorCode = code; render(); beginReadiness(state.context); return;
    }
    clearStartIntent(); state.status = PRESENTATION[code] ? PRESENTATION[code].category : "START_TERMINAL_ERROR"; state.errorCode = PRESENTATION[code] ? code : ""; render(); announce(`Start needs attention: ${presentation().title}`, true);
  }
  function startFromIntent(intent) {
    if (state.activeStartPromise || !intent) return;
    state.status = "STARTING"; state.errorCode = ""; render(); announce("Preparing the next chapter…");
    state.startController = new AbortController();
    const promise = requestStart(intent.snapshot, state.startController.signal).then((result) => {
      if (!sameCurrentContext(intent)) { clearStartIntent(); state.startedResult = null; schedule(true); return; }
      if (!startFieldsValid(result, intent)) { const error = new Error("Start response could not be validated"); error.code = "CORRUPT_OPERATION"; handleStartError(error, intent); return; }
      rebindStarted(result, intent);
    }).catch((error) => {
      if (error && error.name === "AbortError") return;
      handleStartError(error, intent);
    }).finally(() => { state.activeStartPromise = null; state.startController = null; });
    state.activeStartPromise = promise;
  }
  function onStartClick() {
    if (state.activeStartPromise || state.status === "STARTING") return;
    const intent = startIntentForClick();
    if (intent) startFromIntent(intent);
  }
  function continueExistingTurn() {
    const result = state.readiness;
    if (state.status !== "EXISTING_TURN" || !result || !result.existing_turn_id || !result.successor_chapter_id || !state.context) return;
    if (result.existing_turn_status !== "awaiting_action") { state.status = "CORRUPT"; state.errorCode = "CORRUPT"; render(); announce("The existing Turn is not in a safe continuation state.", true); return; }
    handoffToSuccessor(state.context, result.successor_chapter_id, result.existing_turn_id);
  }
  function init() {
    $("simulator-chapter-progression-refresh")?.addEventListener("click", () => { if (state.status === "START_TERMINAL_ERROR") clearStartIntent(); schedule(true); });
    $("simulator-chapter-progression-start")?.addEventListener("click", onStartClick);
    $("simulator-chapter-progression-existing-continue")?.addEventListener("click", continueExistingTurn);
    window.addEventListener("storyos:simulator-state", (event) => {
      const wasCompleted = !!(state.model && state.model.chapter_progression && state.model.chapter_progression.completed);
      state.model = event.detail || null;
      state.modelEpoch += 1;
      const isCompleted = !!(state.model && state.model.chapter_progression && state.model.chapter_progression.completed);
      schedule(!wasCompleted && isCompleted);
    });
    window.addEventListener("storyos:panel-context-ready", () => schedule(false));
    window.addEventListener("popstate", () => schedule(false));
    window.addEventListener("storyos:dashboard-ready", () => schedule(false));
    render();
  }
  window.StoryOSChapterProgression = { init, refresh: () => schedule(true), getState: () => ({ status: state.status, readiness: state.readiness, context: state.context, startIntent: state.startIntent && { snapshot: state.startIntent.snapshot, contextKey: state.startIntent.contextKey } }) };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
