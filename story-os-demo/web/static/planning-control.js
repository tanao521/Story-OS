(() => {
  let overview = null;
  const $ = id => document.getElementById(id);
  const request = async (path, options = {}) => {
    const response = await fetch(path, options);
    const value = await response.json();
    if (!value.ok) throw new Error((value.errors || [value.message])[0]);
    return value.result;
  };
  const setState = value => { const node = $("planning-control-state"); if (node) node.textContent = value; };
  const escape = value => String(value ?? "").replace(/[&<>\"]/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[char]));
  function render(data) {
    overview = data;
    const strategy = data.saved_strategy || {};
    $("planning-control-central-conflict").value = strategy.central_conflict || "";
    $("planning-control-ending-direction").value = strategy.ending_direction || "";
    $("planning-control-story-promise").value = strategy.story_promise || "";
    const projection = data.suggested_projection || {};
    $("planning-control-projection").innerHTML = data.materialized
      ? "控制层已落盘；蓝图仍为只读参考。"
      : "控制层尚未落盘。以下蓝图投影只是建议，点击保存后才会创建控制层文件。";
    const counts = [["里程碑", data.milestones], ["卷契约", data.volume_contracts], ["阶段契约", data.phase_contracts], ["锁定", data.locks], ["开放冲突", (data.conflicts || []).filter(item => item.status === "open")], ["版本", data.versions]];
    $("planning-control-summary").innerHTML = counts.map(([label, values]) => `<div><span>${escape(label)}</span><strong>${values.length}</strong></div>`).join("");
    const source = projection.fields || {};
    const milestones = (data.milestones || []).map(item => `<li><strong>${escape(item.title || "未命名里程碑")}</strong><span>${escape(item.status || "planned")}</span></li>`).join("") || "<li>尚未创建里程碑</li>";
    const contracts = (label, items) => `<h4>${label}</h4><ul>${items.map(item => `<li><strong>${escape(item.primary_goal || item.title || item.contract_id)}</strong><span>${escape(item.contract_id)}</span></li>`).join("") || "<li>尚未创建</li>"}</ul>`;
    const locks = (data.locks || []).filter(item => item.active).map(item => `<li><strong>${escape(item.entity_type)}.${escape(item.field)}</strong><button class="btn btn-secondary btn-compact" data-planning-control-release="${escape(item.lock_id)}">解除</button></li>`).join("") || "<li>没有启用中的锁定</li>";
    const conflicts = (data.conflicts || []).filter(item => item.status === "open").map(item => `<li><strong>${escape(item.entity_type)}.${escape(item.field)}</strong><span><button class="btn btn-secondary btn-compact" data-planning-control-resolve="${escape(item.conflict_id)}" data-resolution="keep_control_value">保留控制层</button><button class="btn btn-secondary btn-compact" data-planning-control-resolve="${escape(item.conflict_id)}" data-resolution="adopt_blueprint_value">采用蓝图</button></span></li>`).join("") || "<li>未发现开放冲突</li>";
    $("planning-control-list").innerHTML = `<h4>蓝图参考</h4><p>核心冲突：${escape(source.core_conflict || "—")}</p><p>结局方向：${escape(source.ending_direction || "—")}</p><h4>里程碑</h4><ul>${milestones}</ul>${contracts("卷契约", data.volume_contracts || [])}${contracts("阶段契约", data.phase_contracts || [])}<h4>锁定</h4><ul>${locks}</ul><h4>来源冲突</h4><ul>${conflicts}</ul>`;
    setState(data.materialized ? "已读取" : "未落盘");
  }
  async function load() { try { setState("读取中"); render(await request("/api/planning-control/overview")); } catch (error) { setState("读取失败"); $("planning-control-projection").textContent = error.message; } }
  async function save() { try { setState("保存中"); const strategy = await request("/api/planning-control/strategy", {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify({central_conflict:$("planning-control-central-conflict").value, ending_direction:$("planning-control-ending-direction").value, story_promise:$("planning-control-story-promise").value})}); if (overview) overview.saved_strategy = strategy.strategy; await load(); } catch (error) { setState("保存失败：" + error.message); } }
  async function createMilestone() { const title = window.prompt("里程碑标题"); if (!title) return; try { await request("/api/planning-control/milestones", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({title, milestone_type:"plot", importance:"major"})}); await load(); } catch (error) { setState("创建失败：" + error.message); } }
  async function scan() { try { setState("扫描中"); await request("/api/planning-control/conflicts/scan", {method:"POST"}); await load(); } catch (error) { setState("扫描失败：" + error.message); } }
  async function createContract(kind) { const primary_goal = window.prompt(kind === "volume" ? "卷契约的主要目标" : "阶段契约的主要目标"); if (!primary_goal) return; const path = kind === "volume" ? "volume-contracts" : "phase-contracts"; const reference = kind === "volume" ? {manual_scope:true, display_name:window.prompt("逻辑卷名称（仅引用，不会创建蓝图卷）") || "手工逻辑卷"} : {source_type:"story_blueprint", entity_type:"story_phase", entity_id:window.prompt("蓝图阶段 ID（例如 1）") || "", display_name:"蓝图阶段"}; try { await request(`/api/planning-control/${path}`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({primary_goal, [kind === "volume" ? "volume_ref" : "phase_ref"]:reference})}); await load(); } catch (error) { setState("创建失败：" + error.message); } }
  async function lockField(field) { if (!overview || !overview.saved_strategy) { setState("请先保存长期战略"); return; } const reason = window.prompt("锁定原因") || "作者锁定"; try { await request("/api/planning-control/locks", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({entity_type:"story_strategy",entity_id:overview.saved_strategy.strategy_id,field,reason})}); await load(); } catch (error) { setState("锁定失败：" + error.message); } }
  async function release(lockId) { try { await request(`/api/planning-control/locks/${lockId}/release`, {method:"POST"}); await load(); } catch (error) { setState("解锁失败：" + error.message); } }
  async function resolve(conflictId, action) { try { await request(`/api/planning-control/conflicts/${conflictId}/resolve`, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})}); await load(); } catch (error) { setState("处理失败：" + error.message); } }
  async function versions() { try { const result = await request("/api/planning-control/versions"); $("planning-control-list").innerHTML = `<h4>规划控制层版本</h4><ul>${(result.versions || []).map(item => `<li><strong>${escape(item.version_id)}</strong><span>${escape(item.reason)} · ${escape(item.created_at)} <button class="btn btn-secondary btn-compact" data-planning-control-restore="${escape(item.version_id)}">恢复</button></span></li>`).join("") || "<li>暂无版本</li>"}</ul>`; } catch (error) { setState("读取版本失败：" + error.message); } }
  async function restore(versionId) { if (!window.confirm("恢复只影响规划控制层；当前控制层会先自动快照。继续？")) return; try { await request(`/api/planning-control/versions/${versionId}/restore`, {method:"POST"}); await load(); } catch (error) { setState("恢复失败：" + error.message); } }
  document.addEventListener("click", event => { const target = event.target.closest("button"); if (!target) return; if (target.matches("[data-planning-control-refresh]")) load(); if (target.matches("[data-planning-control-save]")) save(); if (target.matches("[data-planning-control-add-milestone]")) createMilestone(); if (target.matches("[data-planning-control-add-volume]")) createContract("volume"); if (target.matches("[data-planning-control-add-phase]")) createContract("phase"); if (target.matches("[data-planning-control-lock]")) lockField(target.dataset.planningControlLock); if (target.matches("[data-planning-control-scan]")) scan(); if (target.matches("[data-planning-control-list-versions]")) versions(); if (target.matches("[data-planning-control-release]")) release(target.dataset.planningControlRelease); if (target.matches("[data-planning-control-resolve]")) resolve(target.dataset.planningControlResolve, target.dataset.resolution); if (target.matches("[data-planning-control-restore]")) restore(target.dataset.planningControlRestore); });
  setTimeout(load, 800);
})();
