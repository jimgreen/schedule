// Frontend logic is loaded after the document so every selector is optional-safe.
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = { caseData: null, optimization: null, network: null, overview: null, plans: {}, solvers: {}, activeSolver: "highs", latestPlanId: null, curvePage: 0 };

  const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
  const number = (value, digits = 2) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
  const toast = (message, error = false) => { const node = $("#toast"); if (node) { node.textContent = message; node.classList.toggle("error", error); } };
  async function api(path, options = {}) {
    const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
    const text = await response.text();
    let body = {};
    try { body = text ? JSON.parse(text) : {}; } catch { body = { detail: text }; }
    if (!response.ok) throw new Error(body.detail || `请求失败（${response.status}）`);
    return body;
  }
  function line(values, color = "#4fd1a5") {
    if (!Array.isArray(values) || !values.length) return '<span class="muted">暂无曲线数据</span>';
    const max = Math.max(...values.map(Number), 1);
    const points = values.map((value, index) => `${index * 100 / Math.max(values.length - 1, 1)},${100 - Number(value || 0) * 90 / max}`).join(" ");
    return `<svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="曲线"><polyline fill="none" stroke="${color}" stroke-width="1.5" points="${points}"/></svg>`;
  }
  function setTab(name) {
    $$("#tabs button").forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
    $$(".view").forEach((view) => view.classList.toggle("active", view.id === name));
    if (["weekly", "daily", "hourly"].includes(name)) renderPlan(name);
    if (name === "control") loadAudit().catch((error) => toast(error.message, true));
  }
  function renderOverview(plan = state.overview?.latest_plan) {
    const control = state.overview?.control;
    const firstDispatch = plan?.dispatch?.[0] || {};
    const set = (selector, value) => { const node = $(selector); if (node) node.textContent = value; };
    set("#fuel", plan ? number(plan.fuel_summary?.total_liters) : "—");
    set("#solver", plan?.solver_report?.solver?.toUpperCase() || "—");
    set("#status", plan?.status || "暂无结果");
    set("#load", firstDispatch.demand_kw == null ? "—" : number(firstDispatch.demand_kw, 1));
    set("#auto-state", control ? (control.auto_hourly_enabled ? "开启" : "暂停") : "—");
    set("#db", state.caseData ? "SQLite 已加载" : "数据库检查中");
    set("#latest-plan", plan ? `${plan.kind} · ${plan.plan_id.slice(0, 8)}` : "暂无计划");
    const chart = $("#chart"); if (chart) chart.innerHTML = plan ? line(plan.fuel_summary?.interval_liters, "#6da8ff") : '<span class="muted">数据库中暂无计划，请先求解。</span>';
  }
  function generatorFields(generator) {
    return `<div class="device-card" data-id="${esc(generator.id)}"><div class="device-title"><strong>${esc(generator.name)}</strong><span class="badge">柴油</span></div><div class="field-grid"><label>最小功率(kW)<input data-field="min_power_kw" type="number" min="0" step="1" value="${esc(generator.min_power_kw)}"></label><label>最大功率(kW)<input data-field="max_power_kw" type="number" min="1" step="1" value="${esc(generator.max_power_kw)}"></label><label>爬坡上限(kW/步)<input data-field="ramp_up_kw_per_step" type="number" min="0.1" step="1" value="${esc(generator.ramp_up_kw_per_step)}"></label><label>爬坡下限(kW/步)<input data-field="ramp_down_kw_per_step" type="number" min="0.1" step="1" value="${esc(generator.ramp_down_kw_per_step)}"></label><label>油价(元/L)<input data-field="fuel_price_per_liter" type="number" min="0" step="0.1" value="${esc(generator.fuel_price_per_liter)}"></label><label>启动成本<input data-field="startup_cost" type="number" min="0" step="0.1" value="${esc(generator.startup_cost)}"></label></div><div class="curve-mini"><span>油耗曲线</span>${generator.fuel_curve.map((point, index) => `<label>${index + 1}<input data-curve-power="${index}" type="number" min="0" step="1" value="${esc(point.power_kw)}"><input data-curve-fuel="${index}" type="number" min="0.01" step="0.1" value="${esc(point.liters_per_hour)}"><small>kW / L/h</small></label>`).join("")}</div></div>`;
  }
  function renderCase() {
    const data = state.caseData; const root = $("#device-list"); if (!data || !root) return;
    const renewableFields = data.renewables.map((item) => `<div class="asset-row"><strong>${esc(item.name)}</strong><span class="badge">${esc(item.kind === "pv" ? "光伏" : "风电")}</span><label>容量(kW)<input data-renewable="${esc(item.id)}" type="number" min="0.1" step="1" value="${esc(item.capacity_kw)}"></label></div>`).join("");
    const batteryFields = data.batteries.map((item) => `<div class="asset-row"><strong>${esc(item.name)}</strong><span class="badge">储能</span><label>容量(kWh)<input data-battery="${esc(item.id)}" data-battery-field="capacity_kwh" type="number" min="0.1" step="1" value="${esc(item.capacity_kwh)}"></label><label>最大充电(kW)<input data-battery="${esc(item.id)}" data-battery-field="max_charge_kw" type="number" min="0.1" step="1" value="${esc(item.max_charge_kw)}"></label><label>最大放电(kW)<input data-battery="${esc(item.id)}" data-battery-field="max_discharge_kw" type="number" min="0.1" step="1" value="${esc(item.max_discharge_kw)}"></label></div>`).join("");
    root.innerHTML = data.generators.map(generatorFields).join("") + `<div class="asset-panel"><h3>可再生能源</h3>${renewableFields || '<span class="muted">暂无可再生能源</span>'}</div><div class="asset-panel"><h3>储能与联络线</h3>${batteryFields || '<span class="muted">暂无储能设备</span>'}<div class="asset-row grid-asset"><strong>联络线</strong><label>进口上限(kW)<input data-grid="import_limit_kw" type="number" min="0.1" step="1" value="${esc(data.grid.import_limit_kw)}"></label><label>出口上限(kW)<input data-grid="export_limit_kw" type="number" min="0" step="1" value="${esc(data.grid.export_limit_kw)}"></label><label>进口电价<input data-grid="import_price_per_kwh" type="number" min="0" step="0.01" value="${esc(data.grid.import_price_per_kwh)}"></label></div></div><div class="device-summary"><div class="row"><span>柴油机组 / 风光</span><strong>${data.generators.length} / ${data.renewables.length}</strong></div><div class="row"><span>储能 / 可调负荷</span><strong>${data.batteries.length} / ${data.flexible_loads.length}</strong></div><div class="row"><span>预测点</span><strong>${data.forecast.demand_kw.length} 小时</strong></div></div>`;
  }
  function collectCase() {
    const updated = structuredClone(state.caseData);
    $$(".device-card").forEach((card) => { const generator = updated.generators.find((item) => item.id === card.dataset.id); if (!generator) return; $$("[data-field]", card).forEach((input) => { generator[input.dataset.field] = Number(input.value); }); generator.fuel_curve.forEach((point, index) => { point.power_kw = Number($(`[data-curve-power=\"${index}\"]`, card).value); point.liters_per_hour = Number($(`[data-curve-fuel=\"${index}\"]`, card).value); }); });
    $$("[data-renewable]").forEach((input) => { const item = updated.renewables.find((entry) => entry.id === input.dataset.renewable); if (item) item.capacity_kw = Number(input.value); });
    $$("[data-battery]").forEach((input) => { const item = updated.batteries.find((entry) => entry.id === input.dataset.battery); if (item) item[input.dataset.batteryField] = Number(input.value); });
    $$("[data-grid]").forEach((input) => { updated.grid[input.dataset.grid] = Number(input.value); });
    return updated;
  }
  function renderOptimization() {
    const root = $("#optimization-form"); if (!root || !state.optimization) return;
    const labels = { fuel_cost_multiplier: "燃油成本权重", startup_cost_multiplier: "启停成本权重", curtailment_penalty: "弃风弃光惩罚", reserve_penalty: "备用不足惩罚", lost_load_penalty: "失负荷惩罚", baseline_deviation_penalty: "基线偏差惩罚", storage_degradation_multiplier: "储能衰减权重" };
    root.innerHTML = Object.entries(labels).map(([key, label]) => `<label>${label}<input data-opt="${key}" type="number" min="0" step="0.01" value="${esc(state.optimization[key])}"><small>影响 MILP 目标函数</small></label>`).join("");
  }
  function collectOptimization() { const result = {}; $$("[data-opt]").forEach((input) => { result[input.dataset.opt] = Number(input.value); }); return result; }
  function renderInputs() {
    const kind = $("#curve-kind")?.value || "demand_kw"; const values = state.caseData?.forecast?.[kind] || []; const root = $("#input-curve-form"); if (!root) return;
    const pageSize = 12; const pages = Math.max(1, Math.ceil(values.length / pageSize)); state.curvePage = Math.max(0, Math.min(state.curvePage, pages - 1)); const offset = state.curvePage * pageSize;
    root.innerHTML = values.slice(offset, offset + pageSize).map((value, index) => { const absolute = offset + index; return `<label>${absolute + 1}<input data-curve="${absolute}" type="number" min="0" step="0.1" value="${esc(value)}"><small>${absolute < 4 ? "近端" : "小时"}</small></label>`; }).join("");
    const page = $("#curve-page"); if (page) page.textContent = `${state.curvePage + 1} / ${pages}`; const previous = $("#curve-prev"); const next = $("#curve-next"); if (previous) previous.disabled = state.curvePage === 0; if (next) next.disabled = state.curvePage >= pages - 1;
    const chart = $("#input-chart"); if (chart) chart.innerHTML = line(values.slice(offset, offset + pageSize), kind === "demand_kw" ? "#6da8ff" : kind === "wind_kw" ? "#4fd1a5" : "#f3c969");
  }
  function collectInputs() { const updated = structuredClone(state.caseData); const kind = $("#curve-kind")?.value || "demand_kw"; $$("[data-curve]").forEach((input) => { updated.forecast[kind][Number(input.dataset.curve)] = Number(input.value); }); return updated; }
  function renderNetwork() { const root = $("#network-summary"); if (!root || !state.network) return; root.innerHTML = `<div class="row"><span>模型名称</span><strong>${esc(state.network.name)}</strong></div><div class="row"><span>基准容量</span><strong>${number(state.network.base_mva, 2)} MVA</strong></div><div class="row"><span>母线 / 线路</span><strong>${state.network.buses.length} / ${state.network.lines.length}</strong></div><div class="row"><span>参数</span><strong>${Object.keys(state.network.parameters || {}).length} 项</strong></div>`; const textarea = $("#network-json"); if (textarea && !textarea.value) textarea.value = JSON.stringify(state.network, null, 2); }
  function renderPlan(kind) {
    const plan = state.plans[kind]; const root = $(`#plan-${kind}`); if (!root) return;
    if (!plan) { root.innerHTML = '<div class="panel empty">数据库中没有该层级计划，请先求解。</div>'; return; }
    state.latestPlanId = plan.plan_id; const byGenerator = Object.entries(plan.fuel_summary?.by_generator_liters || {}).map(([id, value]) => `<div class="row"><span>${esc(id)} 柴油消耗</span><strong>${number(value)} L</strong></div>`).join("");
    root.innerHTML = `<div class="plan"><div class="panel"><div class="metric"><span>状态</span><strong>${esc(plan.status)}</strong></div><div class="metric"><span>目标值</span><strong>${number(plan.solver_report?.objective, 1)}</strong></div><div class="metric"><span>柴油总量</span><strong>${number(plan.fuel_summary?.total_liters)} L</strong></div><div class="row"><span>时间步长</span><strong>${plan.horizon_steps} × ${plan.interval_minutes} 分钟</strong></div>${byGenerator}</div><div class="panel"><h3>柴油消耗曲线</h3><div class="chart">${line(plan.fuel_summary?.interval_liters)}</div><div class="row"><span>求解器 / 终止</span><strong>${esc(plan.solver_report?.solver)} / ${esc(plan.solver_report?.termination)}</strong></div><div class="row"><span>MIP Gap</span><strong>${number(plan.solver_report?.mip_gap, 4)}</strong></div><div class="button-row"><button class="primary plan-control" data-action="publish" data-plan-id="${esc(plan.plan_id)}">发布此版本</button><button class="plan-control" data-action="validate" data-plan-id="${esc(plan.plan_id)}">校核</button></div></div></div>`;
    $$(".plan-control", root).forEach((button) => button.addEventListener("click", () => control(button.dataset.action, button.dataset.planId)));
  }
  function renderResults() {
    const plan = state.overview?.latest_plan; const summary = $("#result-summary"); if (summary) summary.innerHTML = plan ? `<div class="row"><span>计划类型</span><strong>${esc(plan.kind)}</strong></div><div class="row"><span>计划版本</span><strong>${esc(plan.plan_id)}</strong></div><div class="row"><span>创建时间</span><strong>${esc(plan.created_at)}</strong></div><div class="row"><span>柴油消耗</span><strong>${number(plan.fuel_summary?.total_liters)} L</strong></div>` : '<span class="muted">暂无输出结果</span>'; const chart = $("#result-chart"); if (chart) chart.innerHTML = plan ? line(plan.fuel_summary?.cumulative_liters, "#f3c969") : '<span class="muted">暂无曲线</span>'; const history = $("#history-list"); if (history) history.innerHTML = Object.values(state.plans).map((item) => `<div class="row"><span>${esc(item.kind)} · ${esc(item.plan_id.slice(0, 8))}</span><strong>${number(item.fuel_summary?.total_liters)} L</strong></div>`).join("") || '<span class="muted">暂无历史计划</span>'; }
  async function loadCase() { state.caseData = await api("/api/case"); renderCase(); renderInputs(); renderOverview(); }
  async function loadOverview() { state.overview = await api("/api/overview"); state.plans = { ...(state.plans || {}), ...(state.overview.plans || {}) }; if (state.overview.latest_plan) state.latestPlanId = state.overview.latest_plan.plan_id; renderOverview(); renderResults(); ["weekly", "daily", "hourly"].forEach(renderPlan); }
  async function loadSolvers() { state.solvers = await api("/api/solver"); const select = $("#solver-select"); if (select) { select.innerHTML = Object.keys(state.solvers).map((name) => `<option value="${esc(name)}" ${name === state.activeSolver ? "selected" : ""}>${esc(name.toUpperCase())}</option>`).join(""); select.addEventListener("change", () => { state.activeSolver = select.value; }); } const root = $("#solver-list"); if (root) root.innerHTML = Object.entries(state.solvers).map(([name, info]) => `<div class="row"><strong>${esc(name.toUpperCase())}</strong><span class="${info.available ? "ok" : "bad"}">${info.available ? "可用" : "不可用"}</span></div>`).join(""); }
  async function loadAudit() { const result = await api("/api/audit"); const root = $("#audit"); if (root) root.innerHTML = result.events.map((event) => `<div class="row"><strong>${esc(event.action)}</strong><span>${esc(event.detail)}<small>${esc(event.created_at)}</small></span></div>`).join("") || '<span class="muted">暂无审计记录</span>'; }
  async function solve(kind) { try { toast(`正在求解 ${kind} MILP…`); const result = await api(`/api/${kind}-plan/solve`, { method: "POST", body: JSON.stringify({ solver: state.activeSolver, time_limit_seconds: Number($("#time-limit")?.value || 30), mip_gap: Number($("#mip-gap")?.value || 0.01) }) }); state.plans[kind] = result; state.latestPlanId = result.plan_id; renderPlan(kind); await loadOverview(); toast(`${kind} 计划已保存到 SQLite`); } catch (error) { toast(error.message, true); } }
  async function control(action, planId = state.latestPlanId) { try { const query = planId ? `?plan_id=${encodeURIComponent(planId)}` : ""; await api(`/api/control/${action}${query}`, { method: "POST" }); await loadOverview(); await loadAudit(); toast("控制操作已完成"); } catch (error) { toast(error.message, true); } }
  async function saveDevice() { state.caseData = await api("/api/case", { method: "PUT", body: JSON.stringify(collectCase()) }); renderCase(); toast("设备参数和油耗曲线已保存"); }
  async function saveOptimization() { state.optimization = await api("/api/optimization-params", { method: "PUT", body: JSON.stringify(collectOptimization()) }); renderOptimization(); toast("优化参数已保存"); }
  async function saveInputs() { state.caseData = await api("/api/case", { method: "PUT", body: JSON.stringify(collectInputs()) }); renderInputs(); toast("输入曲线已保存"); }
  async function saveNetwork() { const model = JSON.parse($("#network-json").value); state.network = await api("/api/network-model", { method: "PUT", body: JSON.stringify(model) }); renderNetwork(); toast("电网模型已保存"); }
  function bind() {
    $$("#tabs button").forEach((button) => button.addEventListener("click", () => setTab(button.dataset.tab)));
    $("#refresh")?.addEventListener("click", () => loadOverview().then(() => toast("总览已刷新")).catch((error) => toast(error.message, true)));
    $("#save-case, #save-device")?.addEventListener("click", () => saveDevice().catch((error) => toast(error.message, true)));
    $("#save-optimization")?.addEventListener("click", () => saveOptimization().catch((error) => toast(error.message, true)));
    $("#save-inputs")?.addEventListener("click", () => saveInputs().catch((error) => toast(error.message, true)));
    $("#save-network")?.addEventListener("click", () => saveNetwork().catch((error) => toast(`电网模型 JSON 无效：${error.message}`, true)));
    $("#curve-kind")?.addEventListener("change", () => { state.curvePage = 0; renderInputs(); });
    $("#curve-prev")?.addEventListener("click", () => { state.curvePage -= 1; renderInputs(); });
    $("#curve-next")?.addEventListener("click", () => { state.curvePage += 1; renderInputs(); });
    $("#reload-results")?.addEventListener("click", () => Promise.all([loadOverview(), loadPlans()]).then(() => toast("输出结果已刷新")).catch((error) => toast(error.message, true)));
    $("#reload-audit")?.addEventListener("click", () => loadAudit().then(() => toast("审计已刷新")).catch((error) => toast(error.message, true)));
    $("#load-network-file")?.addEventListener("click", () => { const file = $("#network-file")?.files?.[0]; if (!file) { toast("请选择 JSON 电网模型文件", true); return; } const reader = new FileReader(); reader.onload = () => { $("#network-json").value = reader.result; toast("已读取 JSON 文件，请检查后保存"); }; reader.readAsText(file, "utf-8"); });
    $$(".solve").forEach((button) => button.addEventListener("click", () => solve(button.dataset.kind)));
    $$("[data-control]").forEach((button) => button.addEventListener("click", () => control(button.dataset.control)));
  }
  async function loadPlans() { for (const kind of ["weekly", "daily", "hourly"]) { const result = await api(`/api/plans/${kind}?limit=20`); if (result.plans?.length) state.plans[kind] = result.plans[0]; } ["weekly", "daily", "hourly"].forEach(renderPlan); renderResults(); }
  async function init() {
    bind();
    try { await Promise.all([loadCase(), loadSolvers(), loadOverview(), loadAudit(), api("/api/health").then((health) => { const node = $("#connection"); if (node) node.textContent = health.case_loaded ? "SQLite 已连接" : "SQLite 已连接 · 待加载"; })]); state.optimization = await api("/api/optimization-params"); state.network = await api("/api/network-model"); renderOptimization(); renderNetwork(); renderInputs(); renderResults(); toast("数据库数据已加载"); }
    catch (error) { const node = $("#connection"); if (node) node.textContent = "连接失败"; toast(error.message, true); }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
