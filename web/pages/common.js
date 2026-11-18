export const $ = (selector, root=document) => root.querySelector(selector);
export const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
export const names = {weekly:'周前计划',daily:'日前计划',hourly:'小时前滚动'};
export const esc = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const fmt = (v,d=2) => v==null||!Number.isFinite(Number(v))?'—':Number(v).toFixed(d);
export const clone = value => structuredClone(value);
export const size = () => innerHeight<650?(innerWidth<800?2:3):innerWidth<800?4:6;
export const rowCount = () => innerHeight<650?2:innerWidth<800?3:5;
export const auditRowCount = () => innerHeight<600&&innerWidth<800?1:Math.min(4,rowCount());
export function page(key,total,count=size()){
  const pages=Math.max(1,Math.ceil(total/count));state.pages[key]=Math.max(0,Math.min(state.pages[key]||0,pages-1));
  const label=$('#'+key+'-page');if(label)label.textContent=(state.pages[key]+1)+' / '+pages+' 页 · '+total+' 项';
  $$('[data-page^="'+key+':"]').forEach(b=>b.disabled=b.dataset.page.endsWith('-1')?state.pages[key]===0:state.pages[key]===pages-1);
  return [state.pages[key]*count,state.pages[key]*count+count];
}
export const state = {
  kind:document.body.dataset.kind,feature:document.body.dataset.feature,
  configs:{},savedConfigs:{},dirty:{},solvers:{},case:null,caseInitial:null,
  deviceDirty:false,deviceIndex:0,networkText:'',networkChunks:[],networkDirty:false,
  plans:{},summaries:{},summaryMeta:{},comparisons:{},curveHistory:{},audit:{},auditMeta:{},controls:{},validations:{},parents:{},
  historyStatus:'',auditAction:'',auditQuery:'',historyRequest:0,controlRequest:0,
  pages:{opt:0,curve:0,device:0,network:0,history:0,dispatch:0,stats:0,control:0,auditDetail:0},
  resultTab:'chart',controlTab:'operations',busy:false,solveRunning:false,pageRenderer:null,
};
export const session = {
  get(key){try{return JSON.parse(sessionStorage.getItem('schedule:'+key)||'null');}catch{return null;}},
  set(key,value){try{sessionStorage.setItem('schedule:'+key,JSON.stringify(value));return true;}catch{return false;}},
  remove(key){try{sessionStorage.removeItem('schedule:'+key);}catch{}}
};
export const pageUrl = (kind,feature='optimization') => `/${kind}_plan/${feature}.html`;
export function toast(text,error=false){$('#toast').textContent=String(text).slice(0,450);$('#toast').classList.toggle('error',error);}
export async function api(path,options={}){
  const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});
  const body=await response.json();
  if(!response.ok){const d=body.detail;const err=new Error(Array.isArray(d)?d.map(v=>`${v.loc?.slice(1).join('.')}：${v.msg}`).join('；'):typeof d==='string'?d:`请求失败 (${response.status})`);err.status=response.status;throw err;}
  return body;
}
export const put = (path,value) => api(path,{method:'PUT',body:JSON.stringify(value)});
export function bind(selector,event,handler){$(selector)?.addEventListener(event,e=>{try{Promise.resolve(handler(e)).catch(err=>toast(err.message,true));}catch(err){toast(err.message,true);}});}
export async function action(button,fn){
  if(state.busy)return;state.busy=true;if(button)button.disabled=true;if($('#solve'))$('#solve').disabled=true;
  try{return await fn();}finally{state.busy=false;if(button)button.disabled=false;if($('#solve'))$('#solve').disabled=state.solveRunning;}
}

