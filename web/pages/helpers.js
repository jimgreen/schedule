import {state,$,$$,esc,fmt,size} from './common.js';
export function page(key,total,count=size()) {
    const pages=Math.max(1,Math.ceil(total/count));
    state.pages[key]=Math.max(0,Math.min(state.pages[key],pages-1));
    const start=state.pages[key]*count;
    $(`#${key}-page`) && ($(`#${key}-page`).textContent=`${state.pages[key]+1} / ${pages} 页 · ${total} 项`);
    $$(`[data-page^="${key}:"]`).forEach(b=>b.disabled=b.dataset.page.endsWith('-1')?state.pages[key]===0:state.pages[key]===pages-1);
    return [start,start+count];
  }

export function inputField(label,attrs,value,type='number') {
    return `<label>${esc(label)}<input ${attrs} type="${type}" step="any" value="${esc(value ?? '')}"></label>`;
  }

export function chart(series,unit) {
    if(!series.length || !series[0].values?.length) return '<p class="muted">暂无结果，请先计算本模块计划。</p>';
    const container=$(state.feature==='inputs'?'#input-chart':'#result-chart');
    const width=Math.max(240,container.clientWidth||600),height=Math.max(65,(container.clientHeight||145)-22);
    const values=series.flatMap(s=>s.values).filter(Number.isFinite),max=Math.max(...values,1),n=series[0].values.length;
    const left=42,right=width-18,top=14,bottom=height-22,colors=['#58d5b3','#75aaff'];
    const legends=series.map((s,i)=>`<span style="color:${colors[i%2]}">${esc(s.name)} (${esc(unit)})</span>`).join('');
    return `<div class="chart-legend">${legends}</div><svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${esc(unit)}曲线"><path d="M${left} ${top}V${bottom}H${right}" fill="none" stroke="#38506e"/><text x="0" y="${top+4}">${fmt(max,max<10?1:0)}</text><text x="18" y="${bottom}">0</text><text x="${left}" y="${height-3}">1</text><text x="${right}" y="${height-3}" text-anchor="end">${n} 时段</text>${series.map((s,i)=>`<polyline fill="none" stroke="${colors[i%2]}" stroke-width="2" points="${s.values.map((v,j)=>`${left+j*(right-left)/Math.max(n-1,1)},${bottom-Number(v)*(bottom-top)/max}`).join(' ')}"><title>${esc(s.name)} (${esc(unit)})</title></polyline>`).join('')}</svg>`;
  }

export function table(headers,rows) { return `<table><thead><tr>${headers.map(x=>`<th>${esc(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`; }

export function download(name,value) {
    const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

export function downloadText(name,text,mime='text/plain') {
    const url=URL.createObjectURL(new Blob([text],{type:mime})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

export async function readFile(event) {
    const file=event.target.files?.[0]; if(!file)return null;
    if(file.size>8*1024*1024)throw new Error('JSON 文件不能超过 8 MB');
    const data=JSON.parse(await file.text());event.target.value='';return data;
  }
