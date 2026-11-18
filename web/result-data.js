/* Pure presentation helpers, shared with the Node regression suite. */
(() => {
  const sum = (items, field) => Object.values(items || {}).reduce((s, x) => s + (field ? x[field] || 0 : x || 0), 0);
  const groups = {
    energy: {demand_kwh:'基础负荷电量',diesel_kwh:'柴油发电量',renewable_kwh:'风光消纳电量',curtailed_kwh:'弃风弃光电量',import_kwh:'购电量',export_kwh:'售电量',charge_kwh:'储能充电量',discharge_kwh:'储能放电量',flexible_kwh:'可调负荷电量',lost_load_kwh:'失负荷电量'},
    cost: {fuel:'加权柴油成本',startup:'加权启停成本',grid:'购售电净成本',storage:'加权储能衰减',curtailment:'弃电惩罚',reserve:'备用成本',lost_load:'失负荷惩罚',baseline:'基线偏差惩罚'},
    performance: {build_seconds:'模型构建时间',solve_seconds:'求解接口时间',extract_seconds:'结果提取时间',total_seconds:'计算总时间（不含存储）',variables:'变量总数',binary_variables:'二进制变量数',constraints:'约束总数'},
  };
  function statistics(plan, group) {
    const values = plan?.[{energy:'energy_summary',cost:'cost_breakdown',performance:'performance'}[group]] || {};
    return Object.entries(groups[group]).map(([key,label]) => [label, values[key], group==='energy'?'kWh':group==='cost'?'元':key.endsWith('seconds')?'s':'个']);
  }
  function resources(plan) {
    const row=plan?.dispatch?.[0];
    return [['system','全站'], ...Object.keys(row?.generators||{}).map(id=>['g:'+id,'柴油机 '+id]), ...Object.keys(row?.batteries||{}).map(id=>['b:'+id,'储能 '+id]), ...Object.keys(row?.renewables||{}).map(id=>['r:'+id,'风光 '+id]), ...Object.keys(row?.flexible_loads||{}).map(id=>['f:'+id,'可调负荷 '+id]), ['grid','联络线'],['reserve','备用与失负荷']];
  }
  function resultView(plan, resource, curve) {
    const rows=plan?.dispatch||[], dt=(plan?.interval_minutes||60)/60;
    const [type,id]=resource.split(':');
    let headers, cells, series, unit='kW';
    const s=(name,fn)=>({name,values:rows.map(fn)});
    if(type==='g') {
      headers=['出力 kW','开机','油耗 L/h','时段油耗 L'];
      cells=r=>{const g=r.generators[id];return [g.power_kw,g.on,g.fuel_lph,g.fuel_lph*dt];};
      series=curve==='fuel'?[s('时段油耗',r=>r.generators[id].fuel_lph*dt)]:[s('柴油出力',r=>r.generators[id].power_kw)];unit=curve==='fuel'?'L':'kW';
    } else if(type==='b') {
      headers=['充电 kW','放电 kW','储能 kWh','SOC %'];
      const capacity=plan?.input_snapshot?.batteries?.find(b=>b.id===id)?.capacity_kwh;
      cells=r=>{const b=r.batteries[id];return [b.charge_kw,b.discharge_kw,b.soc_kwh,capacity?b.soc_kwh/capacity*100:null];};
      series=curve==='soc'?[s('储能电量',r=>r.batteries[id].soc_kwh)]:[s('充电',r=>r.batteries[id].charge_kw),s('放电',r=>r.batteries[id].discharge_kw)];unit=curve==='soc'?'kWh':'kW';
    } else if(type==='r') {
      headers=['出力 kW','时段发电 kWh'];cells=r=>[r.renewables[id],r.renewables[id]*dt];series=[s('风光出力',r=>r.renewables[id])];
    } else if(type==='f') {
      headers=['负荷 kW','时段用电 kWh'];cells=r=>[r.flexible_loads[id],r.flexible_loads[id]*dt];series=[s('可调负荷',r=>r.flexible_loads[id])];
    } else if(type==='grid') {
      headers=['购电 kW','售电 kW','净购电 kW'];cells=r=>[r.grid_import_kw,r.grid_export_kw,r.grid_import_kw-r.grid_export_kw];series=[s('购电',r=>r.grid_import_kw),s('售电',r=>r.grid_export_kw)];
    } else if(type==='reserve') {
      headers=['备用 kW','需求 kW','失负荷 kW'];cells=r=>[r.reserve_kw,r.reserve_required_kw,r.lost_load_kw];series=[s('备用',r=>r.reserve_kw),s('需求',r=>r.reserve_required_kw)];
    } else {
      headers=['负荷 kW','柴油 kW','风光 kW','弃电 kW'];cells=r=>[r.demand_kw,sum(r.generators,'power_kw'),sum(r.renewables),r.renewable_curtailment_kw];
      if(curve==='fuel'||curve==='cumulative'){series=[{name:curve==='fuel'?'时段油耗':'累计油耗',values:plan?.fuel_summary?.[curve==='fuel'?'interval_liters':'cumulative_liters']||[]}];unit='L';}
      else if(curve==='renewable')series=[s('风光消纳',r=>sum(r.renewables)),s('弃风弃光',r=>r.renewable_curtailment_kw)];
      else series=[s('基础负荷',r=>r.demand_kw),s('柴油出力',r=>sum(r.generators,'power_kw'))];
    }
    return {headers:['时段',...headers],rows:rows.map(r=>[r.step+1,...cells(r)]),series,unit};
  }
  function transformCurve(values, start, end, scale, offset) {
    if(!Number.isInteger(start)||!Number.isInteger(end)||start<1||end>values.length||start>end)throw new Error('时段范围无效');
    if(!Number.isFinite(scale)||scale<0||!Number.isFinite(offset))throw new Error('比例须为非负有限数，偏移须为有限数');
    const next=values.map((v,i)=>i<start-1||i>=end?v:v*scale+offset);
    if(next.some(v=>!Number.isFinite(v)||v<0))throw new Error('调整后含负值或非有限值，请修改比例或偏移');
    return next;
  }
  function curveTemplate(values, template, scale, source, target) {
    if(!values.length || values.some(v=>!Number.isFinite(v)||v<0))throw new Error('曲线包含无效数值');
    if(!Number.isFinite(scale)||scale<0)throw new Error('模板比例须为非负有限数');
    let next;
    if(template==='flat') next=values.map(()=>sum(values)/values.length);
    else if(template==='peak_valley') {
      const min=Math.min(...values), max=Math.max(...values);
      next=values.map((_,i)=>min+(max-min)*(1-Math.abs(2*i/Math.max(values.length-1,1)-1)));
    } else if(template==='interpolate') next=values.map((_,i)=>values[0]+(values.at(-1)-values[0])*i/Math.max(values.length-1,1));
    else if(template==='copy_parent') {
      if(!source||!target)throw new Error('当前模块没有上级曲线');
      if(Boolean(source.start_time)!==Boolean(target.start_time))throw new Error('两模块须同时设置起点，或同时留空');
      const offset=target.start_time?(Date.parse(target.start_time)-Date.parse(source.start_time))/60000:0;
      if(!Number.isFinite(offset)||offset<0||offset+values.length*target.interval>source.values.length*source.interval)throw new Error('上级曲线未覆盖当前模块的完整时段');
      next=values.map((_,i)=>{
        const x=(offset+i*target.interval)/source.interval, a=Math.floor(x), b=Math.min(a+1,source.values.length-1);
        return source.values[a]+(source.values[b]-source.values[a])*(x-a);
      });
    } else throw new Error('未知曲线模板');
    next=next.map(v=>v*scale);
    if(next.some(v=>!Number.isFinite(v)||v<0))throw new Error('模板生成了无效曲线');
    return next;
  }
  const api={statistics,resources,resultView,transformCurve,curveTemplate};
  if(typeof module!=='undefined')module.exports=api;else window.ScheduleData=api;
})();
