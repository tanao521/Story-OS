(() => {
  if (window.__storyosRollingLifecycleBound) return;
  window.__storyosRollingLifecycleBound = true;
  const lifecycle = {activeProjectId: "", requestGeneration: 0, windowRevision: 0, preview: null, dirty: false, busy: false};
  const $ = id => document.getElementById(id);
  const notice = () => $("rolling-window-notice");
  const state = () => $("rolling-window-state");
  const statusText = {active: "同步", needs_roll_forward: "需要推进", stale: "需要复核", reanchor_required: "需要重新绑定", uninitialized: "尚未初始化"};
  const operationId = () => globalThis.crypto?.randomUUID?.() || `rolling_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  const sameGeneration = (generation, projectId = "") => generation === lifecycle.requestGeneration && (!projectId || !lifecycle.activeProjectId || projectId === lifecycle.activeProjectId);
  const request = async (path, options = {}) => {
    const value = await window.storyosApiRequest(path, options);
    if (!value.ok) { const error = new Error(value.message || value.error_code || "操作失败"); error.code = value.error_code; error.details = value.details || {}; throw error; }
    return value.result;
  };
  const post = (path, payload = {}) => request(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
  const put = (path, payload) => request(path, {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
  const setBusy = (button, value) => { lifecycle.busy = value; if (button) button.disabled = value; };
  const message = text => { if (notice()) notice().textContent = text; };
  const mutation = (extra = {}) => ({expected_window_revision: lifecycle.windowRevision, operation_id: operationId(), ...extra});
  const reloadWindow = () => window.dispatchEvent(new Event("storyos:project-changed"));
  async function refreshHealth() {
    const generation = lifecycle.requestGeneration;
    const view = await request("/api/planning-control/rolling-window");
    const projectId = view.window?.project_id || "";
    if (!sameGeneration(generation, projectId)) return null;
    lifecycle.activeProjectId = projectId || lifecycle.activeProjectId;
    lifecycle.windowRevision = Number(view.window?.window_revision || 0);
    const health = view.health || await request("/api/planning-control/rolling-window/health");
    if (!sameGeneration(generation, projectId)) return null;
    const label = statusText[health.status] || health.status;
    if (state()) state().textContent = label;
    const diagnostics = (health.issues || []).map(item => item.type).concat((health.source_changes || []).map(item => item.id));
    message(`窗口状态：${label} · revision ${lifecycle.windowRevision}${diagnostics.length ? ` · ${diagnostics.join("、")}` : ""}${lifecycle.dirty ? " · 有未保存修改" : ""}`);
    return view;
  }
  function showError(error) {
    if (error.code === "ROLLING_WINDOW_REVISION_CONFLICT") message("窗口已更新；当前编辑内容仍保留。请重新加载最新数据后再决定是否提交。");
    else if (error.code === "ROLLING_PREVIEW_STALE") message("预览已失效，未执行任何写入。请重新查看预览后确认。");
    else message(`操作未完成：${error.message}。未自动重复提交。`);
  }
  async function previewForward(button) {
    setBusy(button, true); try { lifecycle.preview = (await post("/api/planning-control/rolling-window/roll-forward")).preview; message(`前推预览：${lifecycle.preview.old_anchor} → ${lifecycle.preview.new_anchor}；新增空槽位 ${(lifecycle.preview.new_empty_slots || []).join("、") || "无"}。`); } catch (error) { showError(error); } finally { setBusy(button, false); }
  }
  async function confirmForward(button) {
    if (!lifecycle.preview?.preview_id) return message("请先查看前推预览。");
    if (!window.confirm("确认后只更新滚动窗口，不修改正文、正史、状态或当前章节计划。")) return;
    setBusy(button, true); try { const result = await post("/api/planning-control/rolling-window/roll-forward/confirm", mutation({preview_id: lifecycle.preview.preview_id, author_confirm: true})); lifecycle.preview = null; lifecycle.windowRevision = Number(result.window?.window_revision || lifecycle.windowRevision); await refreshHealth(); reloadWindow(); } catch (error) { showError(error); } finally { setBusy(button, false); }
  }
  async function refreshSources(button) {
    if (lifecycle.dirty && !window.confirm("存在未保存编辑。刷新来源不会保存这些编辑；继续吗？")) return;
    setBusy(button, true); try { const result = await post("/api/planning-control/rolling-window/refresh", mutation()); lifecycle.windowRevision = Number(result.window?.window_revision || lifecycle.windowRevision); await refreshHealth(); reloadWindow(); } catch (error) { showError(error); } finally { setBusy(button, false); }
  }
  async function reanchor(button) {
    if (lifecycle.dirty && !window.confirm("存在未保存编辑。重新绑定前请确认是否放弃这些编辑。")) return;
    const raw = window.prompt("新的下一待写章节号（只重新绑定窗口）"); if (!raw) return;
    setBusy(button, true); try { const previewResult = await post("/api/planning-control/rolling-window/reanchor", {next_chapter_number: +raw, author_confirm: false}); lifecycle.preview = previewResult.preview; if (!window.confirm(`建议锚点 ${lifecycle.preview.suggested_anchor}；影响 ${(lifecycle.preview.affected_slot_ids || []).length} 个槽位。确认？`)) return; const result = await post("/api/planning-control/rolling-window/reanchor", mutation({next_chapter_number: +raw, author_confirm: true, preview_id: lifecycle.preview.preview_id})); lifecycle.preview = null; lifecycle.windowRevision = Number(result.window?.window_revision || lifecycle.windowRevision); await refreshHealth(); reloadWindow(); } catch (error) { showError(error); } finally { setBusy(button, false); }
  }
  async function saveSlot(card, button) {
    const payload = mutation(); card.querySelectorAll("[data-slot-field]").forEach(input => { payload[input.dataset.slotField] = input.value; });
    setBusy(button, true); try { const result = await put(`/api/planning-control/rolling-window/slots/${card.dataset.slotId}`, payload); lifecycle.windowRevision = Number(result.slot?.window_revision || lifecycle.windowRevision + 1); lifecycle.dirty = false; await refreshHealth(); reloadWindow(); } catch (error) { showError(error); } finally { setBusy(button, false); }
  }
  async function cancelSlot(card, button) {
    setBusy(button, true); try { const result = await post(`/api/planning-control/rolling-window/slots/${card.dataset.slotId}/cancel`, mutation()); lifecycle.windowRevision = Number(result.slot?.window_revision || lifecycle.windowRevision + 1); lifecycle.dirty = false; await refreshHealth(); reloadWindow(); } catch (error) { showError(error); } finally { setBusy(button, false); }
  }
  document.addEventListener("input", event => { if (event.target.closest("#rolling-window-panel input, #rolling-window-panel textarea, #rolling-window-panel select")) { lifecycle.dirty = true; } }, true);
  document.addEventListener("click", async event => {
    const button = event.target.closest("button"); if (!button || lifecycle.busy) return;
    const card = button.closest("[data-slot-id]");
    if (button.matches("[data-rolling-preview], [data-rolling-forward], [data-rolling-far], [data-rolling-reanchor]") || (card && button.matches("[data-slot-save], [data-slot-cancel]"))) event.stopImmediatePropagation(); else return;
    event.preventDefault();
    if (button.matches("[data-rolling-preview]")) return previewForward(button);
    if (button.matches("[data-rolling-forward]")) return confirmForward(button);
    if (button.matches("[data-rolling-far]")) return refreshSources(button);
    if (button.matches("[data-rolling-reanchor]")) return reanchor(button);
    if (card && button.matches("[data-slot-save]")) return saveSlot(card, button);
    if (card && button.matches("[data-slot-cancel]")) return cancelSlot(card, button);
  }, true);
  window.addEventListener("storyos:project-changed", () => { lifecycle.requestGeneration += 1; lifecycle.activeProjectId = ""; lifecycle.windowRevision = 0; lifecycle.preview = null; lifecycle.dirty = false; setTimeout(() => { refreshHealth().catch(() => {}); }, 80); });
  window.addEventListener("beforeunload", event => { if (lifecycle.dirty) { event.preventDefault(); event.returnValue = "存在未保存的滚动窗口编辑。"; } });
  setTimeout(() => { refreshHealth().catch(() => {}); }, 900);
})();
