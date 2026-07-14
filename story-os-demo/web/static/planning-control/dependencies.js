(() => {
  if (window.__storyosDependencyGraphBound) return;
  window.__storyosDependencyGraphBound = true;
  const $ = id => document.getElementById(id);
  const state = {revision: 0, nodes: [], dependencies: [], generation: 0, busy: false};
  const escape = value => String(value ?? "").replace(/[&<>\"]/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[character]));
  const operationId = () => globalThis.crypto?.randomUUID?.() || `dependency_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  const note = value => { const element = $("planning-dependency-notice"); if (element) element.textContent = value; };
  const request = async (path, options = {}) => { const response = await fetch(path, options); const value = await response.json(); if (!value.ok) { const error = new Error(value.message || "操作未完成"); error.code = value.error_code || (value.errors || [])[0]; error.details = value.details || {}; throw error; } return value.result; };
  const post = (path, payload) => request(path, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
  const mutation = values => ({expected_dependency_revision: state.revision, operation_id: operationId(), ...values});
  const nodeValue = node => `${node.node_type}|${node.node_id}`;
  const nodeRef = value => { const [node_type, node_id] = String(value).split("|"); return {node_type, node_id}; };
  function renderNodes() {
    const options = state.nodes.map(node => `<option value="${escape(nodeValue(node))}">${escape(node.title)} · ${escape(node.node_type)}</option>`).join("") || '<option value="">暂无可引用节点</option>';
    [$("dependency-from-node"), $("dependency-to-node")].forEach(select => { if (select) select.innerHTML = options; });
  }
  function renderHealth(health) {
    const host = $("planning-dependency-health"); if (!host) return;
    const issues = health?.issues || [];
    host.innerHTML = issues.length ? issues.map(issue => `<p><strong>${escape(issue.code)}</strong> ${escape((issue.cycle_path || issue.nodes || []).join(" → "))}</p>`).join("") : '<p>图健康：未发现缺失引用、前置循环或互相阻断。</p>';
  }
  function renderList() {
    const type = $("dependency-filter-type")?.value || ""; const status = $("dependency-filter-status")?.value || "";
    const values = state.dependencies.filter(item => (!type || item.dependency_type === type) && (!status || item.status === status));
    const host = $("planning-dependency-list"); if (!host) return;
    host.innerHTML = values.map(item => `<article class="planning-dependency-card" data-dependency-id="${escape(item.dependency_id)}"><div><span class="dependency-kind">${escape(item.dependency_type)}</span><strong>${escape(item.from_node?.title || item.from_node?.node_id)}</strong><span class="dependency-arrow">→</span><strong>${escape(item.to_node?.title || item.to_node?.node_id)}</strong><small>${escape(item.strength)} · ${escape(item.status)}</small></div><footer><button class="btn btn-secondary btn-compact" type="button" data-dependency-related="upstream">上游</button><button class="btn btn-secondary btn-compact" type="button" data-dependency-related="downstream">下游</button>${item.status === "active" ? '<button class="btn btn-secondary btn-compact" type="button" data-dependency-transition="disable">停用</button>' : item.status === "disabled" ? '<button class="btn btn-secondary btn-compact" type="button" data-dependency-transition="enable">启用</button>' : ''}${item.status !== "cancelled" ? '<button class="btn btn-secondary btn-compact" type="button" data-dependency-transition="cancel">取消</button>' : ''}</footer><p class="dependency-related" hidden></p></article>`).join("") || '<p class="planning-dependency-empty">尚未保存依赖关系。选择两个规划节点后由作者手动创建。</p>';
  }
  async function load() {
    const generation = ++state.generation;
    try { note("正在读取依赖关系…"); const view = await request("/api/planning-control/dependencies"); if (generation !== state.generation) return; state.revision = Number(view.dependency_revision || 0); state.dependencies = view.dependencies || []; state.nodes = view.available_nodes || []; renderNodes(); renderHealth(view.health); renderList(); note(`依赖图版本 ${state.revision}：${state.dependencies.length} 条关系。`); } catch (error) { note(`读取失败：${error.message}`); }
  }
  async function create(event) { event.preventDefault(); const from = $("dependency-from-node")?.value, to = $("dependency-to-node")?.value; if (!from || !to) return note("请先选择两个规划节点。"); try { state.busy = true; const result = await post("/api/planning-control/dependencies", mutation({from_node:nodeRef(from), to_node:nodeRef(to), dependency_type:$("dependency-type").value, strength:$("dependency-strength").value})); state.revision = Number(result.dependency?.dependency_revision || state.revision + 1); await load(); } catch (error) { const path = error.details?.cycle_path?.join(" → "); note(`未保存：${path || error.message}`); } finally { state.busy = false; } }
  async function transition(card, action) { try { const result = await post(`/api/planning-control/dependencies/${card.dataset.dependencyId}/transition`, mutation({action})); state.revision = Number(result.dependency?.dependency_revision || state.revision + 1); await load(); } catch (error) { note(`未更新：${error.message}`); } }
  async function related(card, direction) { const item = state.dependencies.find(row => row.dependency_id === card.dataset.dependencyId); if (!item) return; const node = direction === "upstream" ? item.from_node : item.to_node; try { const result = await request(`/api/planning-control/dependencies/${direction}?node_type=${encodeURIComponent(node.node_type)}&node_id=${encodeURIComponent(node.node_id)}`); const host = card.querySelector(".dependency-related"); host.hidden = false; host.textContent = `${direction === "upstream" ? "上游" : "下游"}：${(result[direction] || []).map(value => value.title).join("、") || "无"}`; } catch (error) { note(`查询失败：${error.message}`); } }
  async function health() { try { const result = await post("/api/planning-control/dependencies/validate", {}); renderHealth(result); note(`图健康检查完成：版本 ${result.dependency_revision}。`); } catch (error) { note(`检查失败：${error.message}`); } }
  async function addNode() { const title = window.prompt("自定义规划节点名称"); if (!title) return; try { const result = await post("/api/planning-control/dependency-nodes", mutation({title, category:"condition"})); state.revision = Number(result.node?.dependency_revision || state.revision + 1); await load(); } catch (error) { note(`未创建：${error.message}`); } }
  $("planning-dependency-form")?.addEventListener("submit", create);
  document.addEventListener("change", event => { if (event.target.matches("#dependency-filter-type, #dependency-filter-status")) renderList(); });
  document.addEventListener("click", event => { const button = event.target.closest("button"); if (!button) return; if (button.matches("[data-dependency-refresh]")) load(); if (button.matches("[data-dependency-health]")) health(); if (button.matches("[data-dependency-add-node]")) addNode(); const card = button.closest("[data-dependency-id]"); if (card && button.dataset.dependencyTransition) transition(card, button.dataset.dependencyTransition); if (card && button.dataset.dependencyRelated) related(card, button.dataset.dependencyRelated); });
  window.addEventListener("storyos:project-changed", load);
  setTimeout(load, 1050);
})();
