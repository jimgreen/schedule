(() => {
  'use strict';
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const kinds = ['weekly', 'daily', 'hourly'];
  const names = {weekly:'周前计划', daily:'日前计划', hourly:'小时前滚动'};
  const horizons = {weekly:'168 × 60 分钟 · 7 天', daily:'96 × 15 分钟 · 24 小时', hourly:'16 × 15 分钟 · 4 小时'};
  const optLabels = {fuel_cost_multiplier:'燃油成本权重', startup_cost_multiplier:'启停成本权重', curtailment_penalty:'弃风弃光成本 (元/kWh)', reserve_penalty:'备用容量成本 (元/kWh)', lost_load_penalty:'失负荷惩罚 (元/kWh)', baseline_deviation_penalty:'基线偏差成本 (元/kWh)', storage_degradation_multiplier:'储能衰减权重'};
  const fieldLabels = {id:'设备编号',name:'名称',fuel_type:'燃料类型',kind:'能源类型',min_power_kw:'最小功率 (kW)',max_power_kw:'最大功率 (kW)',ramp_up_kw_per_step:'升出力限制 (kW/步)',ramp_down_kw_per_step:'降出力限制 (kW/步)',min_up_steps:'最小开机时长 (步)',min_down_steps:'最小停机时长 (步)',startup_cost:'启动成本 (元)',shutdown_cost:'停机成本 (元)',fuel_price_per_liter:'柴油价格 (元/L)',initial_on:'初始开机',initial_power_kw:'初始出力 (kW)',initial_up_steps:'初始已开机 (步)',initial_down_steps:'初始已停机 (步)',capacity_kw:'额定功率 (kW)',capacity_kwh:'容量 (kWh)',max_charge_kw:'充电上限 (kW)',max_discharge_kw:'放电上限 (kW)',charge_efficiency:'充电效率',discharge_efficiency:'放电效率',min_soc:'SOC 下限',max_soc:'SOC 上限',initial_soc:'初始 SOC',terminal_soc:'目标 SOC (留空不约束)',degradation_cost_per_kwh:'衰减成本 (元/kWh)',min_kw:'最小功率 (kW)',max_kw:'最大功率 (kW)',shiftable_energy_kwh:'每日可调能量 (kWh)',adjustment_cost_per_kwh:'调整成本 (元/kWh)',import_limit_kw:'进口上限 (kW)',export_limit_kw:'出口上限 (kW)',import_price_per_kwh:'购电价格 (元/kWh)',export_price_per_kwh:'售电价格 (元/kWh)'};
  const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = (v,d=2) => v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toFixed(d);
  const clone = v => structuredClone(v);
  const size = () => innerHeight < 650 ? 3 : innerWidth < 800 ? 4 : 6;
  const rowCount = () => innerHeight < 700 || innerWidth < 800 ? 3 : 5;
  const state = {kind:'weekly', feature:'optimization', shared:null, configs:{}, dirty:{}, solvers:{}, case:null, deviceDirty:false, deviceIndex:0, networkText:'', networkChunks:[], networkDirty:false, plans:{}, summaries:{}, comparisons:{}, curveHistory:{}, audit:{}, controls:{}, validations:{}, parents:{}, pages:{opt:0,curve:0,device:0,network:0,history:0,dispatch:0,stats:0,control:0}, resultTab:'chart',controlTab:'audit', busy:false};
  const toast = (text,error=false) => { $('#toast').textContent=String(text).slice(0,450); $('#toast').classList.toggle('error',error); };
  async function api(path,options={}) {
    const response = await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});
    const body = await response.json();
    if(!response.ok) {
      const detail=body.detail;
      throw new Error(Array.isArray(detail)?detail.map(v=>`${v.loc?.slice(1).join('.')}：${v.msg}`).join('；'):typeof detail==='string'?detail:`请求失败 (${response.status})`);
    }
    return body;
  }
  const put = (path,body) => api(path,{method:'PUT',body:JSON.stringify(body)});
  function bind(selector,event,handler) {
    $(selector)?.addEventListener(event,e=>{try {Promise.resolve(handler(e)).catch(err=>toast(err.message,true));} catch(err){toast(err.message,true);}});
  }
  async function action(button,fn) {
    if(state.busy) return;
    state.busy=true; if(button)button.disabled=true; $('#solve').disabled=true;
    try { await fn(); } finally { state.busy=false; if(button)button.disabled=false; $('#solve').disabled=false; }
  }
  state.savedConfigs={};state.historyRequest=0;
  function dirty() { state.dirty[state.kind]=JSON.stringify(state.configs[state.kind])!==JSON.stringify(state.savedConfigs[state.kind]); renderDirty(); }
  function renderDirty() {
    $('#dirty').textContent=state.dirty[state.kind]?'本模块有未保存修改':'本模块已保存';
    $('#dirty').classList.toggle('dirty',!!state.dirty[state.kind]);
    $('#device-dirty').textContent=state.deviceDirty?'共享设备有未保存修改':'共享设备已保存';
    $('#network-dirty').textContent=state.networkDirty?'模型草稿尚未保存':'共享模型已保存';
  }
  function page(key,total,count=size()) {
    const pages=Math.max(1,Math.ceil(total/count));
    state.pages[key]=Math.max(0,Math.min(state.pages[key],pages-1));
    const start=state.pages[key]*count;
    $(`#${key}-page`) && ($(`#${key}-page`).textContent=`${state.pages[key]+1} / ${pages} 页 · ${total} 项`);
    $$(`[data-page^="${key}:"]`).forEach(b=>b.disabled=b.dataset.page.endsWith('-1')?state.pages[key]===0:state.pages[key]===pages-1);
    return [start,start+count];
  }
  function inputField(label,attrs,value,type='number') {
    return `<label>${esc(label)}<input ${attrs} type="${type}" step="any" value="${esc(value ?? '')}"></label>`;
  }
  function chart(series,unit) {
    if(!series.length || !series[0].values?.length) return '<p class="muted">暂无结果，请先计算本模块计划。</p>';
    const values=series.flatMap(s=>s.values), max=Math.max(...values,1), n=series[0].values.length;
    const colors=['#58d5b3','#75aaff'];
    return `<svg viewBox="0 0 640 145" preserveAspectRatio="none" role="img" aria-label="${esc(unit)}曲线"><path d="M45 10V118H625" fill="none" stroke="#38506e"/><text x="0" y="15">${fmt(max,0)}</text><text x="18" y="118">0</text><text x="45" y="140">1</text><text x="590" y="140">${n} 时段</text>${series.map((s,i)=>`<polyline fill="none" stroke="${colors[i%2]}" stroke-width="2" points="${s.values.map((v,j)=>`${45+j*580/Math.max(n-1,1)},${118-Number(v)*100/max}`).join(' ')}"/><text x="${160+i*170}" y="12" style="fill:${colors[i%2]}">${esc(s.name)} (${esc(unit)})</text>`).join('')}</svg>`;
  }
  function renderOptimization() {
    const config=state.configs[state.kind]; if(!config)return;
    $('#solver-select').innerHTML=Object.entries(state.solvers).map(([key,info])=>`<option value="${key}">${key.toUpperCase()} · ${info.available?'可用':'未安装'}</option>`).join('');
    $('#solver-select').value=config.solver; $('#time-limit').value=config.time_limit_seconds; $('#mip-gap').value=config.mip_gap;
    $('#solver-info').textContent=`${names[state.kind]}独立求解配置 · 优先 CPLEX，切换求解器后保存。可用性表示接口已安装，许可证以实际求解为准。`;
    const entries=Object.entries(optLabels), [a,b]=page('opt',entries.length);
    $('#optimization-form').innerHTML=entries.slice(a,b).map(([key,label])=>inputField(label,`data-opt="${key}" min="0"`,config.optimization[key])).join('');
  }
  function renderInputs() {
    const config=state.configs[state.kind]; if(!config)return;
    const key=$('#curve-kind').value, values=config.forecast[key], [a,b]=page('curve',values.length);
    $('#reserve-fraction').value=config.forecast.reserve_fraction;
    const start=config.start_time?new Date(config.start_time):null;
    $('#start-time').value=start?new Date(start.getTime()-start.getTimezoneOffset()*60000).toISOString().slice(0,16):'';
    $('#input-curve-form').innerHTML=values.slice(a,b).map((v,i)=>inputField(`第 ${a+i+1} 时段 · +${(a+i)*config.input_interval_minutes} min`,`data-curve="${a+i}" min="0"`,v)).join('');
    $('#input-chart').innerHTML=chart([{name:$('#curve-kind').selectedOptions[0].textContent,values}], 'kW');
    const history=state.curveHistory[`${state.kind}:${key}`]||[];
    $('[data-curve-action="undo"]').disabled=!history.length;
    const mode=$('#input-mode').value;
    for(const name of ['edit','batch','settings'])$(`#input-${name}`).hidden=mode!==name;
    $('#curve-jump').max=values.length;$('#curve-jump').value=a+1;
    $('#curve-from').max=values.length;$('#curve-to').max=values.length;
    if(!$('#curve-to').value||Number($('#curve-to').value)>values.length)$('#curve-to').value=values.length;
  }
  function curveKey() { return `${state.kind}:${$('#curve-kind').value}`; }
  function rememberCurve() {
    const key=curveKey(), history=state.curveHistory[key]||[];
    history.push(clone(state.configs[state.kind].forecast[$('#curve-kind').value]));
    state.curveHistory[key]=history.slice(-20);
  }
  function curveAction(action) {
    const config=state.configs[state.kind], name=$('#curve-kind').value, values=config.forecast[name];
    if(!values?.length)return;
    if(action==='undo') {
      const history=state.curveHistory[curveKey()]||[], previous=history.pop();
      if(!previous)return;
      config.forecast[name]=previous; state.curveHistory[curveKey()]=history; $('#batch-status').textContent='已撤销上一次批量调整';dirty(); renderInputs(); return;
    }
    if(action==='apply') {
      const scale=Number($('#curve-scale').value), offset=Number($('#curve-offset').value);
      if(!$('#curve-scale').value||!$('#curve-offset').value)throw new Error('比例和偏移不能为空');
      const start=Number($('#curve-from').value),end=Number($('#curve-to').value);
      const next=ScheduleData.transformCurve(values,start,end,scale,offset);
      rememberCurve();config.forecast[name]=next;
      $('#batch-status').textContent=`已调整 ${start}–${end} 时段，共 ${end-start+1} 点；可撤销。`;
    }
    dirty(); renderInputs();
  }
  function renderPlan() {
    const plan=state.plans[state.kind];
    $('#result-summary').innerHTML=plan?[
      ['状态',plan.status],['目标值',fmt(plan.solver_report.objective)],['柴油总量',`${fmt(plan.fuel_summary.total_liters)} L`],['求解耗时',`${fmt(plan.solver_report.elapsed_seconds)} s`]
    ].map(([l,v])=>`<div class="metric"><small>${esc(l)}</small><strong>${esc(v)}</strong></div>`).join(''):'<p class="muted">本模块尚无结果</p>';
    for(const name of ['chart','dispatch','statistics','comparison'])$(`#${name}-result`).hidden=state.resultTab!==name;
    $$('[data-result]').forEach(b=>b.classList.toggle('active',b.dataset.result===state.resultTab));
    const selected=$('#result-resource').value, options=ScheduleData.resources(plan);
    $('#result-resource').innerHTML=options.map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join('');
    $('#result-resource').value=options.some(([key])=>key===selected)?selected:'system';
    const resource=$('#result-resource').value, type=resource.split(':')[0], oldCurve=$('#result-curve').value;
    const curves=type==='system'?[['fuel','柴油消耗 (L/时段)'],['cumulative','累计柴油 (L)'],['power','负荷与柴油出力'],['renewable','风光消纳与弃电']]:type==='g'?[['power','机组出力'],['fuel','机组油耗']]:type==='b'?[['soc','储能电量 / SOC'],['power','充放电功率']]:[['power','功率']];
    $('#result-curve').innerHTML=curves.map(([value,label])=>`<option value="${value}">${label}</option>`).join('');
    if(curves.some(([key])=>key===oldCurve))$('#result-curve').value=oldCurve;
    const view=ScheduleData.resultView(plan,resource,$('#result-curve').value);
    $('#result-chart').innerHTML=chart(view.series,view.unit);
    const gen=resource.startsWith('g:')?resource.slice(2):null;
    $('#generator-fuel').textContent=plan?`柴油消耗量统计：${gen?gen+' '+fmt(plan.fuel_summary.by_generator_liters[gen]):'全站 '+fmt(plan.fuel_summary.total_liters)} L · ${plan.solver_report.solver.toUpperCase()} · Gap ${fmt(plan.solver_report.mip_gap,4)}`:'';
    $('#resource-label').hidden=!['chart','dispatch'].includes(state.resultTab);
    $('#result-extra').hidden=plan?.status!=='not_solved';
    $('#result-extra').textContent=plan?.status==='not_solved'?`没有可用解：${plan.solver_report.termination}。请检查备用、容量和初始状态。`:'';
    const group=$('#statistics-group').value;
    const statRows=ScheduleData.statistics(plan,group).map(([label,value,unit])=>[label,fmt(value,unit==='个'?0:3),unit]);
    const [sa,sb]=page('stats',statRows.length,rowCount());
    $('#statistics-table').innerHTML=plan?table(['指标','数值','单位'],statRows.slice(sa,sb)):'<p class="notice">本模块暂无统计结果。</p>';
    const [a,b]=page('dispatch',view.rows.length,rowCount());
    $('#dispatch-table').innerHTML=table(view.headers,view.rows.slice(a,b).map(r=>r.map((v,i)=>i?fmt(v):v)));
    const comparison=state.comparisons[state.kind];
    const match=comparison?.right.plan_id===plan?.plan_id;
    $('#compare-note').textContent=match?`当前 ${comparison.right.plan_id}；上一版 ${comparison.left.plan_id}。差值 = 当前 − 上一版。${comparison.same_start_time?'':'两版起点不同；'}输入、设备、求解器可能不同，差值仅供方案分析。`:'点击“比较当前/上一版”加载同模块的相邻历史版本。';
    $('#compare-table').innerHTML=match?table(['指标','上一版','当前','差值'],[['目标值','objective'],['柴油 L','total_liters'],['耗时 s','elapsed_seconds']].map(([label,k])=>[label,fmt(comparison.left[k]),fmt(comparison.right[k]),fmt(comparison.delta_right_minus_left[k])])):'';
  }
  function table(headers,rows) { return `<table><thead><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`; }
  async function loadHistory(kind=state.kind,refresh=false) {
    const request=++state.historyRequest;
    const offset=state.pages.history*6;
    const result=await api(`/api/plan-summaries?kind=${kind}&limit=7&offset=${offset}`);
    state.summaries[kind]=result.plans;
    if(state.kind!==kind||request!==state.historyRequest)return;
    const rows=result.plans.slice(0,6), current=state.plans[kind]?.plan_id;
    $('#plan-select').innerHTML=rows.map(p=>`<option value="${esc(p.plan_id)}">${esc(p.plan_id)} · ${esc(new Date(p.created_at).toLocaleString())}</option>`).join('')||'<option value="">暂无结果</option>';
    if(rows.some(p=>p.plan_id===current)&&!refresh)$('#plan-select').value=current;
    $('#history-page').textContent=`版本页 ${state.pages.history+1}`;
    $('[data-page="history:-1"]').disabled=state.pages.history===0;
    $('[data-page="history:1"]').disabled=result.plans.length<=6;
    const id=$('#plan-select').value;
    const loaded=id?(state.plans[kind]?.plan_id===id&&!refresh?state.plans[kind]:await api(`/api/plans/id/${encodeURIComponent(id)}`)):null;
    if(state.kind!==kind||request!==state.historyRequest)return;
    state.plans[kind]=loaded;
    if(state.kind===kind)renderPlan();
  }
  async function compareCurrent() {
    const kind=state.kind, rows=state.summaries[kind]||[], current=state.plans[kind]?.plan_id;
    const index=rows.findIndex(row=>row.plan_id===current), previous=rows[index+1];
    if(!current||index<0||!previous)throw new Error('当前版本没有可比较的上一版');
    state.comparisons[kind]=await api(`/api/plans/${kind}/compare?left_id=${encodeURIComponent(previous.plan_id)}&right_id=${encodeURIComponent(current)}`);
    if(state.kind===kind){state.resultTab='comparison';renderPlan();}
  }
  function renderControl() {
    const kind=state.kind, control=state.controls[kind]||{}, plan=state.plans[kind];
    $('#control-summary').textContent=`操作计划：${plan?.plan_id||'无'}；已发布：${control.last_published_plan_id||'无'}；已模拟执行：${control.last_executed_plan_id||'无'}。在输出结果中选择版本。`;
    $('#execute').hidden=kind!=='hourly';
    $('#parent-select').disabled=kind==='weekly';
    $('#parent-note').textContent=kind==='weekly'?'周前计划生成基线':'设置起点后按时间对齐基线；均留空时按相对起点对齐。';
    $$('[data-control-tab]').forEach(b=>b.classList.toggle('active',b.dataset.controlTab===state.controlTab));
    const validation=state.validations[kind];
    if(state.controlTab==='validation') {
      const rows=validation?.issues||[], [a,b]=page('control',rows.length,rowCount());
      $('#control-list').innerHTML=validation?`<p class="notice">${esc(validation.plan_id)}：${validation.valid?'校核通过':'校核未通过'} · 最大功率偏差 ${fmt(validation.metrics.max_power_balance_error_kw,4)} kW</p><table>${rows.slice(a,b).map(r=>`<tr><td>${r.step==null?'全部':r.step+1}</td><td>${esc(r.message)}</td></tr>`).join('')}</table>`:'<p class="notice">点击校核，检查本模块选中计划的输入快照与出力。</p>';
    } else {
      const rows=state.audit[kind]||[];
      $('#control-list').innerHTML=rows.length?`<table><thead><tr><th>操作 / 版本</th><th>详情</th><th>时间</th></tr></thead><tbody>${rows.slice(0,rowCount()).map(r=>`<tr><td>${esc(r.action)}<br><small>${esc(r.plan_id||'配置')}</small></td><td>${esc(r.detail)}</td><td>${esc(new Date(r.created_at).toLocaleString())}</td></tr>`).join('')}</tbody></table>`:'<p class="notice">本模块暂无审计记录。</p>';
      $('#control-page').textContent=`审计页 ${state.pages.control+1}`;
      $('[data-page="control:-1"]').disabled=state.pages.control===0;
      $('[data-page="control:1"]').disabled=rows.length<=rowCount();
    }
  }
  async function loadControl() {
    const kind=state.kind;
    const [control,audit]=await Promise.all([api(`/api/modules/${kind}/control`),api(`/api/modules/${kind}/audit?limit=${rowCount()+1}&offset=${state.pages.control*rowCount()}`)]);
    state.controls[kind]=control; state.audit[kind]=audit.events;
    if(kind!==state.kind)return;
    const parent={daily:'weekly',hourly:'daily'}[kind];
    const rows=parent?(await api(`/api/plan-summaries?kind=${parent}&limit=30`)).plans:[];
    if(kind!==state.kind)return;
    $('#parent-select').innerHTML='<option value="">不指定</option>'+rows.filter(r=>['solved','feasible'].includes(r.status)).map(r=>`<option value="${esc(r.plan_id)}">${esc(r.plan_id)}</option>`).join('');
    $('#parent-select').value=state.parents[kind]||'';
    renderControl();
  }
  function deviceEntries() {
    if(!state.case)return [];
    return ['generators','renewables','batteries','flexible_loads'].flatMap(key=>state.case[key].map((item,i)=>({key,index:i,item}))).concat([{key:'grid',item:state.case.grid}]);
  }
  function renderDevices() {
    const entries=deviceEntries(); state.deviceIndex=Math.min(state.deviceIndex,entries.length-1);
    $('#device-select').innerHTML=entries.map((v,i)=>`<option value="${i}">${esc(v.item.name||'联络线')} · ${esc(v.item.id||'grid')}</option>`).join('');
    $('#device-select').value=state.deviceIndex;
    const item=entries[state.deviceIndex]?.item; if(!item)return;
    const fields=Object.keys(item).filter(k=>!['fuel_curve','fuel_type','id','kind'].includes(k)).map(k=>({key:k,label:fieldLabels[k]||k,value:item[k]}));
    item.fuel_curve?.forEach((p,i)=>{fields.push({curve:i,key:'power_kw',label:`油耗点 ${i+1} · 出力 kW`,value:p.power_kw},{curve:i,key:'liters_per_hour',label:`油耗点 ${i+1} · 油耗 L/h`,value:p.liters_per_hour});});
    const [a,b]=page('device',fields.length);
    $('#device-form').innerHTML=fields.slice(a,b).map(f=>typeof f.value==='boolean'?`<label>${esc(f.label)}<select data-device-field="${f.key}"><option value="true" ${f.value?'selected':''}>开启</option><option value="false" ${!f.value?'selected':''}>关闭</option></select></label>`:inputField(f.label,`data-device-field="${f.key}" ${f.curve==null?'':`data-fuel-point="${f.curve}"`}`,f.value,typeof f.value==='string'?'text':'number')).join('');
    renderDirty();
  }
  function splitNetwork() {
    const width=Math.max(16,Math.floor(($('#network-json').clientWidth||500)/8)-3);
    const maxLines=Math.max(3,Math.floor(($('#network-json').clientHeight||200)/20)-1);
    const text=state.networkText, chunks=[]; let start=0, lines=1, column=0;
    for(let i=0;i<text.length;i++) {
      column += text.charCodeAt(i)>255?2:1;
      if(text[i]==='\n'||column>=width){lines++;column=0;}
      if(lines>=maxLines){chunks.push(text.slice(start,i+1));start=i+1;lines=1;}
    }
    chunks.push(text.slice(start)); state.networkChunks=chunks;
  }
  function renderNetwork() {
    splitNetwork();const [a]=page('network',state.networkChunks.length,1);
    $('#network-json').value=state.networkChunks[a]||'';
    try {const m=JSON.parse(state.networkText);$('#network-summary').textContent=`${m.name} · ${m.base_mva} MVA · ${m.buses.length} 母线 / ${m.lines.length} 线路`;}catch{$('#network-summary').textContent='JSON 编辑草稿：保存时校验完整模型';}
    renderDirty();
  }
  function show() {
    $('#module-view').hidden=!!state.shared; $('#device-view').hidden=state.shared!=='device'; $('#network-view').hidden=state.shared!=='network';
    $$('[data-module]').forEach(b=>b.classList.toggle('active',!state.shared&&b.dataset.module===state.kind));
    $$('[data-shared]').forEach(b=>b.classList.toggle('active',b.dataset.shared===state.shared));
    if(state.shared==='device'){renderDevices();return;} if(state.shared==='network'){renderNetwork();return;}
    $('#module-title').textContent=names[state.kind]; $('#horizon-label').textContent=horizons[state.kind];
    $('#scope-label').textContent=`当前：${names[state.kind]} · 本模块配置独立保存`;
    $$('.feature').forEach(v=>v.hidden=v.id!==state.feature);
    $$('[data-function]').forEach(b=>b.classList.toggle('active',b.dataset.function===state.feature));
    $('#save-module').hidden=!['optimization','inputs'].includes(state.feature);
    $('#module-tools').hidden=!['optimization','inputs'].includes(state.feature);
    renderDirty(); if(state.feature==='optimization')renderOptimization();if(state.feature==='inputs')renderInputs();if(state.feature==='results')renderPlan();if(state.feature==='control')renderControl();
  }
  async function activate(feature=state.feature) {
    state.feature=feature; show();
    if(feature==='results'||feature==='control'){await loadHistory();if(feature==='control')await loadControl();}
  }
  function download(name,value) {
    const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function downloadText(name,text,mime='text/plain') {
    const url=URL.createObjectURL(new Blob([text],{type:mime})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function exportCsv() {
    const plan=state.plans[state.kind]; if(!plan?.dispatch?.length)throw new Error('本模块暂无结果');
    const rows=[['step','timestamp','demand_kw','diesel_kw','grid_import_kw','grid_export_kw','fuel_liters','lost_load_kw']];
    plan.dispatch.forEach((row,index)=>rows.push([row.step+1,row.timestamp||'',row.demand_kw,Object.values(row.generators||{}).reduce((sum,g)=>sum+g.power_kw,0),row.grid_import_kw,row.grid_export_kw,plan.fuel_summary.interval_liters[index]||0,row.lost_load_kw]));
    downloadText(`${plan.plan_id}.csv`,rows.map(row=>row.map(value=>`"${String(value??'').replaceAll('"','""')}"`).join(',')).join('\r\n'),'text/csv;charset=utf-8');
  }
  async function readFile(event) {
    const file=event.target.files?.[0]; if(!file)return null;
    if(file.size>8*1024*1024)throw new Error('JSON 文件不能超过 8 MB');
    const data=JSON.parse(await file.text());event.target.value='';return data;
  }
  function bindEvents() {
    bind('#modules','click',async e=>{const b=e.target.closest('button');if(!b)return;if(b.dataset.module){state.kind=b.dataset.module;state.shared=null;state.pages={...state.pages,opt:0,curve:0,history:0,dispatch:0,control:0};await activate();}else{state.shared=b.dataset.shared;show();}});
    bind('#functions','click',e=>{const b=e.target.closest('[data-function]');if(b)return activate(b.dataset.function);});
    for(const [id,key] of [['solver-select','solver'],['time-limit','time_limit_seconds'],['mip-gap','mip_gap']])bind(`#${id}`,key==='solver'?'change':'input',e=>{state.configs[state.kind][key]=key==='solver'?e.target.value:Number(e.target.value);dirty();});
    bind('#optimization-form','input',e=>{if(e.target.dataset.opt){state.configs[state.kind].optimization[e.target.dataset.opt]=Number(e.target.value);dirty();}});
    bind('#curve-kind','change',()=>{state.pages.curve=0;renderInputs();});
    bind('#inputs','click',e=>{const button=e.target.closest('[data-curve-action]');if(button)curveAction(button.dataset.curveAction);});
    bind('#input-mode','change',renderInputs);
    bind('#curve-jump','change',e=>{const n=Number(e.target.value),total=state.configs[state.kind].forecast.demand_kw.length;if(!Number.isInteger(n)||n<1||n>total)throw new Error(`时段必须在 1–${total} 之间`);state.pages.curve=Math.floor((n-1)/size());renderInputs();});
    bind('#input-curve-form','input',e=>{if(e.target.dataset.curve!=null){state.configs[state.kind].forecast[$('#curve-kind').value][Number(e.target.dataset.curve)]=Number(e.target.value);dirty();}});
    bind('#reserve-fraction','input',e=>{state.configs[state.kind].forecast.reserve_fraction=Number(e.target.value);dirty();});
    bind('#start-time','change',e=>{state.configs[state.kind].start_time=e.target.value?new Date(e.target.value).toISOString():null;dirty();});
    bind('#save-module','click',e=>action(e.target,async()=>{const kind=state.kind, data=clone(state.configs[kind]);const saved=await put(`/api/modules/${kind}/config`,data);state.savedConfigs[kind]=clone(saved);if(JSON.stringify(data)===JSON.stringify(state.configs[kind]))state.configs[kind]=saved;state.dirty[kind]=JSON.stringify(state.configs[kind])!==JSON.stringify(saved);renderDirty();toast(`${names[kind]}参数和曲线已保存${state.dirty[kind]?'；随后编辑的草稿仍待保存':''}`);}));
    bind('#export-module','click',()=>download(`${state.kind}-config.json`,state.configs[state.kind]));
    bind('#import-module','change',async e=>{const kind=state.kind,data=await readFile(e);if(!data)return;const steps={weekly:168,daily:96,hourly:16}[kind];if(!data.optimization||!data.forecast||!['demand_kw','wind_kw','pv_kw'].every(k=>Array.isArray(data.forecast[k])&&data.forecast[k].length===steps)||data.input_interval_minutes!==(kind==='weekly'?60:15))throw new Error('导入文件的步数、步长或字段不属于当前模块');state.configs[kind]=data;state.dirty[kind]=true;show();toast('已导入本模块草稿，请保存后计算');});
    bind('#solve','click',e=>action(e.target,async()=>{const kind=state.kind;if(state.dirty[kind]||state.deviceDirty||state.networkDirty)throw new Error('请先保存当前模块和共享配置的修改');toast(`${names[kind]}正在求解…`);const result=await api(`/api/${kind}-plan/solve`,{method:'POST',body:JSON.stringify({parent_plan_id:state.parents[kind]||null})});state.plans[kind]=result;if(state.kind===kind&&!state.shared){state.pages.history=0;await activate('results');}toast(`${names[kind]}：${result.status==='not_solved'?'没有可用解，请检查输入和求解状态':'计算完成，结果已保存'}`,result.status==='not_solved');}));
    bind('#parent-select','change',e=>{state.parents[state.kind]=e.target.value;});
    bind('#plan-select','change',async e=>{const kind=state.kind;if(e.target.value)state.plans[kind]=await api(`/api/plans/id/${encodeURIComponent(e.target.value)}`);if(state.kind===kind)renderPlan();});
    bind('#reload-results','click',()=>loadHistory(state.kind,true));
    bind('#compare-result','click',e=>action(e.target,compareCurrent));
    bind('#export-result','click',()=>{const plan=state.plans[state.kind];if(!plan)throw new Error('本模块暂无结果');download(`${plan.plan_id}.json`,plan);});
    bind('#export-csv','click',exportCsv);
    bind('#result-curve','change',renderPlan);
    bind('#result-resource','change',()=>{state.pages.dispatch=0;renderPlan();});
    bind('#statistics-group','change',()=>{state.pages.stats=0;renderPlan();});
    bind('#result-tabs','click',e=>{const b=e.target.closest('[data-result]');if(b){state.resultTab=b.dataset.result;renderPlan();}});
    bind('#control-tabs','click',async e=>{const b=e.target.closest('[data-control-tab]');if(b){state.controlTab=b.dataset.controlTab;state.pages.control=0;await loadControl();}});
    bind('#control','click',e=>{const button=e.target.closest('[data-control]');if(!button)return;return action(button,async()=>{const kind=state.kind, selected=state.plans[kind]?.plan_id;if(!selected&&button.dataset.control!=='rollback')throw new Error('请先在本模块输出结果中选择计划');const result=await api(`/api/modules/${kind}/control/${button.dataset.control}${selected?`?plan_id=${encodeURIComponent(selected)}`:''}`,{method:'POST'});if(result.validation)state.validations[kind]=result.validation;if(kind===state.kind){state.pages.control=0;state.controlTab=result.validation?'validation':'audit';await loadControl();}toast(result.validation?result.validation.valid?'计划校核通过；本模块操作已完成':`校核发现 ${result.validation.issues.length} 个问题`:'本模块操作已完成',result.validation&&!result.validation.valid);});});
    bind('#device-select','change',e=>{state.deviceIndex=Number(e.target.value);state.pages.device=0;renderDevices();});
    bind('#device-form','input',e=>{const k=e.target.dataset.deviceField;if(!k)return;const item=deviceEntries()[state.deviceIndex].item;if(e.target.dataset.fuelPoint!=null)item.fuel_curve[Number(e.target.dataset.fuelPoint)][k]=Number(e.target.value);else item[k]=typeof item[k]==='boolean'?e.target.value==='true':e.target.type==='text'?e.target.value:e.target.value===''?null:Number(e.target.value);state.deviceDirty=true;renderDirty();});
    bind('#save-case','click',e=>action(e.target,async()=>{await put('/api/shared/devices',Object.fromEntries(['generators','renewables','batteries','flexible_loads','grid','fuel_price_per_liter'].map(k=>[k,state.case[k]])));state.deviceDirty=false;renderDirty();toast('共享设备已保存，三层配置保持独立');}));
    bind('#export-device','click',()=>download('shared-devices.json',Object.fromEntries(['generators','renewables','batteries','flexible_loads','grid','fuel_price_per_liter'].map(k=>[k,state.case[k]]))));
    bind('#import-device','change',async e=>{const data=await readFile(e);if(!data)return;if(!Array.isArray(data.generators)||!data.generators.length||!data.grid)throw new Error('缺少柴油机或联络线参数');for(const key of ['generators','renewables','batteries','flexible_loads','grid','fuel_price_per_liter'])if(key in data)state.case[key]=data[key];state.deviceDirty=true;state.deviceIndex=0;state.pages.device=0;renderDevices();toast('共享设备已载入草稿，请校验并保存');});
    bind('#network-json','input',e=>{state.networkChunks[state.pages.network]=e.target.value;state.networkText=state.networkChunks.join('');state.networkDirty=true;renderDirty();});
    bind('#network-file','change',async e=>{const data=await readFile(e);if(!data)return;state.networkText=JSON.stringify(data,null,2);state.networkDirty=true;state.pages.network=0;renderNetwork();toast('模型已加载为共享草稿，请保存');});
    bind('#save-network','click',e=>action(e.target,async()=>{const model=await put('/api/network-model',JSON.parse(state.networkText));state.networkText=JSON.stringify(model,null,2);state.networkDirty=false;renderNetwork();toast('共享电网模型已保存');}));
    bind('#export-network','click',()=>download('shared-network.json',JSON.parse(state.networkText)));
    bind('#app','click',async e=>{const b=e.target.closest('[data-page]');if(!b)return;const [key,delta]=b.dataset.page.split(':');state.pages[key]=Math.max(0,state.pages[key]+Number(delta));if(key==='opt')renderOptimization();if(key==='curve')renderInputs();if(key==='device')renderDevices();if(key==='network')renderNetwork();if(key==='history')await loadHistory();if(key==='dispatch'||key==='stats')renderPlan();if(key==='control'){if(state.controlTab==='audit')await loadControl();else renderControl();}});
    window.addEventListener('beforeunload',e=>{if(Object.values(state.dirty).some(Boolean)||state.deviceDirty||state.networkDirty){e.preventDefault();e.returnValue='';}});
    window.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();$(state.shared==='device'?'#save-case':state.shared==='network'?'#save-network':'#save-module').click();}});
    let resizeTimer;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(show,150);});
  }
  async function init() {
    try {
      // Load the case once first: this also migrates old shared curves into isolated copies.
      state.case=await api('/api/case');
      const [solvers,health,...configs]=await Promise.all([api('/api/solver'),api('/api/health'),...kinds.map(k=>api(`/api/modules/${k}/config`))]);
      state.solvers=solvers;kinds.forEach((k,i)=>{state.configs[k]=configs[i];state.savedConfigs[k]=clone(configs[i]);});state.networkText=JSON.stringify(state.case.network_model,null,2);
      $('#connection').textContent='SQLite 已连接';$('#db-path').textContent=health.database;
      bindEvents();show();toast('三层配置已独立加载；设备与电网模型共用');
    } catch(err){$('#connection').textContent='加载失败，请刷新重试';toast(err.message,true);}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