let draft=null;
const draftKey = () => `draft:${state.kind||'shared'}:${state.feature}`;
const equal = (a,b) => JSON.stringify(a)===JSON.stringify(b);
export function configureDraft(saved,read,write,render){
  draft={saved:clone(saved),read,write,render,conflict:false,cached:true};
  const cached=session.get(draftKey());
  if(cached){
    if(equal(cached.base,saved)){write(clone(cached.value));toast('已恢复本标签页暂存草稿；保存后生效');}
    else if(equal(cached.value,saved)){session.remove(draftKey());}
    else{draft.conflict=true;$('#draft-tools').hidden=false;toast('服务器数据已变化，请先导出或清除本地草稿',true);}
  }
  bind('#export-local-draft','click',()=>{
    const cached=session.get(draftKey());if(!cached)return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(cached.value,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download=`${state.kind||'shared'}-${state.feature}-draft.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  bind('#discard-local-draft','click',()=>{session.remove(draftKey());draft.conflict=false;$('#draft-tools').hidden=true;write(clone(draft.saved));dirty();render();toast('已清除本地草稿，显示服务器保存值');});
  dirty();
}
export function dirty(){
  if(!draft)return;
  let value;try{value=draft.read();}catch{state.dirty[state.kind]=true;renderDirty();return;}
  const changed=!equal(value,draft.saved);
  state.dirty[state.kind]=changed;state.deviceDirty=state.feature==='devices'&&changed;state.networkDirty=state.feature==='network'&&changed;
  if(!draft.conflict){
    if(changed)draft.cached=session.set(draftKey(),{base:draft.saved,value});
    else{session.remove(draftKey());draft.cached=true;}
  }
  renderDirty();
}
export function renderDirty(){
  const changed=!!state.dirty[state.kind];
  for(const id of ['dirty','device-dirty','network-dirty'])if($('#'+id)){
    $('#'+id).textContent=draft?.conflict?'本地草稿与服务器有冲突':changed?'本页有未保存草稿':'本页已保存';
    $('#'+id).classList.toggle('dirty',changed||draft?.conflict);
  }
}
export async function saveDraft(path,encode=v=>v,decode=v=>v){
  if(draft.conflict)throw new Error('请先导出或清除冲突草稿');
  const sent=clone(draft.read()),saved=decode(await put(path,encode(sent)));
  if(equal(draft.read(),sent))draft.write(clone(saved));
  draft.saved=clone(saved);state.savedConfigs[state.kind]=clone(saved);
  if(state.feature==='devices')state.caseInitial=clone(saved);
  dirty();toast(state.dirty[state.kind]?'已保存；随后编辑的草稿仍待保存':'本页数据已保存');
  return saved;
}
export function importDraft(value){if(draft.conflict)throw new Error('请先处理冲突草稿');draft.write(clone(value));dirty();draft.render();toast('已导入本页草稿，请保存后计算');}

export async function selectPlan(){
  const kind=state.kind,explicit=new URLSearchParams(location.search).get('plan_id'),id=explicit||session.get(`selected:${kind}`);
  let plan=null;
  if(id){
    try{plan=await api(`/api/plans/id/${encodeURIComponent(id)}`);if(plan.kind!==kind)throw new Error('该版本不属于当前调度模块');}
    catch(err){if(explicit||err.status!==404)throw err;session.remove(`selected:${kind}`);}
  }
  if(!plan){const latest=await api(`/api/plan-summaries?kind=${kind}&limit=1`);if(latest.plans.length)plan=await api(`/api/plans/id/${encodeURIComponent(latest.plans[0].plan_id)}`);}
  state.plans[kind]=plan;if(plan)session.set(`selected:${kind}`,plan.plan_id);return plan;
}
async function refreshStatus(){
  if(document.hidden||state.polling)return;state.polling=true;
  try{
    const status=await api('/api/solve-status');state.solveRunning=status.running;
    const seconds=status.started_at?Math.max(0,Math.floor((Date.now()-Date.parse(status.started_at))/1000)):0;
    $('#connection').textContent=status.running?`${names[status.kind]}计算中 · ${seconds} s`:'SQLite 已连接 · 求解空闲';
    if($('#solve'))$('#solve').disabled=state.busy||status.running;
  }catch{$('#connection').textContent='服务连接中断 · 正在重试';}finally{state.polling=false;}
}
export async function boot(initialize,render=()=>{}){
  bind('#solve','click',e=>action(e.target,async()=>{
    const scopes=[`${state.kind}:optimization`,`${state.kind}:inputs`,'shared:devices','shared:network'];
    if(state.dirty[state.kind]||scopes.some(s=>session.get('draft:'+s)))throw new Error('请先保存或处理本模块及共享页面的草稿');
    toast(`${names[state.kind]}正在计算…`);
    const result=await api(`/api/${state.kind}-plan/solve`,{method:'POST',body:JSON.stringify({parent_plan_id:session.get(`parent:${state.kind}`)||null})});
    session.set(`selected:${state.kind}`,result.plan_id);
    location.assign(pageUrl(state.kind,'results')+'?plan_id='+encodeURIComponent(result.plan_id));
  }));
  bind('#app','click',e=>{const b=e.target.closest('[data-page]');if(!b)return;const [key,delta]=b.dataset.page.split(':');state.pages[key]=Math.max(0,(state.pages[key]||0)+Number(delta));return state.pageRenderer?state.pageRenderer(key):render(key);});
  window.addEventListener('beforeunload',e=>{if(state.busy||(draft&&!draft.cached&&state.dirty[state.kind])){e.preventDefault();e.returnValue='';}});
  window.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();$('#save-module,#save-case,#save-network')?.click();}});
  let timer;window.addEventListener('resize',()=>{clearTimeout(timer);timer=setTimeout(()=>Promise.resolve(state.pageRenderer?state.pageRenderer('resize'):render('resize')).catch(err=>toast(err.message,true)),180);});
  try{
    const health=await api('/api/health');$('#db-path').textContent=health.database;
    if(state.kind)state.parents[state.kind]=session.get(`parent:${state.kind}`)||'';
    await initialize();await refreshStatus();setInterval(refreshStatus,4000);
  }catch(err){toast(err.message,true);$('#connection').textContent='本页加载失败，请刷新重试';}
}
const labels={fuel_cost_multiplier:'燃油成本权重',startup_cost_multiplier:'启停成本权重',curtailment_penalty:'弃风弃光成本 (元/kWh)',reserve_penalty:'备用容量成本 (元/kWh)',lost_load_penalty:'失负荷惩罚 (元/kWh)',baseline_deviation_penalty:'基线偏差成本 (元/kWh)',storage_degradation_multiplier:'储能衰减权重'};
const presets={fast:[10,.03],balanced:[30,.01],precise:[120,.001]};
function valueField(label,attrs,value,type='number'){return '<label>'+esc(label)+'<input '+attrs+' type="'+type+'" step="any" value="'+esc(value??'')+'"></label>';}
function chart(series,unit){
  if(!series?.length||!series[0].values?.length)return '<p class="muted">暂无曲线数据</p>';
  const values=series.flatMap(s=>s.values),max=Math.max(...values,1),n=series[0].values.length;
  const points=s=>s.values.map((v,i)=>(45+i*580/Math.max(n-1,1))+','+(118-Number(v)*100/max)).join(' ');
  return '<svg viewBox="0 0 640 145" preserveAspectRatio="none" role="img" aria-label="'+esc(unit)+'曲线"><path d="M45 10V118H625" fill="none" stroke="#38506e"/><text x="0" y="15">'+fmt(max,0)+'</text><text x="18" y="118">0</text>'+series.map((s,i)=>'<polyline fill="none" stroke="'+(i?'#75aaff':'#58d5b3')+'" stroke-width="2" points="'+points(s)+'"><title>'+esc(s.name)+'</title></polyline>').join('')+'</svg>';
}
function table(headers,rows){return '<table><thead><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(v=>'<td>'+esc(v)+'</td>').join('')+'</tr>').join('')+'</tbody></table>';}
function download(name,value){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function readFile(event){const file=event.target.files?.[0];if(!file)return null;if(file.size>8*1024*1024)throw new Error('JSON 文件不能超过 8 MB');const value=JSON.parse(await file.text());event.target.value='';return value;}
function wireOptimization(){
  const config=state.configs[state.kind],render=()=>{
    $('#solver-select').innerHTML=Object.entries(state.solvers).map(([key,v])=>'<option value="'+key+'">'+key.toUpperCase()+' · '+(v.available?'可用':'未安装')+'</option>').join('');
    $('#solver-select').value=config.solver;$('#time-limit').value=config.time_limit_seconds;$('#mip-gap').value=config.mip_gap;
    $('#solver-info').textContent=names[state.kind]+'独立求解配置 · 优先 CPLEX，切换求解器后保存。';
    const entries=Object.entries(labels),range=page('opt',entries.length);$('#optimization-form').innerHTML=entries.slice(range[0],range[1]).map(([k,l])=>valueField(l,'data-opt="'+k+'" min="0"',config.optimization[k])).join('');
  };
  bind('#solver-select','change',e=>{config.solver=e.target.value;dirty();});
  for(const item of [['time-limit','time_limit_seconds'],['mip-gap','mip_gap']])bind('#'+item[0],'input',e=>{config[item[1]]=Number(e.target.value);dirty();});
  bind('#optimization-form','input',e=>{if(e.target.dataset.opt){config.optimization[e.target.dataset.opt]=Number(e.target.value);dirty();}});
  bind('#optimization','click',e=>{const b=e.target.closest('[data-opt-preset]');if(b){config.time_limit_seconds=presets[b.dataset.optPreset][0];config.mip_gap=presets[b.dataset.optPreset][1];dirty();render();toast('快捷求解参数已写入本页草稿');}});
  bind('#save-module','click',e=>action(e.target,()=>saveDraft('/api/modules/'+state.kind+'/optimization',{optimization:config.optimization,solver:config.solver,time_limit_seconds:config.time_limit_seconds,mip_gap:config.mip_gap})));
  bind('#export-module','click',()=>download(state.kind+'-optimization.json',{optimization:config.optimization,solver:config.solver,time_limit_seconds:config.time_limit_seconds,mip_gap:config.mip_gap}));
  bind('#import-module','change',async e=>{const v=await readFile(e);if(!v?.optimization)throw new Error('配置缺少 optimization');Object.assign(config,v);dirty();render();});
  configureDraft(config,()=>config,v=>Object.assign(config,v),render);state.pageRenderer=key=>{if(key==='opt'||key==='resize')render();};render();
}
function wireInputs(){
  const config=state.configs[state.kind],render=()=>{
    const key=$('#curve-kind').value,values=config.forecast[key],range=page('curve',values.length);
    $('#input-curve-form').innerHTML=values.slice(range[0],range[1]).map((v,i)=>valueField('第 '+(range[0]+i+1)+' 时段 · +'+((range[0]+i)*config.input_interval_minutes)+' min','data-curve="'+(range[0]+i)+'" min="0"',v)).join('');
    $('#input-chart').innerHTML=chart([{name:$('#curve-kind').selectedOptions[0].textContent,values:values}],'kW');$('#curve-jump').max=values.length;$('#curve-jump').value=range[0]+1;$('#curve-from').max=values.length;$('#curve-to').max=values.length;if(!$('#curve-to').value)$('#curve-to').value=values.length;
    for(const n of ['edit','batch','template','settings'])$('#input-'+n).hidden=$('#input-mode').value!==n;
    $('#reserve-fraction').value=config.forecast.reserve_fraction;const start=config.start_time?new Date(config.start_time):null;$('#start-time').value=start?new Date(start.getTime()-start.getTimezoneOffset()*60000).toISOString().slice(0,16):'';
  };
  bind('#curve-kind','change',()=>{state.pages.curve=0;render();});bind('#input-mode','change',render);
  bind('#input-curve-form','input',e=>{if(e.target.dataset.curve!=null){config.forecast[$('#curve-kind').value][Number(e.target.dataset.curve)]=Number(e.target.value);dirty();render();}});
  bind('#curve-jump','change',e=>{state.pages.curve=Math.floor((Number(e.target.value)-1)/size());render();});
  bind('#reserve-fraction','input',e=>{config.forecast.reserve_fraction=Number(e.target.value);dirty();});bind('#start-time','change',e=>{config.start_time=e.target.value?new Date(e.target.value).toISOString():null;dirty();});
  bind('#inputs','click',e=>{const b=e.target.closest('[data-curve-action]');if(!b)return;const key=$('#curve-kind').value;if(b.dataset.curveAction==='apply'){config.forecast[key]=ScheduleData.transformCurve(config.forecast[key],Number($('#curve-from').value),Number($('#curve-to').value),Number($('#curve-scale').value),Number($('#curve-offset').value));dirty();render();toast('批量曲线已写入本页草稿');}else if(b.dataset.curveAction==='template'){const p=state.configs[{daily:'weekly',hourly:'daily'}[state.kind]];config.forecast[key]=ScheduleData.curveTemplate(config.forecast[key],$('#curve-template').value,Number($('#template-scale').value||1),p?{values:p.forecast[key],interval:p.input_interval_minutes,start_time:p.start_time}:null,{interval:config.input_interval_minutes,start_time:config.start_time});dirty();render();toast('曲线模板已应用');}else if(b.dataset.curveAction==='restore'){config.forecast[key]=clone(state.savedConfigs[state.kind].forecast[key]);dirty();render();toast('已恢复保存曲线');}});
  bind('#save-module','click',e=>action(e.target,()=>saveDraft('/api/modules/'+state.kind+'/inputs',{input_interval_minutes:config.input_interval_minutes,forecast:config.forecast,start_time:config.start_time})));
  bind('#export-module','click',()=>download(state.kind+'-inputs.json',{input_interval_minutes:config.input_interval_minutes,forecast:config.forecast,start_time:config.start_time}));
  bind('#import-module','change',async e=>{const v=await readFile(e);if(!v?.forecast)throw new Error('输入文件缺少 forecast');Object.assign(config,v);dirty();render();});
  configureDraft(config,()=>config,v=>Object.assign(config,v),render);state.pageRenderer=key=>{if(key==='curve'||key==='resize')render();};render();
}
function downloadText(name,text,mime='text/plain'){
  const url=URL.createObjectURL(new Blob([text],{type:mime})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
const actionNames={weekly_solved:'周前计算',daily_solved:'日前计算',hourly_solved:'小时前计算',module_config_updated:'参数保存',shared_devices_updated:'设备参数保存',network_model_updated:'电网模型保存',validate:'校核',plan_validated:'校核',publish:'发布',rollback:'回退',execute:'模拟执行',solve_failed:'求解失败'};
function resultResources(plan){return window.ScheduleData?.resources(plan)||[['system','全站']];}
function resultView(plan,resource,curve){return window.ScheduleData?.resultView(plan,resource,curve)||{headers:['时段'],rows:[],series:[],unit:'kW'};}
function resultStatistics(plan,group){return window.ScheduleData?.statistics(plan,group)||[];}
async function wireResults(){
  const kind=state.kind;let active=await selectPlan(),history=[],historyMeta={};
  const render=()=>{
    for(const n of ['chart','dispatch','statistics','comparison','history'])$('#'+n+'-result').hidden=state.resultTab!==n;
    $$('[data-result]').forEach(b=>b.classList.toggle('active',b.dataset.result===state.resultTab));
    $('#selected-plan').textContent=active?`${active.plan_id} · ${new Date(active.created_at).toLocaleString()}`:'本模块尚无结果，请先计算或从版本管理选择计划';
    $('#result-summary').innerHTML=active?[['状态',({solved:'已求解',feasible:'可行解',not_solved:'无可用解'})[active.status]||active.status],['目标值',fmt(active.solver_report.objective)],['柴油总量',`${fmt(active.fuel_summary.total_liters)} L`],['求解耗时',`${fmt(active.solver_report.elapsed_seconds)} s`]].map(x=>`<div class="metric"><small>${esc(x[0])}</small><strong>${esc(x[1])}</strong></div>`).join(''):'<p class="notice">本模块尚无结果。</p>';
    const options=resultResources(active),selected=$('#result-resource').value;
    $('#result-resource').innerHTML=options.map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join('');
    if(options.some(([key])=>key===selected))$('#result-resource').value=selected;
    const resource=$('#result-resource').value||'system',type=resource.split(':')[0],oldCurve=$('#result-curve').value;
    const curves=type==='system'?[['fuel','柴油消耗 (L/时段)'],['cumulative','累计柴油 (L)'],['power','负荷与柴油出力'],['renewable','风光消纳与弃电']]:type==='g'?[['power','机组出力'],['fuel','机组油耗']]:type==='b'?[['soc','储能电量 / SOC'],['power','充放电功率']]:[['power','功率']];
    $('#result-curve').innerHTML=curves.map(([value,label])=>`<option value="${value}">${label}</option>`).join('');
    if(curves.some(([key])=>key===oldCurve))$('#result-curve').value=oldCurve;
    const view=active?resultView(active,resource,$('#result-curve').value):{headers:['时段'],rows:[],series:[],unit:'kW'};
    $('#resource-label').hidden=!['chart','dispatch'].includes(state.resultTab);
    $('#result-chart').innerHTML=chart(view.series,view.unit);
    const gen=resource.startsWith('g:')?resource.slice(2):null;
    $('#generator-fuel').textContent=active?`柴油消耗量统计：${gen?gen+' '+fmt(active.fuel_summary.by_generator_liters[gen]):'全站 '+fmt(active.fuel_summary.total_liters)} L · ${active.solver_report.solver.toUpperCase()} · Gap ${fmt(active.solver_report.mip_gap,4)}`:'';
    $('#result-extra').hidden=active?.status!=='not_solved';$('#result-extra').textContent=active?.status==='not_solved'?`没有可用解：${active.solver_report.termination}。请检查备用、容量和初始状态。`:'';
    const statRows=active?resultStatistics(active,$('#statistics-group').value).map(([label,value,unit])=>[label,fmt(value,unit==='个'?0:3),unit]):[];
    const statCount=Math.max(1,Math.min(rowCount(),Math.floor(($('#statistics-result').clientHeight||180-110)/32))),[sa,sb]=page('stats',statRows.length,statCount);
    $('#statistics-table').innerHTML=active?table(['指标','数值','单位'],statRows.slice(sa,sb)):'<p class="notice">本模块暂无统计结果。</p>';
    const [a,b]=page('dispatch',view.rows.length,rowCount());$('#dispatch-table').innerHTML=table(view.headers,view.rows.slice(a,b).map(r=>r.map((v,i)=>i?fmt(v):v)));
    const comparison=state.comparisons[kind],match=!!comparison&&!!active&&comparison.right.plan_id===active.plan_id;
    $('#compare-note').textContent=match?`当前 ${comparison.right.plan_id}；上一版 ${comparison.left.plan_id}。差值 = 当前 − 上一版。${comparison.same_start_time?'':'两版起点不同；'}输入、设备、求解器可能不同，差值仅供方案分析。`:'点击“比较当前/上一版”加载同模块的相邻历史版本。';
    $('#compare-table').innerHTML=match?table(['指标','上一版','当前','差值'],[['目标值','objective'],['柴油 L','total_liters'],['耗时 s','elapsed_seconds']].map(([label,key])=>[label,fmt(comparison.left[key]),fmt(comparison.right[key]),fmt(comparison.delta_right_minus_left[key])])):'';
    const total=historyMeta.total??history.length,pages=Math.max(1,Math.ceil(total/6));$('#history-page').textContent=`版本页 ${state.pages.history+1} / ${pages} · ${total} 项`;$("[data-page='history:-1']").disabled=state.pages.history===0;$("[data-page='history:1']").disabled=!historyMeta.has_more;
  };
  const loadHistory=async(refresh=false)=>{
    const request=++state.historyRequest,offset=state.pages.history*6,q=new URLSearchParams({kind,limit:'6',offset:String(offset)});if(state.historyStatus)q.set('status',state.historyStatus);
    const response=await api(`/api/plan-summaries?${q}`);if(request!==state.historyRequest)return;
    history=response.plans;historyMeta=response;const pages=Math.max(1,Math.ceil((response.total||0)/6));
    if(state.pages.history>=pages){state.pages.history=pages-1;return loadHistory(refresh);}
    const current=active?.plan_id;$('#history-status').value=state.historyStatus;$('#plan-select').innerHTML=history.map(p=>`<option value="${esc(p.plan_id)}">${esc(p.plan_id)} · ${esc(new Date(p.created_at).toLocaleString())}</option>`).join('')||'<option value="">暂无结果</option>';
    const id=history.some(p=>p.plan_id===current)?current:history[0]?.plan_id||'';if(id)$('#plan-select').value=id;
    if(id&&(refresh||!active||active.plan_id!==id))active=await api(`/api/plans/id/${encodeURIComponent(id)}`);else if(!id)active=null;
    state.plans[kind]=active;if(active)session.set(`selected:${kind}`,active.plan_id);render();
  };
  const compareCurrent=async()=>{
    if(!active)throw new Error('本模块暂无结果');
    const response=await api(`/api/plan-summaries?kind=${kind}&limit=200${state.historyStatus?`&status=${encodeURIComponent(state.historyStatus)}`:''}`),rows=response.plans,index=rows.findIndex(p=>p.plan_id===active.plan_id),previous=rows[index+1];
    if(index<0||!previous)throw new Error('当前版本没有可比较的上一版');
    state.comparisons[kind]=await api(`/api/plans/${kind}/compare?left_id=${encodeURIComponent(previous.plan_id)}&right_id=${encodeURIComponent(active.plan_id)}`);state.resultTab='comparison';render();
  };
  bind('#result-tabs','click',e=>{const b=e.target.closest('[data-result]');if(b){state.resultTab=b.dataset.result;render();}});bind('#result-resource','change',()=>{state.pages.dispatch=0;render();});bind('#result-curve','change',render);bind('#statistics-group','change',()=>{state.pages.stats=0;render();});bind('#plan-select','change',async e=>{if(!e.target.value)return;active=await api(`/api/plans/id/${encodeURIComponent(e.target.value)}`);state.plans[kind]=active;session.set(`selected:${kind}`,active.plan_id);render();});bind('#history-status','change',e=>{state.historyStatus=e.target.value;state.pages.history=0;loadHistory(true).catch(err=>toast(err.message,true));});bind('#reload-results','click',e=>action(e.target,()=>loadHistory(true)));bind('#compare-result','click',e=>action(e.target,compareCurrent));bind('#export-result','click',()=>{if(!active)throw new Error('本模块暂无结果');download(`${active.plan_id}.json`,active);});bind('#export-csv','click',()=>{if(!active?.dispatch?.length)throw new Error('本模块暂无结果');const rows=[['step','timestamp','demand_kw','diesel_kw','grid_import_kw','grid_export_kw','fuel_liters','lost_load_kw']];active.dispatch.forEach((r,i)=>rows.push([r.step+1,r.timestamp||'',r.demand_kw,Object.values(r.generators||{}).reduce((sum,g)=>sum+(g.power_kw||0),0),r.grid_import_kw,r.grid_export_kw,active.fuel_summary.interval_liters[i]||0,r.lost_load_kw]));downloadText(`${active.plan_id}.csv`,rows.map(row=>row.map(v=>`"${String(v??'').replaceAll('"','""')}"`).join(',')).join('\r\n'),'text/csv;charset=utf-8');});
  state.pageRenderer=async key=>{if(key==='history')await loadHistory();else if(key==='resize'||key==='dispatch'||key==='stats'||key==='auditDetail')render();};
  await loadHistory();
}
async function wireControl(){
  const kind=state.kind;let plan=await selectPlan();
  const renderAuditDetail=()=>{const event=state.auditDetail,text=event?`${actionNames[event.action]||event.action} · ${new Date(event.created_at).toLocaleString()}\n计划：${event.plan_id||'配置'}\n${event.detail}`:'尚未选择审计记录',el=$('#audit-detail-text');if(!el)return;const width=Math.max(16,Math.floor((el.clientWidth||500)/7.5)-1),lines=Math.max(1,Math.floor((el.clientHeight||200)/20)-1),chunks=[];let start=0,column=0,line=1;for(let i=0;i<text.length;i++){column+=text.charCodeAt(i)>255?2:1;if(text[i]==='\n'||column>=width){line++;column=0;}if(line>lines){chunks.push(text.slice(start,i+1));start=i+1;line=1;}}chunks.push(text.slice(start));const [a]=page('auditDetail',chunks.length,1);el.textContent=chunks[a]||'';};
  const render=()=>{
    const control=state.controls[kind]||{},validation=state.validations[kind];$('#control-summary').textContent=`操作计划：${plan?.plan_id||'无'}；已发布：${control.last_published_plan_id||'无'}；已模拟执行：${control.last_executed_plan_id||'无'}。在输出结果中选择版本。`;$('#execute').hidden=kind!=='hourly';$('#parent-select').disabled=kind==='weekly';$('#parent-note').textContent=kind==='weekly'?'周前计划生成基线':'设置起点后按时间对齐基线；均留空时按相对起点对齐。';$('#control-operations').hidden=state.controlTab!=='operations';$('#control-list').hidden=!['audit','validation'].includes(state.controlTab);$('#audit-detail-view').hidden=state.controlTab!=='detail';$('#control-pager').hidden=!['audit','validation'].includes(state.controlTab);$('#audit-filter').hidden=state.controlTab!=='audit';$$('[data-control-tab]').forEach(b=>b.classList.toggle('active',b.dataset.controlTab===state.controlTab));
    if(state.controlTab==='detail'){renderAuditDetail();return;}
    if(state.controlTab==='validation'){const rows=validation?.issues||[],[a,b]=page('control',rows.length,rowCount());$('#control-list').innerHTML=validation?`<p class="notice">${esc(validation.plan_id)}：${validation.valid?'校核通过':'校核未通过'} · 最大功率偏差 ${fmt(validation.metrics.max_power_balance_error_kw,4)} kW</p><table><thead><tr><th>时段</th><th>校核信息</th></tr></thead><tbody>${rows.slice(a,b).map(r=>`<tr><td>${r.step==null?'全部':r.step+1}</td><td>${esc(r.message)}</td></tr>`).join('')}</tbody></table>`:'<p class="notice">点击校核，检查本模块选中计划的输入快照与出力。</p>';return;}
    const rows=state.audit[kind]||[],meta=state.auditMeta[kind]||{},[a,b]=page('control',meta.total??rows.length,auditRowCount());$('#control-list').innerHTML=rows.length?`<table><thead><tr><th>操作 / 版本</th><th>详情</th><th>时间</th></tr></thead><tbody>${rows.map((r,i)=>`<tr><td>${esc(actionNames[r.action]||r.action)}<small class="audit-version" title="${esc(r.plan_id||'配置')}">${esc(r.plan_id||'配置')}</small></td><td><button data-audit-detail="${i}">查看详情</button></td><td>${esc(new Date(r.created_at).toLocaleString())}</td></tr>`).join('')}</tbody></table>`:'<p class="notice">当前筛选条件下暂无审计记录。</p>';
  };
  const load=async()=>{const request=++state.controlRequest,limit=auditRowCount(),q=new URLSearchParams({limit:String(limit),offset:String(state.pages.control*limit)});if(state.auditAction)q.set('action',state.auditAction);if(state.auditQuery)q.set('query',state.auditQuery);const parent={daily:'weekly',hourly:'daily'}[kind];const [control,audit,parents]=await Promise.all([api(`/api/modules/${kind}/control`),api(`/api/modules/${kind}/audit?${q}`),parent?api(`/api/plan-summaries?kind=${parent}&limit=30`):Promise.resolve({plans:[]})]);if(request!==state.controlRequest)return;state.controls[kind]=control;state.audit[kind]=audit.events;state.auditMeta[kind]=audit;plan=await selectPlan();if((audit.total||0)>0&&state.pages.control>0&&state.pages.control*limit>audit.total){state.pages.control--;return load();}$('#parent-select').innerHTML='<option value="">不指定</option>'+parents.plans.filter(r=>['solved','feasible'].includes(r.status)).map(r=>`<option value="${esc(r.plan_id)}">${esc(r.plan_id)}</option>`).join('');$('#parent-select').value=state.parents[kind]||'';$('#audit-action').value=state.auditAction;$('#audit-query').value=state.auditQuery;render();};
  bind('#control-tabs','click',e=>{const b=e.target.closest('[data-control-tab]');if(b){state.controlTab=b.dataset.controlTab;state.pages.control=0;load().catch(err=>toast(err.message,true));}});bind('#parent-select','change',e=>{state.parents[kind]=e.target.value;session.set(`parent:${kind}`,e.target.value||null);});bind('#audit-action','change',e=>{state.auditAction=e.target.value;state.pages.control=0;load().catch(err=>toast(err.message,true));});bind('#audit-query','change',e=>{state.auditQuery=e.target.value.trim();state.pages.control=0;load().catch(err=>toast(err.message,true));});bind('#audit-query','keydown',e=>{if(e.key==='Enter'){e.preventDefault();state.auditQuery=e.target.value.trim();state.pages.control=0;load().catch(err=>toast(err.message,true));}});bind('#control-list','click',e=>{const b=e.target.closest('[data-audit-detail]');if(b){state.auditDetail=(state.audit[kind]||[])[Number(b.dataset.auditDetail)];state.pages.auditDetail=0;state.controlTab='detail';render();}});bind('#audit-detail-back','click',()=>{state.controlTab='audit';render();});bind('#export-audit','click',async e=>action(e.target,async()=>{const q=new URLSearchParams();if(state.auditAction)q.set('action',state.auditAction);if(state.auditQuery)q.set('query',state.auditQuery);const response=await fetch(`/api/modules/${kind}/audit/export?${q}`);if(!response.ok)throw new Error('审计导出失败，请稍后重试');const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${kind}-audit.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('已导出当前筛选条件下的全部审计记录');}));bind('#control','click',e=>{const b=e.target.closest('[data-control]');if(!b)return;action(b,async()=>{const selected=plan?.plan_id,requested=b.dataset.control;if(!selected&&requested!=='rollback')throw new Error('请先在本模块输出结果中选择计划');const result=await api(`/api/modules/${kind}/control/${requested}${selected?`?plan_id=${encodeURIComponent(selected)}`:''}`,{method:'POST'});if(result.validation)state.validations[kind]=result.validation;state.pages.control=0;state.controlTab=result.validation?'validation':'audit';await load();toast(result.validation?(result.validation.valid?'计划校核通过；本模块操作已完成':`校核发现 ${result.validation.issues.length} 个问题`):'本模块操作已完成',result.validation&&!result.validation.valid);}).catch(err=>toast(err.message,true));});
  state.pageRenderer=async key=>{if(key==='control')await load();else if(key==='auditDetail'||key==='resize')render();};
  await load();
}
const fieldLabels={id:'设备编号',name:'名称',fuel_type:'燃料类型',kind:'能源类型',min_power_kw:'最小功率 (kW)',max_power_kw:'最大功率 (kW)',ramp_up_kw_per_step:'升出力限制 (kW/步)',ramp_down_kw_per_step:'降出力限制 (kW/步)',min_up_steps:'最小开机时长 (步)',min_down_steps:'最小停机时长 (步)',startup_cost:'启动成本 (元)',shutdown_cost:'停机成本 (元)',fuel_price_per_liter:'柴油价格 (元/L)',initial_on:'初始开机',initial_power_kw:'初始出力 (kW)',initial_up_steps:'初始已开机 (步)',initial_down_steps:'初始已停机 (步)',capacity_kw:'额定功率 (kW)',capacity_kwh:'容量 (kWh)',max_charge_kw:'充电上限 (kW)',max_discharge_kw:'放电上限 (kW)',charge_efficiency:'充电效率',discharge_efficiency:'放电效率',min_soc:'SOC 下限',max_soc:'SOC 上限',initial_soc:'初始 SOC',terminal_soc:'目标 SOC (留空不约束)',degradation_cost_per_kwh:'衰减成本 (元/kWh)',min_kw:'最小功率 (kW)',max_kw:'最大功率 (kW)',shiftable_energy_kwh:'每日可调能量 (kWh)',adjustment_cost_per_kwh:'调整成本 (元/kWh)',import_limit_kw:'进口上限 (kW)',export_limit_kw:'出口上限 (kW)',import_price_per_kwh:'购电价格 (元/kWh)',export_price_per_kwh:'售电价格 (元/kWh)',fuel_price_per_liter:'柴油价格 (元/L)'};
function deviceSnapshot(data){return Object.fromEntries(['generators','renewables','batteries','flexible_loads','grid','fuel_price_per_liter'].map(k=>[k,clone(data[k])]));}
async function wireDevices(){
  const data=await api('/api/shared/devices');state.case=data;state.caseInitial=clone(data);
  const entries=()=>['generators','renewables','batteries','flexible_loads'].flatMap(key=>state.case[key].map((item,index)=>({key,index,item}))).concat([{key:'grid',item:state.case.grid}]);
  const render=()=>{const list=entries();if(!list.length)return;state.deviceIndex=Math.min(state.deviceIndex,list.length-1);$('#device-select').innerHTML=list.map((e,i)=>`<option value="${i}">${esc(e.item.name||'联络线')} · ${esc(e.item.id||'grid')}</option>`).join('');$('#device-select').value=state.deviceIndex;const item=list[state.deviceIndex].item,fields=Object.keys(item).filter(k=>!['id','kind','fuel_type','fuel_curve'].includes(k)).map(k=>({key:k,label:fieldLabels[k]||k,value:item[k]}));item.fuel_curve?.forEach((p,i)=>fields.push({curve:i,key:'power_kw',label:`油耗点 ${i+1} · 出力 kW`,value:p.power_kw},{curve:i,key:'liters_per_hour',label:`油耗点 ${i+1} · 油耗 L/h`,value:p.liters_per_hour}));const [a,b]=page('device',fields.length);$('#device-form').innerHTML=fields.slice(a,b).map(f=>typeof f.value==='boolean'?`<label>${esc(f.label)}<select data-device-field="${f.key}"><option value="true" ${f.value?'selected':''}>开启</option><option value="false" ${!f.value?'selected':''}>关闭</option></select></label>`:valueField(f.label,`data-device-field="${f.key}" ${f.curve==null?'':`data-fuel-point="${f.curve}"`}`,f.value,typeof f.value==='string'?'text':'number')).join('');renderDirty();};
  const update=e=>{const key=e.target.dataset.deviceField;if(!key)return;const entry=entries()[state.deviceIndex],item=entry.item,point=e.target.dataset.fuelPoint;let value=typeof item[key]==='boolean'?e.target.value==='true':e.target.type==='text'?e.target.value:e.target.value===''?null:Number(e.target.value);if(point!=null)item.fuel_curve[Number(point)][key]=value;else item[key]=value;dirty();};
  bind('#device-select','change',e=>{state.deviceIndex=Number(e.target.value);state.pages.device=0;render();});bind('#device-form','input',update);bind('#device-form','change',update);bind('#restore-device','click',()=>{const e=entries()[state.deviceIndex],original=e.key==='grid'?state.caseInitial.grid:state.caseInitial[e.key]?.find(v=>v.id===e.item.id);if(!original)throw new Error('当前设备没有可恢复的加载值');if(e.key==='grid')state.case.grid=clone(original);else state.case[e.key][e.index]=clone(original);render();dirty();toast('已恢复当前设备的加载值，保存后生效');});bind('#copy-device','click',async()=>{const e=entries()[state.deviceIndex];if(!e)return;try{await navigator.clipboard.writeText(JSON.stringify(e.item,null,2));toast(`已复制 ${e.item.name||e.item.id||'设备'} 参数`);}catch{downloadText(`${e.item.id||'device'}.json`,JSON.stringify(e.item,null,2),'application/json');toast('剪贴板不可用，已下载所选设备参数');}});bind('#save-case','click',e=>action(e.target,()=>saveDraft('/api/shared/devices')));bind('#export-device','click',()=>download('shared-devices.json',deviceSnapshot(state.case)));bind('#import-device','change',async e=>{const imported=await readFile(e);if(!imported)return;if(!Array.isArray(imported.generators)||!imported.generators.length||!imported.grid)throw new Error('缺少柴油机或联络线参数');for(const key of ['generators','renewables','batteries','flexible_loads','grid','fuel_price_per_liter'])if(key in imported)state.case[key]=clone(imported[key]);state.deviceIndex=0;state.pages.device=0;dirty();render();toast('共享设备已载入草稿，请校验并保存');});configureDraft(state.case,()=>deviceSnapshot(state.case),v=>Object.assign(state.case,v),render);state.pageRenderer=key=>{if(key==='device'||key==='resize')render();};render();
}
function splitNetwork(){const textarea=$('#network-json'),text=state.networkText,width=Math.max(16,Math.floor((textarea?.clientWidth||500)/8)-3),maxLines=Math.max(3,Math.floor((textarea?.clientHeight||240)/20)-1),chunks=[];let start=0,lines=1,column=0;for(let i=0;i<text.length;i++){column+=text.charCodeAt(i)>255?2:1;if(text[i]==='\n'||column>=width){lines++;column=0;}if(lines>=maxLines){chunks.push(text.slice(start,i+1));start=i+1;lines=1;}}chunks.push(text.slice(start));state.networkChunks=chunks;}
async function wireNetwork(){
  const model=await api('/api/network-model');state.networkText=JSON.stringify(model,null,2);
  const render=()=>{splitNetwork();const [a]=page('network',state.networkChunks.length,1);$('#network-json').value=state.networkChunks[a]||'';try{const m=JSON.parse(state.networkText);$('#network-summary').textContent=`${m.name} · ${m.base_mva} MVA · ${m.buses?.length||0} 母线 / ${m.lines?.length||0} 线路`;}catch{$('#network-summary').textContent='JSON 编辑草稿：保存时校验完整模型';}renderDirty();};
  bind('#network-json','input',e=>{state.networkChunks[state.pages.network]=e.target.value;state.networkText=state.networkChunks.join('');dirty();});bind('#network-file','change',async e=>{const imported=await readFile(e);if(!imported)return;state.networkText=JSON.stringify(imported,null,2);state.pages.network=0;dirty();render();toast('模型已加载为共享草稿，请保存');});bind('#save-network','click',e=>action(e.target,()=>saveDraft('/api/network-model')));bind('#export-network','click',()=>{const model=JSON.parse(state.networkText);download('shared-network.json',model);});configureDraft(model,()=>JSON.parse(state.networkText),v=>{state.networkText=JSON.stringify(v,null,2);state.pages.network=0;},render);state.pageRenderer=key=>{if(key==='network'||key==='resize')render();};render();
}
export async function initFeature(feature){
  if(feature==='home'){await boot(async()=>toast('请选择功能进入独立页面'));return;}
  if(feature==='optimization'){await boot(async()=>{const data=await Promise.all([api('/api/solver'),api('/api/modules/'+state.kind+'/optimization')]);state.solvers=data[0];state.configs[state.kind]=data[1];state.savedConfigs[state.kind]=clone(data[1]);wireOptimization();});return;}
  if(feature==='inputs'){await boot(async()=>{const data=await api('/api/modules/'+state.kind+'/inputs');state.configs[state.kind]=data;state.savedConfigs[state.kind]=clone(data);const parent={daily:'weekly',hourly:'daily'}[state.kind];if(parent)state.configs[parent]=await api('/api/modules/'+parent+'/inputs');wireInputs();});return;}
  if(feature==='results'){await boot(async()=>wireResults());return;}
  if(feature==='control'){await boot(async()=>wireControl());return;}
  if(feature==='devices'){await boot(async()=>wireDevices());return;}
  if(feature==='network'){await boot(async()=>wireNetwork());return;}
}

