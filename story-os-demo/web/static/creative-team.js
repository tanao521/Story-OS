(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? "").replace(/[&<>"]/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[char]));
  let activeRun = null;

  const roleName = {story_director: "故事导演", plot_architect: "剧情架构师", character_psychologist: "角色心理顾问", world_builder: "世界观顾问", writer: "写作顾问", editor: "编辑顾问", continuity_checker: "连续性检查员", reader_simulator: "读者模拟器", character_simulator: "角色模拟器", market_analyst: "市场分析师", audience_analyst: "读者分析师", story_strategist: "故事策略师", retention_analyst: "留存分析师", author_assistant: "作者助手"};
  const roleNote = {story_director: "明确本章创作简报，不直接生成正文。", plot_architect: "为作者确认而拆解章节节拍。", character_psychologist: "检查人物动机与可能反应。", world_builder: "依据既定世界观提出建议，不改写设定。", writer: "提供可审阅的正文方向。", editor: "提出清晰度与节奏改进建议。", continuity_checker: "标记事实与因果冲突。", reader_simulator: "给出多类读者的反馈。", character_simulator: "进行受限的角色行为推演。", market_analyst: "分析题材信号、定位与创作风险。", audience_analyst: "模拟读者预期，不使用真实用户数据。", story_strategist: "将分析转为由作者选择的故事策略。", retention_analyst: "标记开篇与结尾的模拟流失风险。", author_assistant: "结合作者偏好和资产提供编辑式提醒。"};
  const stateName = {pending: "等待执行", running: "执行中", completed: "已完成", waiting_for_human: "等待作者确认", failed: "执行失败"};
  const stepName = {direct: "形成创作简报", plan: "提出章节节拍", character: "推演角色行为", write: "给出写作方向", edit: "给出编辑建议", read: "读者反馈", continuity: "连续性建议"};
  const legacyProposalText = {
    "Advance the current chapter with a clear consequence.": "推动本章发展，并让主角面对清晰且会改变局面的后果。",
    "Advance the current chapter.": "推动本章发展，并让主角面对清晰且会改变局面的后果。",
    "Keep the chapter aligned with the active story promise.": "让本章始终兑现当前故事已经建立的核心承诺。",
    "Confirm the creative brief before drafting.": "请确认这份创作简报，再进入后续的情节设计。"
  };

  function localize(value) {
    if (typeof value === "string") return legacyProposalText[value] || value;
    if (Array.isArray(value)) return value.map(localize);
    if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, localize(item)]));
    return value;
  }

  async function api(url, method = "GET", body) {
    const response = await fetch(url, {method, headers: body ? {"Content-Type": "application/json"} : {}, body: body ? JSON.stringify(body) : undefined});
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error?.message || payload.message || "请求失败");
    return payload.result || {};
  }

  function roster(agents) {
    $("creative-team-roster").innerHTML = agents.map(agent => `<article class="agent-card"><i class="agent-status ${agent.enabled ? "" : "off"}"></i><b>${roleName[agent.id] || esc(agent.name)}</b><small>${roleNote[agent.id] || esc(agent.description)}</small><button class="btn btn-link btn-compact" data-agent-toggle="${esc(agent.id)}" data-enabled="${agent.enabled}">${agent.enabled ? "暂停" : "启用"}</button></article>`).join("") || '<div class="empty-state">暂无可用创作角色。</div>';
    document.querySelectorAll("[data-agent-toggle]").forEach(button => button.addEventListener("click", async () => {
      try {
        await api(`/api/agents/${button.dataset.agentToggle}`, "PUT", {enabled: button.dataset.enabled !== "true"});
        refresh();
      } catch (error) {
        $("creative-team-feedback").textContent = error.message;
      }
    }));
  }

  function field(label, value) {
    const localized = localize(value);
    if (localized === undefined || localized === null || localized === "") return "";
    const body = Array.isArray(localized) ? `<ul>${localized.map(item => `<li>${esc(typeof item === "string" ? item : JSON.stringify(item))}</li>`).join("")}</ul>` : typeof localized === "object" ? `<pre>${esc(JSON.stringify(localized, null, 2))}</pre>` : `<p>${esc(localized)}</p>`;
    return `<div class="proposal-field"><span>${label}</span>${body}</div>`;
  }

  function proposalFields(result) {
    const fields = [];
    if (result.model_advisory_error?.message) fields.push(field("模型状态", result.model_advisory_error.message));
    if (result.model_advisory) fields.push(field("模型生成的创作建议", result.model_advisory));
    if (result.creative_brief) fields.push(field("创作简报", result.creative_brief));
    if (result.decision) fields.push(field("执行原则", result.decision));
    if (result.goal) fields.push(field("本章目标", result.goal));
    if (result.beats) fields.push(field("建议节拍", result.beats));
    if (result.human_checkpoint) fields.push(field("作者要确认的事", result.human_checkpoint));
    if (!fields.length) fields.push(field("建议内容", result));
    return fields.join("");
  }

  function proposal(step) {
    if (!step) return "";
    const result = step.result || {};
    if (!Object.keys(result).length) return '<section class="meeting-proposal"><span class="eyebrow">旧会议记录</span><h4>这场会议没有保存可审阅的方案。</h4><p class="proposal-impact">请重新生成一场会议；系统会先展示方案，再请你确认。</p><button class="btn btn-secondary btn-compact" data-restart-meeting>重新生成可确认方案</button></section>';
    return `<section class="meeting-proposal"><span class="eyebrow">待作者确认</span><h4>请先阅读这份方案，再决定是否认可</h4>${proposalFields(result)}<p class="proposal-impact">确认后，团队只会进入下一步建议；不会自动写入正文、提交章节或改写设定。</p><button class="btn btn-primary btn-compact" data-confirm-proposal>认可方案，进入下一步</button></section>`;
  }

  function meetingResults(run) {
    const completed = (run.steps || []).filter(step => step.status === "completed" && step.result && Object.keys(step.result).length);
    if (!completed.length) return "";
    return `<section class="meeting-results"><h4>本次会议已生成的建议</h4>${completed.map((step, index) => `<details class="meeting-result" ${index === completed.length - 1 ? "open" : ""}><summary>${stepName[step.id] || esc(step.label)}</summary>${proposalFields(step.result)}</details>`).join("")}</section>`;
  }

  function meeting(run) {
    if (!run) {
      $("creative-meeting-record").innerHTML = '<p class="empty-state">开始会议后，系统会先展示待确认的方案。</p>';
      return;
    }
    activeRun = run;
    const current = (run.steps || []).find(step => step.id === run.current_step);
    const rows = (run.steps || []).map(step => `<div class="meeting-step ${esc(step.status)}"><b>${stepName[step.id] || esc(step.label)}</b><br><small>${stateName[step.status] || esc(step.status)}</small></div>`).join("");
    $("creative-meeting-record").innerHTML = `<p class="meeting-title">创作会议 · ${stateName[run.status] || esc(run.status)}</p>${proposal(current)}${meetingResults(run)}<div class="meeting-track">${rows}</div>`;
    $("creative-team-run").textContent = run.status === "waiting_for_human" ? "认可方案并继续" : "开始创作会议";
    $("creative-meeting-record").querySelector("[data-confirm-proposal]")?.addEventListener("click", continueRun);
    $("creative-meeting-record").querySelector("[data-restart-meeting]")?.addEventListener("click", startFresh);
  }

  async function refresh() {
    try {
      const [agents, workflows] = await Promise.all([api("/api/agents"), api("/api/workflows/chapter_creative_v1/runs")]);
      roster(agents.agents || []);
      meeting((workflows.runs || [])[0] || null);
    } catch (error) {
      $("creative-meeting-record").textContent = error.message;
    }
  }

  async function continueRun() {
    if (!activeRun) return;
    try {
      await api("/api/workflows/run", "POST", {run_id: activeRun.run_id, decisions: {[activeRun.current_step]: true}});
      setTimeout(refresh, 350);
    } catch (error) {
      $("creative-team-feedback").textContent = error.message;
    }
  }

  async function startFresh() {
    try {
      const result = await api("/api/workflows/run", "POST", {workflow_id: "chapter_creative_v1", allow_model_calls: true});
      $("creative-meeting-record").innerHTML = `<p class="empty-state">创作会议已提交：${esc(result.job?.job_id || "")}。正在生成可审阅方案…</p>`;
      setTimeout(refresh, 800);
      setTimeout(refresh, 1800);
    } catch (error) {
      $("creative-meeting-record").innerHTML = `<p class="empty-state">无法生成方案：${esc(error.message)}</p>`;
    }
  }

  async function run() {
    if (activeRun && activeRun.status === "waiting_for_human") return continueRun();
    await startFresh();
  }

  async function action(path, label, button) {
    const feedback = $("creative-team-feedback");
    const previous = button?.textContent;
    if (button) button.disabled = true;
    feedback.textContent = `${label}正在生成…`;
    try {
      const result = await api(path, "POST", path.includes("reader") ? {draft_text: ""} : {});
      const content = result.review || result.simulation || result.debate || result;
      feedback.textContent = `${label}\n\n${JSON.stringify(localize(content), null, 2)}`;
    } catch (error) {
      feedback.textContent = `${label}失败：${error.message}`;
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = previous;
      }
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    $("creative-team-run")?.addEventListener("click", run);
    $("creative-team-debate")?.addEventListener("click", event => action("/api/creative/debate", "提案比较", event.currentTarget));
    $("creative-team-reader")?.addEventListener("click", event => action("/api/reader/simulate", "读者模拟", event.currentTarget));
    $("creative-team-character")?.addEventListener("click", event => action("/api/character/simulate", "角色模拟", event.currentTarget));
    window.addEventListener("storyos:project-changed", () => {
      activeRun = null;
      refresh();
    });
    refresh();
  });
})();
