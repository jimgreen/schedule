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
  resultTab:'chart',controlTab:'operations',busy:false,solveRunning:false,
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
  bind('#app','click',e=>{const b=e.target.closest('[data-page]');if(!b)return;const [key,delta]=b.dataset.page.split(':');state.pages[key]=Math.max(0,(state.pages[key]||0)+Number(delta));return render(key);});
  window.addEventListener('beforeunload',e=>{if(state.busy||(draft&&!draft.cached&&state.dirty[state.kind])){e.preventDefault();e.returnValue='';}});
  window.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();$('#save-module,#save-case,#save-network')?.click();}});
  let timer;window.addEventListener('resize',()=>{clearTimeout(timer);timer=setTimeout(()=>Promise.resolve(render('resize')).catch(err=>toast(err.message,true)),180);});
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
  configureDraft(config,()=>config,v=>Object.assign(config,v),render);render();
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
  configureDraft(config,()=>config,v=>Object.assign(config,v),render);render();
}
function compactResult(plan){
  if(!plan)return {headers:['时段'],rows:[],series:[],unit:'kW'};
  const resource=$('#result-resource').value||'system',curve=$('#result-curve').value||'fuel',rows=plan.dispatch,dt=plan.interval_minutes/60;
  const sum=(items,key)=>Object.values(items||{}).reduce((s,v)=>s+(key?(v[key]||0):(v||0)),0),parts=resource.split(':'),type=parts[0],id=parts[1];let headers,cells,series,unit='kW';
  if(type==='g'){headers=['出力 kW','开机','油耗 L/h','时段油耗 L'];cells=r=>{const g=r.generators[id];return[g.power_kw,g.on,g.fuel_lph,g.fuel_lph*dt];};series=[{name:curve==='fuel'?'时段油耗':'柴油出力',values:rows.map(r=>curve==='fuel'?r.generators[id].fuel_lph*dt:r.generators[id].power_kw)}];unit=curve==='fuel'?'L':'kW';}
  else if(type==='b'){headers=['充电 kW','放电 kW','储能 kWh'];cells=r=>{const b=r.batteries[id];return[b.charge_kw,b.discharge_kw,b.soc_kwh];};series=[{name:'储能电量',values:rows.map(r=>r.batteries[id].soc_kwh)}];unit='kWh';}
  else if(type==='grid'){headers=['购电 kW','售电 kW','净购电 kW'];cells=r=>[r.grid_import_kw,r.grid_export_kw,r.grid_import_kw-r.grid_export_kw];series=[{name:'购电',values:rows.map(r=>r.grid_import_kw)},{name:'售电',values:rows.map(r=>r.grid_export_kw)}];}
  else {headers=['负荷 kW','柴油 kW','风光 kW','弃电 kW'];cells=r=>[r.demand_kw,sum(r.generators,'power_kw'),sum(r.renewables),r.renewable_curtailment_kw];series=curve==='fuel'?[{name:'时段油耗',values:plan.fuel_summary.interval_liters}]:curve==='cumulative'?[{name:'累计油耗',values:plan.fuel_summary.cumulative_liters}]:[{name:'基础负荷',values:rows.map(r=>r.demand_kw)},{name:'柴油出力',values:rows.map(r=>sum(r.generators,'power_kw'))}];if(curve==='fuel'||curve==='cumulative')unit='L';}
  return {headers:['时段',...headers],rows:rows.map(r=>[r.step+1,...cells(r)]),series,unit};
}
async function wireResults(){
  const plan=await selectPlan();let active=plan,history=[];
  const render=()=>{for(const n of ['chart','dispatch','statistics','comparison','history'])$('#'+n+'-result').hidden=state.resultTab!==n;$$('[data-result]').forEach(b=>b.classList.toggle('active',b.dataset.result===state.resultTab));if(!active)return;$('#selected-plan').textContent=active.plan_id+' · '+new Date(active.created_at).toLocaleString();$('#result-summary').innerHTML=[['状态',({solved:'已求解',feasible:'可行解'})[active.status]||active.status],['目标值',fmt(active.solver_report.objective)],['柴油总量',fmt(active.fuel_summary.total_liters)+' L'],['求解耗时',fmt(active.solver_report.elapsed_seconds)+' s']].map(x=>'<div class="metric"><small>'+x[0]+'</small><strong>'+x[1]+'</strong></div>').join('');const options=ScheduleData.resources(active);$('#result-resource').innerHTML=options.map(x=>'<option value="'+x[0]+'">'+x[1]+'</option>').join('');const view=compactResult(active);$('#result-curve').innerHTML=[['fuel','柴油消耗 (L/时段)'],['cumulative','累计柴油 (L)'],['power','负荷与柴油出力']].map(x=>'<option value="'+x[0]+'">'+x[1]+'</option>').join('');const final=compactResult(active);$('#result-chart').innerHTML=chart(final.series,final.unit);$('#generator-fuel').textContent='柴油消耗量统计：全站 '+fmt(active.fuel_summary.total_liters)+' L · '+active.solver_report.solver.toUpperCase();const range=page('dispatch',view.rows.length,rowCount());$('#dispatch-table').innerHTML=table(view.headers,view.rows.slice(range[0],range[1]).map(r=>r.map((v,i)=>i?fmt(v):v)));};
  bind('#result-tabs','click',e=>{const b=e.target.closest('[data-result]');if(b){state.resultTab=b.dataset.result;render();}});bind('#result-resource','change',render);bind('#result-curve','change',render);bind('#reload-results','click',()=>location.reload());bind('#export-result','click',()=>download(active.plan_id+'.json',active));
  if(active){const response=await api('/api/plan-summaries?kind='+state.kind+'&limit=50');history=response.plans;$('#plan-select').innerHTML=history.map(p=>'<option value="'+p.plan_id+'">'+p.plan_id+' · '+new Date(p.created_at).toLocaleString()+'</option>').join('');$('#plan-select').value=active.plan_id;bind('#plan-select','change',async e=>{active=await api('/api/plans/id/'+encodeURIComponent(e.target.value));render();});}
  render();
}
async function wireControl(){
  const kind=state.kind,control=await api('/api/modules/'+kind+'/control'),audit=await api('/api/modules/'+kind+'/audit?limit='+auditRowCount()),plan=await selectPlan();state.controls[kind]=control;state.audit[kind]=audit.events;
  $('#control-summary').textContent='操作计划：'+(plan?.plan_id||'无')+'；已发布：'+(control.last_published_plan_id||'无')+'；已模拟执行：'+(control.last_executed_plan_id||'无');
  const render=()=>{const rows=state.audit[kind]||[];$('#control-list').innerHTML=rows.length?'<table><thead><tr><th>操作 / 版本</th><th>详情</th><th>时间</th></tr></thead><tbody>'+rows.map(r=>'<tr><td>'+esc(r.action)+'<small>'+esc(r.plan_id||'配置')+'</small></td><td>'+esc(r.detail)+'</td><td>'+new Date(r.created_at).toLocaleString()+'</td></tr>').join('')+'</tbody></table>':'<p class="notice">暂无审计记录</p>';};
  bind('#control-tabs','click',e=>{const b=e.target.closest('[data-control-tab]');if(b){state.controlTab=b.dataset.controlTab;$('#control-operations').hidden=state.controlTab!=='operations';$('#control-list').hidden=state.controlTab!=='audit';}});
  bind('#control','click',async e=>{const b=e.target.closest('[data-control]');if(!b)return;if(!plan)throw new Error('请先计算本模块计划');const result=await api('/api/modules/'+kind+'/control/'+b.dataset.control+'?plan_id='+encodeURIComponent(plan.plan_id),{method:'POST'});if(result.validation)$('#control-list').innerHTML='<p class="notice">'+(result.validation.valid?'校核通过':'校核未通过')+' · '+result.validation.issues.length+' 个问题</p>';state.audit[kind]=(await api('/api/modules/'+kind+'/audit?limit='+auditRowCount())).events;render();toast('本模块操作已完成');});render();
}
async function wireDevices(){
  const data=await api('/api/shared/devices');state.case=data;state.caseInitial=clone(data);
  const entries=()=>['generators','renewables','batteries','flexible_loads'].flatMap(k=>state.case[k].map((item,i)=>({key:k,index:i,item}))).concat([{key:'grid',item:state.case.grid}]);
  const render=()=>{const list=entries();state.deviceIndex=Math.min(state.deviceIndex,list.length-1);$('#device-select').innerHTML=list.map((e,i)=>'<option value="'+i+'">'+esc(e.item.name||'联络线')+' · '+esc(e.item.id||'grid')+'</option>').join('');$('#device-select').value=state.deviceIndex;const item=list[state.deviceIndex].item;$('#device-form').innerHTML=Object.entries(item).filter(x=>!['id','kind','fuel_type','fuel_curve'].includes(x[0])).map(x=>typeof x[1]==='boolean'?'<label>'+esc(x[0])+'<select data-device-field="'+x[0]+'"><option value="true" '+(x[1]?'selected':'')+'>开启</option><option value="false" '+(!x[1]?'selected':'')+'>关闭</option></select></label>':valueField(x[0],'data-device-field="'+x[0]+'"',x[1],typeof x[1]==='string'?'text':'number')).join('');};
  bind('#device-select','change',e=>{state.deviceIndex=Number(e.target.value);render();});bind('#device-form','input',e=>{entries()[state.deviceIndex].item[e.target.dataset.deviceField]=e.target.tagName==='SELECT'?e.target.value==='true':e.target.type==='text'?e.target.value:Number(e.target.value);dirty();});bind('#restore-device','click',()=>{state.case=clone(state.caseInitial);render();dirty();});bind('#copy-device','click',()=>navigator.clipboard?.writeText(JSON.stringify(state.case,null,2)).then(()=>toast('已复制共享设备参数')));bind('#save-case','click',e=>action(e.target,()=>saveDraft('/api/shared/devices',deviceSnapshot(state.case))));bind('#export-device','click',()=>download('shared-devices.json',deviceSnapshot(state.case)));render();configureDraft(state.case,()=>deviceSnapshot(state.case),v=>Object.assign(state.case,v),render);
}
function deviceSnapshot(data){return Object.fromEntries(['generators','renewables','batteries','flexible_loads','grid','fuel_price_per_liter'].map(k=>[k,data[k]]));}
async function wireNetwork(){const model=await api('/api/network-model');state.networkText=JSON.stringify(model,null,2);const render=()=>{$('#network-json').value=state.networkText;$('#network-summary').textContent=model.name+' · '+model.base_mva+' MVA · '+model.buses.length+' 母线 / '+model.lines.length+' 线路';};bind('#network-json','input',e=>{state.networkText=e.target.value;dirty();});bind('#save-network','click',e=>action(e.target,async()=>{const saved=await saveDraft('/api/network-model',JSON.parse(state.networkText));state.networkText=JSON.stringify(saved,null,2);render();}));bind('#export-network','click',()=>download('shared-network.json',JSON.parse(state.networkText)));render();configureDraft(model,()=>JSON.parse(state.networkText),v=>{state.networkText=JSON.stringify(v,null,2);},render);}
export async function initFeature(feature){
  if(feature==='home'){await boot(async()=>toast('请选择功能进入独立页面'));return;}
  if(feature==='optimization'){await boot(async()=>{const data=await Promise.all([api('/api/solver'),api('/api/modules/'+state.kind+'/optimization')]);state.solvers=data[0];state.configs[state.kind]=data[1];state.savedConfigs[state.kind]=clone(data[1]);wireOptimization();});return;}
  if(feature==='inputs'){await boot(async()=>{const data=await api('/api/modules/'+state.kind+'/inputs');state.configs[state.kind]=data;state.savedConfigs[state.kind]=clone(data);const parent={daily:'weekly',hourly:'daily'}[state.kind];if(parent)state.configs[parent]=await api('/api/modules/'+parent+'/inputs');wireInputs();});return;}
  if(feature==='results'){await boot(async()=>wireResults());return;}
  if(feature==='control'){await boot(async()=>wireControl());return;}
  if(feature==='devices'){await boot(async()=>wireDevices());return;}
  if(feature==='network'){await boot(async()=>wireNetwork());return;}
}

