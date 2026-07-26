/* Phase 0D4-C: Narrative Turn Workspace — production frontend module.
 *
 * Implements the 10 components defined in
 * docs/design/simulator_narrative_turn_component_contract.md:
 *   NarrativeTurnWorkspace, NarrativeSituationHeader,
 *   NarrativeEvidenceSummary, RecommendedActionGroup, RecommendedActionRow,
 *   CustomActionComposer, FeasibilityPanel, ConsequencePreview,
 *   TurnPrimaryAction, TurnStatusNotice.
 *
 * Security boundaries:
 * - Custom action raw text exists ONLY in textarea memory state + POST body.
 * - Never written to URL, localStorage, file, or log.
 * - Never echoed from response; only SHA-256 hash is shown.
 * - Browser never calls Python accessors; consumes only Wire DTOs.
 *
 * Race protection:
 * - AbortController per request group.
 * - Generation counter; responses with stale generation are silently discarded.
 *
 * URL state (only safe params):
 *   mode, view, project_id, timeline_id, branch_id, chapter_id,
 *   source_version_id, turn_id, action_id.
 * Forbidden in URL: custom_action_text, custom_action_text_hash,
 *   context_fingerprint, validation payload, preview payload.
 */
(function () {
  "use strict";

  const ID_PATTERN = /^[A-Za-z0-9_-]+$/;
  const FINGERPRINT_PATTERN = /^[0-9a-f]{64}$/;
  const MAX_CUSTOM_LENGTH = 200;
  const THRESHOLDS = [150, 190, 200, 201];

  const STATUS_LABEL = {
    allowed: "可用",
    allowed_with_cost: "带代价",
    requires_clarification: "需补充",
    blocked: "不可用",
  };
  const STATUS_ICON = {
    allowed: "◆",
    allowed_with_cost: "◇",
    requires_clarification: "◈",
    blocked: "×",
  };
  const STATUS_CLASS = {
    allowed: "nt-status-allowed",
    allowed_with_cost: "nt-status-cost",
    requires_clarification: "nt-status-clarify",
    blocked: "nt-status-blocked",
  };
  const REASON_TEXT = {
    ACTION_EMPTY: "行动为空",
    ACTION_TOO_LONG: "行动超过 200 字符上限",
    ACTION_UNPARSEABLE: "行动结构无法识别",
    ACTION_TARGET_AMBIGUOUS: "行动目标不明确",
    ACTION_OBJECT_AMBIGUOUS: "行动对象不明确",
    CONTEXT_STALE: "上下文已过期",
    SOURCE_STALE: "来源版本已变更",
    CONTEXT_INSUFFICIENT: "上下文证据不足",
    BRANCH_NOT_ACTIVE: "分支未激活",
    BRANCH_ARCHIVED: "分支已归档",
    WORLD_RULE_CONFLICT: "与世界规则冲突",
    CANON_CONFLICT: "与已确立 Canon 冲突",
    CAPABILITY_MISSING: "角色能力不足",
    RESOURCE_MISSING: "资源不存在",
    RESOURCE_COST_HIGH: "资源代价较高",
    LOCATION_MISMATCH: "位置不匹配",
    TIME_WINDOW_CLOSED: "时间窗口已关闭",
    RELATIONSHIP_PERMISSION_MISSING: "关系或权限不足",
    DEPENDENCY_BLOCKED: "前置依赖未完成",
  };

  // Module state
  const state = {
    generation: 0,
    controller: null,
    contextDto: null,
    planDto: null,
    validationDto: null,
    previewDto: null,
    selectedActionId: null,
    actionSource: null, // "recommended" | "custom" | null
    customText: "",
    lastThresholdAnnounced: null,
    branchOptions: [],
    confirmResultDto: null,
    confirmOperationId: null,
    confirmBusy: false,
  };

  // ---- DOM helpers -------------------------------------------------------

  function safeText(value, fallback = "未提供") {
    if (value === null || value === undefined || value === "") return fallback;
    return String(value);
  }

  function node(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = safeText(text);
    return el;
  }

  function clear(target) {
    while (target && target.firstChild) target.removeChild(target.firstChild);
  }

  function $(id) { return document.getElementById(id); }

  function shortenFp(fp) {
    if (typeof fp !== "string" || fp.length < 8) return "—";
    return fp.slice(0, 8);
  }

  // ---- URL state ---------------------------------------------------------

  function parseUrl() {
    const params = new URLSearchParams(window.location.search);
    const mode = params.get("mode") || "traditional";
    const view = params.get("view");
    const project_id = params.get("project_id") || "";
    const timeline_id = params.get("timeline_id") || "";
    const branch_id = params.get("branch_id") || "";
    const chapterRaw = params.get("chapter_id") || "";
    const source_version_id = params.get("source_version_id") || "";
    const turn_id = params.get("turn_id") || "";
    const action_id = params.get("action_id") || "";
    let chapter_id = 0;
    if (/^\d{1,7}$/.test(chapterRaw)) {
      chapter_id = Number(chapterRaw);
    }
    return {
      mode, view, project_id, timeline_id, branch_id,
      chapter_id, source_version_id, turn_id, action_id,
    };
  }

  function pushUrl(changes) {
    const next = new URLSearchParams(window.location.search);
    Object.entries(changes).forEach(([key, value]) => {
      if (value === null || value === "" ) next.delete(key);
      else next.set(key, String(value));
    });
    const url = `${window.location.pathname}?${next.toString()}${window.location.hash}`;
    window.history.pushState({}, "", url);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }

  // ---- API helpers -------------------------------------------------------

  async function apiGet(url, signal) {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      signal,
    });
    return await parseJsonSafely(response);
  }

  async function apiPost(url, body, signal) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      signal,
    });
    return await parseJsonSafely(response);
  }

  async function parseJsonSafely(response) {
    const text = await response.text();
    let data = {};
    if (text) {
      try { data = JSON.parse(text); } catch { data = {}; }
    }
    return { ok: response.ok, status: response.status, data };
  }

  function describeHttpError({ status, data }) {
    const err = (data && data.error) || {};
    const code = err.code || "INTERNAL_ERROR";
    const message = err.message || `HTTP ${status}`;
    return { code, message };
  }

  // ---- Component: TurnStatusNotice --------------------------------------
  // The ONLY business live region. Switches role="status" ↔ role="alert".

  function noticeAnnounce(message) {
    const el = $("nt-status-notice");
    if (!el) return;
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    el.textContent = message;
  }

  function noticeError(message) {
    const el = $("nt-status-notice");
    if (!el) return;
    el.setAttribute("role", "alert");
    el.setAttribute("aria-live", "assertive");
    el.textContent = message;
  }

  function noticeClear() {
    const el = $("nt-status-notice");
    if (!el) return;
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    el.textContent = "";
  }

  // ---- Component: NarrativeSituationHeader ------------------------------

  function renderSituationHeader(ctx) {
    const meta = $("nt-situation-meta");
    const chips = $("nt-situation-chips");
    if (!meta || !chips) return;
    clear(meta);
    clear(chips);

    const scope = ctx.scope || {};
    const branch = ctx.branch || {};

    meta.append(
      metaItem("Project", scope.project_id),
      metaItem("Timeline", scope.timeline_id),
      metaItem("Branch", scope.branch_id),
      metaItem("Chapter", `第 ${ctx.chapter_id} 章`),
      metaItem("Source", ctx.source_version_id || "当前源"),
      metaItem("Canon", shortenFp(ctx.canon_revision)),
      metaItem("Planner", ctx.planner_revision),
      metaItem("Audit", shortenFp(ctx.context_fingerprint), "上下文审计标记（非完整指纹）"),
    );

    // Branch lifecycle chip
    chips.append(chip(branch.lifecycle === "open" ? "open" : "archived",
      branch.lifecycle === "open" ? "nt-chip-gold" : "nt-chip-red"));
    chips.append(chip(branch.activity === "active" ? "active" : "inactive",
      branch.activity === "active" ? "nt-chip-gold" : "nt-chip-amber"));
    const nsd = branch.narrative_state_data || "unavailable";
    const nsdClass = nsd === "available" ? "nt-chip-gold"
      : nsd === "scope_mismatch" || nsd === "invalid" ? "nt-chip-red"
      : "nt-chip-amber";
    chips.append(chip(`state: ${nsd}`, nsdClass));

    // Limitations as muted chips
    (ctx.limitations || []).forEach((lim) => {
      chips.append(chip(lim, "nt-chip-muted"));
    });
  }

  function metaItem(label, value, title) {
    const wrap = node("div", "nt-situation-meta");
    const lab = node("span", "", label);
    const val = node("strong", "", value);
    if (title) val.title = title;
    wrap.append(lab, val);
    return wrap;
  }

  function chip(text, cls = "") {
    return node("span", `nt-chip ${cls}`.trim(), text);
  }

  // ---- Component: NarrativeEvidenceSummary ------------------------------

  function renderEvidenceSummary(ctx) {
    const body = $("nt-evidence-body");
    if (!body) return;
    clear(body);
    const sit = ctx.situation || {};
    const grid = node("div", "nt-evidence-grid");
    grid.append(
      evidenceItem("当前章节目标", sit.chapter_goal),
      evidenceList("当前冲突", sit.active_conflicts),
      evidenceList("角色与位置", mergeCharacterLocations(sit.characters, sit.locations)),
      evidenceList("可用资源", sit.resources),
      evidenceList("世界规则约束", sit.world_rules),
      evidenceList("未解决线索", sit.open_threads),
      evidenceItem("时间窗口", sit.time_window),
      evidenceList("已知依赖", sit.dependencies),
    );
    body.append(grid);

    const disclosure = node("button", "nt-evidence-disclosure", "查看依据");
    const detail = node("div", "nt-evidence-detail");
    detail.textContent = `evidence_codes: ${(ctx.evidence_codes || []).join(", ") || "—"} · ` +
      `limitations: ${(ctx.limitations || []).join(", ") || "—"}`;
    disclosure.addEventListener("click", () => {
      detail.classList.toggle("nt-open");
    });
    body.append(disclosure, detail);
  }

  function mergeCharacterLocations(characters, locations) {
    const out = [];
    if (Array.isArray(characters)) out.push(...characters);
    if (Array.isArray(locations)) out.push(...locations);
    return out;
  }

  function evidenceItem(label, value) {
    const wrap = node("div", "nt-evidence-item");
    wrap.append(node("span", "nt-evidence-label", label));
    if (value === null || value === undefined || value === "") {
      wrap.append(node("span", "nt-evidence-value nt-evidence-empty", "未提供"));
    } else {
      wrap.append(node("span", "nt-evidence-value", value));
    }
    return wrap;
  }

  function evidenceList(label, items) {
    const wrap = node("div", "nt-evidence-item");
    wrap.append(node("span", "nt-evidence-label", label));
    if (!Array.isArray(items) || !items.length) {
      wrap.append(node("span", "nt-evidence-value nt-evidence-empty", "未提供"));
      return wrap;
    }
    const ul = node("ul", "nt-evidence-list");
    items.forEach((item) => ul.append(node("li", "", item)));
    wrap.append(ul);
    return wrap;
  }

  // ---- Component: RecommendedActionGroup + RecommendedActionRow ---------

  function renderRecommendedActionGroup(plan) {
    const form = $("nt-action-form");
    if (!form) return;
    clear(form);

    const fieldset = node("fieldset", "nt-action-fieldset");
    const legend = node("legend", "nt-action-legend", "在以下 3 个推荐行动中选择一个进行可行性分析");
    fieldset.append(legend);

    const actions = (plan && plan.recommended_actions) || [];
    actions.forEach((action) => {
      fieldset.append(renderActionRow(action, plan));
    });
    form.append(fieldset);
  }

  function renderActionRow(action, plan) {
    const row = node("label", "nt-action-row");
    const unavailable = Array.isArray(action.unavailable_reasons) && action.unavailable_reasons.length > 0;
    if (unavailable) row.dataset.unavailable = "true";

    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "narrative-turn-action";
    radio.value = action.action_id;
    radio.className = "nt-action-radio";
    radio.id = `nt-action-radio-${action.action_id}`;
    if (state.selectedActionId === action.action_id && state.actionSource === "recommended") {
      radio.checked = true;
      row.classList.add("nt-selected");
    }
    const reasonId = `nt-action-reason-${action.action_id}`;
    if (unavailable) {
      radio.setAttribute("aria-describedby", reasonId);
    }
    radio.addEventListener("change", () => {
      if (radio.checked) handleRecommendedSelected(action.action_id);
    });

    const order = node("span", "nt-action-order", circleNumber(action.deterministic_order));

    const body = node("div", "nt-action-body");
    body.append(
      node("span", "nt-action-kicker", action.action_type),
      node("div", "nt-action-intent", action.intent),
      node("div", "nt-action-display", action.display_text),
    );
    const costsRisks = node("div", "nt-action-costs-risks");
    (action.expected_costs || []).forEach((c) => {
      costsRisks.append(node("span", "nt-action-cost", `${safeText(c.key, "?")}·${safeText(c.level, "?")}`));
    });
    (action.expected_risks || []).forEach((r) => {
      costsRisks.append(node("span", "nt-action-risk", `${safeText(r.key, "?")}·${safeText(r.level, "?")}`));
    });
    body.append(costsRisks);

    const side = node("div", "nt-action-side");
    const status = node("span", `nt-action-status ${unavailable ? "nt-status-blocked" : "nt-status-allowed"}`,
      unavailable ? "不可用" : "可用");
    side.append(status);
    if (unavailable) {
      const reason = node("span", "nt-action-unavailable-reason",
        (action.unavailable_reasons || []).map((r) => REASON_TEXT[r] || r).join("；"));
      reason.id = reasonId;
      side.append(reason);
    }

    row.append(radio, order, body, side);
    return row;
  }

  function circleNumber(n) {
    const map = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"];
    const idx = Number(n) - 1;
    if (idx >= 0 && idx < map.length) return map[idx];
    return String(n);
  }

  function markActionGroupStale(stale) {
    const form = $("nt-action-form");
    if (!form) return;
    form.querySelectorAll(".nt-action-row").forEach((row) => {
      if (stale) {
        row.dataset.staleGroup = "true";
        const radio = row.querySelector('input[type="radio"]');
        if (radio) radio.disabled = true;
      } else {
        delete row.dataset.staleGroup;
        const radio = row.querySelector('input[type="radio"]');
        if (radio) radio.disabled = false;
      }
    });
  }

  // ---- Component: CustomActionComposer ----------------------------------

  function normalizeText(raw) {
    // Mirror backend normalize_custom_action: NFKC + trim + collapse whitespace.
    // Reject NUL/control chars. Return {text, error}.
    if (typeof raw !== "string") return { text: "", error: "ACTION_UNPARSEABLE" };
    if (raw.indexOf("\u0000") !== -1) return { text: "", error: "ACTION_UNPARSEABLE" };
    // Reject other C0 control chars except \n \t \r
    for (let i = 0; i < raw.length; i++) {
      const c = raw.charCodeAt(i);
      if (c < 0x20 && c !== 0x09 && c !== 0x0A && c !== 0x0D) {
        return { text: "", error: "ACTION_UNPARSEABLE" };
      }
    }
    let text = raw.normalize("NFKC");
    text = text.replace(/\s+/g, " ").trim();
    return { text, error: null };
  }

  function renderCustomActionComposer() {
    const textarea = $("nt-custom-action-textarea");
    const counter = $("nt-custom-action-counter");
    const submit = $("nt-custom-action-submit");
    if (!textarea || !counter || !submit) return;

    textarea.value = state.customText;
    updateCounter();

    textarea.addEventListener("input", () => {
      state.customText = textarea.value;
      updateCounter();
    });
    textarea.addEventListener("blur", () => {
      // Persist text only in memory; never to localStorage or URL.
    });
    submit.addEventListener("click", () => {
      handleSubmitCustomAction();
    });
  }

  function updateCounter() {
    const counter = $("nt-custom-action-counter");
    const submit = $("nt-custom-action-submit");
    if (!counter || !submit) return;
    const { text, error } = normalizeText(state.customText);
    const count = text.length;
    counter.textContent = `${count}/${MAX_CUSTOM_LENGTH}`;
    counter.classList.toggle("nt-over-limit", count > MAX_CUSTOM_LENGTH);
    const canSubmit = count > 0 && count <= MAX_CUSTOM_LENGTH && !error;
    submit.disabled = !canSubmit;
    // Threshold announcement via TurnStatusNotice (single live region)
    announceThreshold(count);
  }

  function announceThreshold(count) {
    let bucket = null;
    if (count >= 201) bucket = 201;
    else if (count >= 200) bucket = 200;
    else if (count >= 190) bucket = 190;
    else if (count >= 150) bucket = 150;
    if (bucket !== null && bucket !== state.lastThresholdAnnounced) {
      state.lastThresholdAnnounced = bucket;
      if (bucket >= 201) {
        noticeAnnounce(`自定义行动已超过 ${MAX_CUSTOM_LENGTH} 字符上限，无法提交。`);
      } else if (bucket === 200) {
        noticeAnnounce("自定义行动已达 200 字符上限，仍可提交。");
      } else if (bucket === 190) {
        noticeAnnounce("自定义行动接近 200 字符上限。");
      } else if (bucket === 150) {
        noticeAnnounce("自定义行动已超过半数字符上限。");
      }
    } else if (bucket === null && state.lastThresholdAnnounced !== null) {
      state.lastThresholdAnnounced = null;
    }
  }

  // ---- Component: FeasibilityPanel --------------------------------------

  function renderFeasibilityPanel(validation) {
    const panel = $("nt-feasibility-panel");
    const body = $("nt-feasibility-body");
    if (!panel || !body) return;
    panel.classList.remove("hidden");
    clear(body);

    const status = validation.status || "blocked";
    const statusRow = node("div", "nt-feasibility-status-row");
    statusRow.append(
      node("span", "nt-feasibility-status-icon", STATUS_ICON[status] || "×"),
      node("span", `nt-feasibility-status-label ${STATUS_CLASS[status] || ""}`,
        `${STATUS_LABEL[status] || status}`),
    );
    body.append(statusRow);

    const reasons = (validation.blocking_reasons || []).map((r) => REASON_TEXT[r] || r);
    if (reasons.length) {
      body.append(node("p", "nt-feasibility-reasons", reasons.join("；")));
    }

    const blocks = node("div", "nt-feasibility-blocks");
    blocks.append(
      costRiskBlock("代价说明", validation.cost_explanation),
      costRiskBlock("风险说明", validation.risk_explanation),
    );
    body.append(blocks);

    const disclosure = node("button", "nt-feasibility-disclosure", "查看原始 reason code");
    const codes = node("div", "nt-feasibility-reason-codes");
    codes.textContent = (validation.blocking_reasons || []).join(", ") || "—";
    disclosure.addEventListener("click", () => codes.classList.toggle("nt-open"));
    body.append(disclosure, codes);
  }

  function costRiskBlock(label, items) {
    const wrap = node("div", "nt-feasibility-block");
    wrap.append(node("h3", "", label));
    if (!Array.isArray(items) || !items.length) {
      wrap.append(node("span", "nt-evidence-empty", "未提供"));
      return wrap;
    }
    const ul = node("ul", "");
    items.forEach((it) => ul.append(node("li", "", `${safeText(it.key, "?")}·${safeText(it.level, "?")}`)));
    wrap.append(ul);
    return wrap;
  }

  function hideFeasibilityPanel() {
    const panel = $("nt-feasibility-panel");
    if (panel) panel.classList.add("hidden");
  }

  // ---- Component: ConsequencePreview ------------------------------------

  function renderConsequencePreview(preview) {
    const panel = $("nt-consequence-preview");
    const body = $("nt-preview-body");
    if (!panel || !body) return;
    panel.classList.remove("hidden");
    clear(body);

    body.append(consequenceBlock("可能后果", preview.likely_consequences));
    body.append(consequenceBlock("预计代价", (preview.expected_costs || []).map((c) => `${c.key}·${c.level}`)));
    body.append(consequenceBlock("预计风险", (preview.expected_risks || []).map((r) => `${r.key}·${r.level}`)));
    body.append(consequenceBlock("证据", preview.evidence_codes));
    body.append(consequenceBlock("限制", preview.limitations));

    const freshness = node("div", "nt-consequence-freshness");
    freshness.append(
      node("span", "", `生成时间: ${safeText(preview.generated_at, "—")}`),
      node("span", "", `预览指纹: ${shortenFp(preview.preview_fingerprint)}`),
      node("span", "", `上下文: ${
        preview.context_fingerprint === (state.contextDto && state.contextDto.context_fingerprint)
          ? "匹配" : "已变更"}`),
    );
    body.append(freshness);
  }

  function consequenceBlock(label, items) {
    const wrap = node("div", "nt-consequence-block");
    wrap.append(node("h3", "", label));
    if (!Array.isArray(items) || !items.length) {
      wrap.append(node("span", "nt-evidence-empty", "未提供"));
      return wrap;
    }
    const ul = node("ul", "");
    items.forEach((it) => ul.append(node("li", "", it)));
    wrap.append(ul);
    return wrap;
  }

  function hideConsequencePreview() {
    const panel = $("nt-consequence-preview");
    if (panel) panel.classList.add("hidden");
  }

  // ---- Component: TurnPrimaryAction -------------------------------------

  function isConfirmEnabled() {
    if (state.confirmBusy) return false;
    if (state.confirmResultDto) return false;
    if (!state.contextDto) return false;
    if (!state.planDto) return false;
    if (!state.validationDto) return false;
    if (!state.previewDto) return false;
    if (!state.actionSource) return false;
    const branch = state.contextDto.branch || {};
    if (branch.lifecycle !== "open") return false;
    if (branch.activity !== "active") return false;
    const vstatus = state.validationDto.status;
    if (vstatus !== "allowed" && vstatus !== "allowed_with_cost") return false;
    if (state.validationDto.turn_id !== state.planDto.turn_id) return false;
    if (state.previewDto.turn_id !== state.planDto.turn_id) return false;
    if (state.previewDto.preview_fingerprint !== state.validationDto.context_fingerprint
        && state.previewDto.context_fingerprint !== state.contextDto.context_fingerprint) {
      return true;
    }
    return true;
  }

  function renderPrimaryAction() {
    const btn = $("nt-primary-action");
    if (!btn) return;

    if (state.confirmBusy) {
      btn.textContent = "确认中…";
      btn.disabled = true;
      btn.setAttribute("aria-disabled", "true");
      return;
    }

    if (state.confirmResultDto) {
      btn.textContent = "已确认";
      btn.disabled = true;
      btn.setAttribute("aria-disabled", "true");
      return;
    }

    btn.textContent = "确认行动";
    const enabled = isConfirmEnabled();
    btn.disabled = !enabled;
    btn.setAttribute("aria-disabled", enabled ? "false" : "true");
  }

  function generateOperationId() {
    const rand = crypto.getRandomValues(new Uint8Array(12));
    const hex = Array.from(rand).map(b => b.toString(16).padStart(2, "0")).join("");
    return "op-" + hex;
  }

  async function handleConfirmClick() {
    if (!isConfirmEnabled()) return;
    if (state.confirmBusy) return;

    const parsed = parseUrl();
    if (!parsed.project_id || !parsed.timeline_id || !parsed.branch_id || !parsed.chapter_id) {
      noticeError("缺少必要的范围参数。");
      return;
    }

    const operationId = state.confirmOperationId || generateOperationId();
    state.confirmOperationId = operationId;
    state.confirmBusy = true;
    renderPrimaryAction();
    noticeAnnounce("正在确认行动…");

    const body = {
      operation_id: operationId,
      project_id: parsed.project_id,
      timeline_id: parsed.timeline_id,
      branch_id: parsed.branch_id,
      chapter_id: parsed.chapter_id,
      source_version_id: parsed.source_version_id || null,
      expected_context_fingerprint: state.contextDto ? state.contextDto.context_fingerprint : null,
      expected_turn_id: state.planDto ? state.planDto.turn_id : null,
      expected_validation_id: state.validationDto ? state.validationDto.validation_id : null,
      expected_preview_fingerprint: state.previewDto ? state.previewDto.preview_fingerprint : null,
      action_source: state.actionSource,
    };

    if (state.actionSource === "recommended") {
      body.selected_action_id = state.selectedActionId;
    } else {
      body.custom_action_text = state.customText;
    }

    try {
      const resp = await apiPost("/api/narrative-turn/confirm", body);
      if (!resp.ok) {
        const err = describeHttpError(resp);
        state.confirmBusy = false;
        renderPrimaryAction();
        if (resp.status === 409 && err.code === "TURN_ALREADY_CONFIRMED") {
          noticeError("该回合已被确认。");
          state.confirmOperationId = null;
        } else if (resp.status === 409 && err.code === "OPERATION_ID_CONFLICT") {
          noticeError("操作 ID 冲突，请重试。");
          state.confirmOperationId = null;
        } else if (resp.status === 422) {
          noticeError(`确认被拒绝：${err.message}`);
          state.confirmOperationId = null;
        } else {
          noticeError(`确认失败：${err.message}`);
        }
        return;
      }

      state.confirmResultDto = resp.data;
      state.confirmBusy = false;
      renderPrimaryAction();
      renderConfirmResult(resp.data);

      if (resp.data.recovery_performed) {
        noticeAnnounce("行动已确认（故障恢复完成）。");
      } else if (resp.data.idempotent_replay) {
        noticeAnnounce("行动已确认（幂等重放）。");
      } else {
        noticeAnnounce("行动已确认。");
      }

      state.confirmOperationId = null;
      state.validationDto = null;
      state.previewDto = null;
      renderFeasibilityPanel(null);
      renderConsequencePreview(null);

      if (resp.data.result && resp.data.result.next_context_fingerprint) {
      }
    } catch (err) {
      if (err && err.name === "AbortError") return;
      state.confirmBusy = false;
      renderPrimaryAction();
      noticeError("确认请求失败；未展示原始异常信息。");
    }
  }

  function renderConfirmResult(resultDto) {
    const panel = $("nt-confirm-result");
    if (!panel) return;
    if (!resultDto || !resultDto.result) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    const r = resultDto.result;
    const summary = $("nt-confirm-summary");
    const status = $("nt-confirm-status");
    const flags = $("nt-confirm-flags");
    const nextFp = $("nt-confirm-next-fp");

    if (summary) summary.textContent = r.event_summary || "";
    if (status) summary.textContent = r.result_status || "";
    if (status) status.textContent = r.result_status || "";
    if (flags) {
      clear(flags);
      const fl = Array.isArray(r.consequence_flags) ? r.consequence_flags : [];
      fl.forEach(f => {
        const chip = node("span", "nt-flag-chip", f);
        flags.appendChild(chip);
      });
    }
    if (nextFp) {
      nextFp.textContent = r.next_context_fingerprint
        ? r.next_context_fingerprint.slice(0, 16) + "…"
        : "";
    }
  }

  // ---- Component: NarrativeTurnWorkspace --------------------------------

  function setWorkspaceState(stateName, busy) {
    const ws = $("narrative-turn-workspace");
    if (!ws) return;
    ws.dataset.contextState = stateName;
    ws.setAttribute("aria-busy", busy ? "true" : "false");
  }

  function showWorkspace() {
    const ws = $("narrative-turn-workspace");
    if (ws) {
      ws.classList.remove("hidden");
      ws.classList.add("nt-visible");
    }
  }

  function hideWorkspace() {
    const ws = $("narrative-turn-workspace");
    if (ws) {
      ws.classList.add("hidden");
      ws.classList.remove("nt-visible");
    }
  }

  // ---- Context bar (branch selector only) --------------------------------
  // Project, Timeline, Chapter, and Source Version are controlled by the
  // shared simulator-context-navigator. Narrative Turn adds only the
  // branch selector because the navigator does not include one.

  function renderContextBar(parsed) {
    const bar = $("nt-context-bar");
    if (!bar) return;
    clear(bar);

    const branchSel = document.createElement("select");
    branchSel.id = "nt-context-branch";
    branchSel.disabled = true;
    branchSel.append(new Option("加载中…", ""));
    const branchLabel = document.createElement("label");
    branchLabel.append(node("span", "", "Branch"), branchSel);
    bar.append(branchLabel);

    branchSel.addEventListener("change", (e) => {
      pushUrl({ branch_id: e.target.value, turn_id: null, action_id: null });
    });
  }

  async function loadContextBar(parsed) {
    const branchSel = $("nt-context-branch");
    if (!branchSel) return;

    try {
      const scope = `project_id=${encodeURIComponent(parsed.project_id)}&timeline_id=${encodeURIComponent(parsed.timeline_id)}`;
      const ctxResp = await apiGet(`/api/simulator/context?${scope}`);
      if (!ctxResp.ok) throw new Error("context load failed");
      const ctx = ctxResp.data && ctxResp.data.result ? ctxResp.data.result : ctxResp.data;

      const branches = Array.isArray(ctx.branches) ? ctx.branches : [];
      state.branchOptions = branches;
      branchSel.replaceChildren();
      if (!branches.length) {
        branchSel.append(new Option("无可用分支", ""));
        branchSel.disabled = true;
      } else {
        branches.forEach((b) => {
          const lifecycle = b.lifecycle_status || "open";
          const opt = new Option(`${b.branch_id} · ${lifecycle}`, b.branch_id);
          branchSel.append(opt);
        });
        const current = branches.find((b) => b.branch_id === parsed.branch_id);
        branchSel.value = current ? current.branch_id : branches[0].branch_id;
        branchSel.disabled = false;
      }
    } catch (err) {
      // Stale or transport error — keep selector disabled.
    }
  }

  // ---- Race protection ---------------------------------------------------

  function bumpGeneration() {
    state.generation += 1;
    if (state.controller) {
      try { state.controller.abort(); } catch (_) { /* ignore */ }
    }
    state.controller = new AbortController();
    return state.generation;
  }

  function isStale(generation) {
    return generation !== state.generation;
  }

  // ---- Workflow ----------------------------------------------------------

  function resetActionState() {
    state.selectedActionId = null;
    state.actionSource = null;
    state.validationDto = null;
    state.previewDto = null;
    state.confirmResultDto = null;
    state.confirmBusy = false;
    state.confirmOperationId = null;
    hideFeasibilityPanel();
    hideConsequencePreview();
    renderConfirmResult(null);
    renderPrimaryAction();
  }

  async function bindContextAndPlan(parsed) {
    const generation = bumpGeneration();
    setWorkspaceState("loading", true);
    noticeClear();
    resetActionState();
    markActionGroupStale(false);

    if (!parsed.project_id || !parsed.timeline_id || !parsed.branch_id || !parsed.chapter_id) {
      setWorkspaceState("error", false);
      noticeError("缺少 project_id / timeline_id / branch_id / chapter_id；请通过 Context Navigator 选择。");
      return;
    }
    if (!ID_PATTERN.test(parsed.project_id) || !ID_PATTERN.test(parsed.timeline_id)
        || !ID_PATTERN.test(parsed.branch_id)) {
      setWorkspaceState("error", false);
      noticeError("project_id / timeline_id / branch_id 格式无效。");
      return;
    }

    const scope = `project_id=${encodeURIComponent(parsed.project_id)}` +
      `&timeline_id=${encodeURIComponent(parsed.timeline_id)}` +
      `&branch_id=${encodeURIComponent(parsed.branch_id)}` +
      `&chapter_id=${encodeURIComponent(parsed.chapter_id)}` +
      (parsed.source_version_id ? `&source_version_id=${encodeURIComponent(parsed.source_version_id)}` : "");

    try {
      const ctxResp = await apiGet(`/api/narrative-turn/context?${scope}`, state.controller.signal);
      if (isStale(generation)) return; // silent discard
      if (!ctxResp.ok) {
        const err = describeHttpError(ctxResp);
        setWorkspaceState("error", false);
        if (ctxResp.status === 404) {
          noticeError(`上下文不存在：${err.message}`);
        } else {
          noticeError(`上下文读取失败：${err.message}`);
        }
        return;
      }
      state.contextDto = ctxResp.data;

      const planResp = await apiGet(`/api/narrative-turn/plan?${scope}`, state.controller.signal);
      if (isStale(generation)) return; // silent discard
      if (!planResp.ok) {
        const err = describeHttpError(planResp);
        setWorkspaceState("error", false);
        noticeError(`计划读取失败：${err.message}`);
        return;
      }
      state.planDto = planResp.data;

      // URL turn_id authority: compare with rebuilt plan.turn_id
      const urlTurnId = parsed.turn_id;
      if (urlTurnId) {
        if (urlTurnId !== state.planDto.turn_id) {
          setWorkspaceState("error", false);
          markActionGroupStale(true);
          noticeError("URL turn_id 与当前重建计划不匹配；请重新选择行动。");
          // Do not auto-correct URL
          return;
        }
        // turn_id matches — restore action_id if it belongs to current plan
        if (parsed.action_id) {
          const matched = (state.planDto.recommended_actions || [])
            .find((a) => a.action_id === parsed.action_id);
          if (matched) {
            state.selectedActionId = parsed.action_id;
            state.actionSource = "recommended";
          }
        }
      }

      setWorkspaceState("ready", false);
      renderSituationHeader(state.contextDto);
      renderEvidenceSummary(state.contextDto);
      renderRecommendedActionGroup(state.planDto);
      renderEvidenceRail(state.contextDto, state.planDto);
      noticeAnnounce("上下文已就绪");
      const heading = $("nt-heading");
      if (heading) heading.focus();

      // If action was restored, automatically request feasibility + preview
      if (state.selectedActionId && state.actionSource === "recommended") {
        requestFeasibilityAndPreview();
      }
    } catch (err) {
      if (err && err.name === "AbortError") return; // silent
      if (isStale(generation)) return;
      setWorkspaceState("error", false);
      noticeError("无法读取上下文；未展示原始异常信息。");
    }
  }

  function renderEvidenceRail(ctx, plan) {
    const body = $("nt-evidence-rail-body");
    if (!body) return;
    clear(body);

    const sec1 = node("div", "nt-evidence-rail-section");
    sec1.append(node("h3", "", "Freshness"));
    sec1.append(node("div", "", `audit: ${shortenFp(ctx.context_fingerprint)}`));
    sec1.append(node("div", "", `canon: ${shortenFp(ctx.canon_revision)}`));
    sec1.append(node("div", "", `planner: ${safeText(ctx.planner_revision, "—")}`));
    body.append(sec1);

    const sec2 = node("div", "nt-evidence-rail-section");
    sec2.append(node("h3", "", "Branch state"));
    const branch = ctx.branch || {};
    sec2.append(node("div", "", `lifecycle: ${safeText(branch.lifecycle, "—")}`));
    sec2.append(node("div", "", `activity: ${safeText(branch.activity, "—")}`));
    sec2.append(node("div", "", `narrative: ${safeText(branch.narrative_state_data, "—")}`));
    body.append(sec2);

    const sec3 = node("div", "nt-evidence-rail-section");
    sec3.append(node("h3", "", "Evidence codes"));
    (ctx.evidence_codes || []).forEach((code) => sec3.append(node("div", "", code)));
    if (!ctx.evidence_codes || !ctx.evidence_codes.length) {
      sec3.append(node("div", "", "—"));
    }
    body.append(sec3);

    const sec4 = node("div", "nt-evidence-rail-section");
    sec4.append(node("h3", "", "Limitations"));
    (ctx.limitations || []).forEach((lim) => sec4.append(node("div", "", lim)));
    if (!ctx.limitations || !ctx.limitations.length) {
      sec4.append(node("div", "", "—"));
    }
    body.append(sec4);
  }

  // ---- Action selection handlers ----------------------------------------

  function handleRecommendedSelected(actionId) {
    state.selectedActionId = actionId;
    state.actionSource = "recommended";
    // Retain custom text but supersede its result
    // (do not clear state.customText)
    pushUrl({ action_id: actionId, turn_id: state.planDto ? state.planDto.turn_id : null });
    // Re-render to show selected styling
    if (state.planDto) renderRecommendedActionGroup(state.planDto);
    requestFeasibilityAndPreview();
  }

  function handleSubmitCustomAction() {
    const { text, error } = normalizeText(state.customText);
    if (error || !text || text.length > MAX_CUSTOM_LENGTH) {
      noticeAnnounce("自定义行动无法提交，请检查输入。");
      return;
    }
    // Clear recommended selection (mutual exclusion)
    state.selectedActionId = null;
    state.actionSource = "custom";
    if (state.planDto) renderRecommendedActionGroup(state.planDto);
    pushUrl({ action_id: null, turn_id: state.planDto ? state.planDto.turn_id : null });
    requestFeasibilityAndPreview(text);
  }

  async function requestFeasibilityAndPreview(customTextOverride) {
    if (!state.contextDto || !state.planDto) return;
    const generation = bumpGeneration();
    const scope = {
      project_id: state.contextDto.scope.project_id,
      timeline_id: state.contextDto.scope.timeline_id,
      branch_id: state.contextDto.scope.branch_id,
      chapter_id: state.contextDto.chapter_id,
      source_version_id: state.contextDto.source_version_id || "",
      expected_context_fingerprint: state.contextDto.context_fingerprint,
      expected_turn_id: state.planDto.turn_id,
    };

    let body;
    if (state.actionSource === "recommended") {
      body = Object.assign({}, scope, {
        action_source: "recommended",
        selected_action_id: state.selectedActionId,
      });
    } else {
      // custom — raw text only in request body, never in URL/log/response
      body = Object.assign({}, scope, {
        action_source: "custom",
        custom_action_text: customTextOverride,
      });
    }

    try {
      noticeAnnounce("正在分析可行性…");
      const feasResp = await apiPost("/api/narrative-turn/feasibility", body, state.controller.signal);
      if (isStale(generation)) return; // silent discard
      if (!feasResp.ok) {
        const err = describeHttpError(feasResp);
        if (feasResp.status === 404) {
          noticeError(`所选范围不存在：${err.message}`);
        } else if (feasResp.status === 409) {
          noticeError(`上下文或回合已变更：${err.message}`);
          markActionGroupStale(true);
        } else if (feasResp.status === 422) {
          noticeError(`行动输入被拒绝：${err.message}`);
        } else {
          noticeError(`可行性分析失败：${err.message}`);
        }
        return;
      }
      state.validationDto = feasResp.data;
      renderFeasibilityPanel(state.validationDto);
      noticeAnnounce(`可行性分析完成：${STATUS_LABEL[state.validationDto.status] || state.validationDto.status}`);
    } catch (err) {
      if (err && err.name === "AbortError") return;
      if (isStale(generation)) return;
      noticeError("可行性分析请求失败；未展示原始异常信息。");
      return;
    }

    // Preview — re-issue with same body (server re-executes feasibility)
    try {
      const prevResp = await apiPost("/api/narrative-turn/preview", body, state.controller.signal);
      if (isStale(generation)) return; // silent discard
      if (!prevResp.ok) {
        const err = describeHttpError(prevResp);
        noticeError(`预览生成失败：${err.message}`);
        return;
      }
      state.previewDto = prevResp.data;
      renderConsequencePreview(state.previewDto);
      noticeAnnounce("预览已生成（定性）");
    } catch (err) {
      if (err && err.name === "AbortError") return;
      if (isStale(generation)) return;
      noticeError("预览请求失败；未展示原始异常信息。");
    }
  }

  // ---- Visibility --------------------------------------------------------

  function applyView(parsed) {
    const isNarrativeTurn = parsed.mode === "simulator" && parsed.view === "narrative-turn";
    if (isNarrativeTurn) {
      showWorkspace();
      // Hide the panel-review section to avoid double-mount
      const panel = $("simulator-panel-review");
      if (panel) panel.classList.add("hidden");
      renderContextBar(parsed);
      bindContextAndPlan(parsed);
      loadContextBar(parsed);
    } else {
      hideWorkspace();
    }
  }

  // ---- Init --------------------------------------------------------------

  function init() {
    window.addEventListener("popstate", () => {
      const parsed = parseUrl();
      applyView(parsed);
    });
    window.addEventListener("storyos:dashboard-ready", () => {
      const parsed = parseUrl();
      applyView(parsed);
    });

    const confirmBtn = $("nt-primary-action");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", handleConfirmClick);
    }

    // Re-render custom action composer once
    renderCustomActionComposer();
    renderPrimaryAction();
    // Initial application
    const parsed = parseUrl();
    applyView(parsed);
  }

  // Expose for tests / programmatic use
  window.StoryOSNarrativeTurn = {
    init,
    parseUrl,
    normalizeText,
    renderSituationHeader,
    renderEvidenceSummary,
    renderRecommendedActionGroup,
    renderFeasibilityPanel,
    renderConsequencePreview,
    renderPrimaryAction,
    renderConfirmResult,
    noticeAnnounce,
    noticeError,
    bindContextAndPlan,
    resetActionState,
    handleConfirmClick,
    isConfirmEnabled,
    generateOperationId,
    getState: () => Object.assign({}, state),
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
