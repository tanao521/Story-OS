/* Read-only production integration for the Simulator / Panel Review surface. */
(function () {
  "use strict";

  const PROJECT_KEY = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
  const ID_KEY = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
  const STATUS_LABELS = {
    ready: "就绪", partial: "部分完成", not_run: "尚未运行", failed: "执行失败",
    stale: "结果过期", source_missing: "来源缺失", loading: "读取中",
    invalid_context: "上下文无效", transport_error: "连接失败", explicit_not_found: "面板运行不存在",
  };
  const root = () => document.getElementById("simulator-panel-review-root");
  const panel = () => document.getElementById("simulator-panel-review");

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
  function valueLine(label, value) {
    const row = node("div", "storyos-simulator-value");
    row.append(node("span", "storyos-simulator-label", label), node("strong", "storyos-simulator-value-text", value));
    return row;
  }
  function card(title, body, className = "") {
    const section = node("section", `storyos-simulator-card ${className}`.trim());
    section.append(node("h3", "storyos-simulator-card-title", title));
    if (body) section.append(body);
    return section;
  }
  function list(items, empty = "未提供") {
    const ul = node("ul", "storyos-simulator-list");
    if (!Array.isArray(items) || !items.length) { ul.append(node("li", "is-empty", empty)); return ul; }
    items.forEach((item) => ul.append(node("li", "", typeof item === "string" ? item : safeText(item.message || item.flag_code || item.target || item.conflict_id))));
    return ul;
  }
  function statusChip(status, extra = "") {
    const normalized = safeText(status, "transport_error");
    return node("span", `storyos-simulator-status storyos-simulator-status-${normalized} ${extra}`.trim(), STATUS_LABELS[normalized] || normalized);
  }
  function clear(target) { while (target && target.firstChild) target.removeChild(target.firstChild); }

  async function resolveSafeProject(apiGet) {
    const active = await apiGet("/api/projects/active");
    const activeProject = active && active.result && active.result.project;
    if (activeProject) return activeProject;
    const listing = await apiGet("/api/projects");
    const projects = listing && listing.result && Array.isArray(listing.result.projects) ? listing.result.projects : [];
    const legacy = projects.filter((project) => project && project.valid === true && project.legacy === true && PROJECT_KEY.test(String(project.project_id || "")));
    return legacy.length === 1 ? legacy[0] : null;
  }

  function parseContext() {
    const params = new URLSearchParams(window.location.search);
    const mode = params.get("mode") || "traditional";
    if (mode !== "simulator") return { mode };
    const view = params.get("view");
    const project = params.get("project");
    const timelineId = params.get("timeline_id");
    const chapterRaw = params.get("chapter_id");
    const panelExecutionId = params.get("panel_execution_id");
    const chapterId = Number(chapterRaw);
    const valid = view === "reader-panel-review" && PROJECT_KEY.test(project || "") && PROJECT_KEY.test(timelineId || "")
      && /^\d{1,7}$/.test(chapterRaw || "") && Number.isSafeInteger(chapterId) && chapterId > 0
      && (!panelExecutionId || ID_KEY.test(panelExecutionId));
    return { mode, view, project, timelineId, chapterId, panelExecutionId, valid };
  }

  function setMode(mode) {
    document.body.dataset.storyosMode = mode;
    document.querySelectorAll("[data-storyos-mode]").forEach((button) => {
      const selected = button.dataset.storyosMode === mode;
      button.setAttribute("aria-pressed", selected ? "true" : "false");
    });
    if (panel()) panel().classList.toggle("hidden", mode !== "simulator");
    const dashboard = document.getElementById("dashboard-view");
    if (dashboard) dashboard.classList.toggle("storyos-simulator-active", mode === "simulator");
  }

  function renderState(state, details) {
    const target = root(); if (!target) return;
    clear(target);
    const wrap = node("div", `storyos-simulator-state storyos-simulator-state-${state}`);
    wrap.append(statusChip(state), node("h3", "storyos-simulator-state-title", STATUS_LABELS[state] || state));
    wrap.append(node("p", "storyos-simulator-state-copy", details || "暂时无法提供面板复核。"));
    target.append(wrap);
  }

  function renderReview(review) {
    const target = root(); if (!target) return;
    clear(target);
    const status = safeText(review && review.review_status, "transport_error");
    const header = node("div", "storyos-simulator-review-summary");
    const summary = review.summary || {};
    header.append(statusChip(status), valueLine("章节", review.chapter_id), valueLine("面板执行", review.selected_panel_execution_id));
    target.append(header);

    const authority = review.authoritative_panel || {};
    const selectedRun = review.selected_panel_run || {};
    const authorityBody = node("div", "storyos-simulator-grid");
    authorityBody.append(valueLine("权威状态", authority.status || authority.panel_status), valueLine("面板运行", authority.panel_run_id || selectedRun.execution_id), valueLine("人格顺序", (authority.ordered_persona_ids || review.persona_reviews?.map((item) => item.persona_id) || []).join(" · ")));
    target.append(card("权威面板", authorityBody, "storyos-simulator-authority"));

    const cards = node("div", "storyos-simulator-persona-grid");
    (review.persona_reviews || []).slice().sort((a, b) => Number(a.persona_order || 0) - Number(b.persona_order || 0)).forEach((item) => {
      const auth = item.authoritative || {}; const supplement = item.model_supplement || {};
      const body = node("div", "storyos-simulator-persona-body");
      body.append(statusChip(item.display_status), valueLine("确定性评分", auth.engagement_score), valueLine("留存风险", auth.retention_risk));
      const split = node("div", "storyos-simulator-supplement-split");
      const feedback = supplement.model_feedback;
      const feedbackItems = Array.isArray(feedback?.concerns) ? feedback.concerns : (feedback ? [feedback] : []);
      split.append(card("权威结果", list((auth.priority_flags || []).map((flag) => `${safeText(flag.flag_code)} · ${safeText(flag.persona_severity || flag.base_severity)}`))), card("模型补充", list(feedbackItems, supplement.model_run_status === "not_run" ? "尚未生成模型补充" : "未提供")));
      body.append(split);
      if (Array.isArray(item.warnings) && item.warnings.length) body.append(list(item.warnings, "未提供"));
      cards.append(card(`${safeText(item.persona_order, "-")}. ${safeText(item.persona_name, item.persona_id)}`, body, "storyos-simulator-persona-card"));
    });
    target.append(card("人格复核", cards));

    const groups = node("div", "storyos-simulator-two-column");
    groups.append(card("一致性", list((review.agreement_groups || []).map((group) => `${safeText(group.category)} · ${(group.persona_ids || []).join("、")}`))), card("冲突", list((review.conflict_groups || []).map((group) => `${safeText(group.conflict_type)} · unresolved · ${(group.persona_ids || []).join("、")}`))));
    target.append(groups);

    const metrics = node("div", "storyos-simulator-grid");
    ["evidence_summary", "execution_summary", "usage_summary", "staleness_summary"].forEach((key) => {
      const data = review[key] || {}; const body = node("div", "storyos-simulator-metric-list");
      Object.keys(data).slice(0, 8).forEach((field) => body.append(valueLine(field, Array.isArray(data[field]) ? data[field].join("、") : data[field])));
      metrics.append(card(key.replace(/_summary$/, ""), body));
    });
    target.append(card("证据、执行、用量与新鲜度", metrics));
    if (Array.isArray(review.warnings) && review.warnings.length) target.append(card("警告", list(review.warnings)));
    if (!cards.children.length && status === "not_run") renderState("not_run", "当前章节尚无可选的面板执行记录；未创建运行，也未调用模型。 ");
  }

  async function loadReview(context) {
    const apiGet = window.storyosApiGet;
    if (typeof apiGet !== "function") { renderState("transport_error", "生产 API 辅助函数尚未就绪。 "); return; }
    renderState("loading", "正在读取只读复核结果…");
    try {
      const activeProject = await resolveSafeProject(apiGet);
      if (!activeProject || safeText(activeProject.project_id) !== context.project) {
        renderState("invalid_context", "URL 项目上下文与当前活动项目不一致；未发起复核请求。 "); return;
      }
      const query = `?chapter_id=${encodeURIComponent(context.chapterId)}`;
      const endpoint = context.panelExecutionId
        ? `/api/reader-persona/model-panel/runs/${encodeURIComponent(context.panelExecutionId)}/review${query}`
        : `/api/reader-persona/model-panel/review${query}`;
      const review = await apiGet(endpoint);
      renderReview(review && review.result ? review.result : review);
    } catch (error) {
      const message = safeText(error && error.message, "");
      if (context.panelExecutionId && /PANEL_RUN_NOT_FOUND|Panel run not found/i.test(message)) {
        renderState("explicit_not_found", "指定的面板执行不存在；未回退到自动选择。 ");
      } else if (/STALE_PROJECT_RESPONSE|AbortError/i.test(message)) {
        renderState("invalid_context", "项目上下文已变化，已丢弃过期响应。 ");
      } else {
        renderState("transport_error", "无法读取面板复核；未展示原始异常信息。 ");
      }
    }
  }

  function applyUrl() {
    const context = parseContext();
    setMode(context.mode === "simulator" ? "simulator" : "traditional");
    if (context.mode !== "simulator") return;
    if (!context.valid) { renderState("invalid_context", "需要有效的 view、project、timeline_id 和 chapter_id；未发起复核请求。 "); return; }
    loadReview(context);
  }

  async function enterSimulatorMode() {
    const url = new URL(window.location.href);
    url.searchParams.set("mode", "simulator");
    const apiGet = window.storyosApiGet;
    if (typeof apiGet === "function") {
      try {
        const project = await resolveSafeProject(apiGet);
        const chapterText = document.getElementById("topbar-current-chapter")?.textContent || "";
        const chapterMatch = chapterText.match(/\d+/);
        const chapterId = Number(chapterMatch && chapterMatch[0]) || Number(project && project.next_chapter) || 0;
        if (project && PROJECT_KEY.test(String(project.project_id || "")) && chapterId > 0) {
          url.searchParams.set("view", "reader-panel-review");
          url.searchParams.set("project", String(project.project_id));
          url.searchParams.set("timeline_id", "main");
          url.searchParams.set("chapter_id", String(chapterId));
        }
      } catch (_) {
        // Keep the mode-only URL; applyUrl will show the safe invalid-context state.
      }
    }
    window.history.pushState({}, "", url);
    applyUrl();
  }

  function init() {
    document.querySelectorAll("[data-storyos-mode]").forEach((button) => button.addEventListener("click", () => {
      const mode = button.dataset.storyosMode || "traditional";
      if (mode === "simulator") { enterSimulatorMode(); return; }
      const url = new URL(window.location.href); url.searchParams.set("mode", mode);
      url.searchParams.delete("view"); url.searchParams.delete("panel_execution_id");
      window.history.pushState({}, "", url); applyUrl();
    }));
    window.addEventListener("popstate", applyUrl);
    window.addEventListener("storyos:dashboard-ready", applyUrl);
    const refresh = document.getElementById("simulator-panel-review-refresh");
    if (refresh) refresh.addEventListener("click", applyUrl);
    applyUrl();
  }

  window.StoryOSSimulatorPanelReview = { init, parseContext, renderReview, renderState };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
