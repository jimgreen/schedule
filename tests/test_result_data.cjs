const {test}=require('node:test');
const assert=require('node:assert/strict');
const {transformCurve,resultView,statistics}=require('../web/result-data.js');
const {curveTemplate}=require('../web/result-data.js');
test('templates preserve input, allow zero scale, and generate exact endpoints',()=>{
  const input=[10,20,30,40];
  assert.deepEqual(curveTemplate(input,'flat',1),[25,25,25,25]);
  assert.deepEqual(curveTemplate(input,'interpolate',0),[0,0,0,0]);
  assert.deepEqual(curveTemplate([10,100,30],'interpolate',1),[10,20,30]);
  assert.deepEqual(input,[10,20,30,40]);
  assert.throws(()=>curveTemplate(input,'flat',NaN));
});
test('parent copy aligns timestamps and rejects partial or mismatched coverage',()=>{
  const source={values:[0,60,120],interval:60,start_time:'2026-11-18T00:00:00Z'};
  const target={interval:15,start_time:'2026-11-18T01:00:00Z'};
  assert.deepEqual(curveTemplate([0,0,0,0],'copy_parent',1,source,target),[60,75,90,105]);
  assert.throws(()=>curveTemplate([0,0],'copy_parent',1,source,{interval:15}));
  assert.throws(()=>curveTemplate([0,0],'copy_parent',1,source,{...target,start_time:'2026-11-18T02:45:00Z'}));
});
test('bulk edit only changes chosen range; rejects invalid values without mutation',()=>{
  const original=[10,20,30,40];assert.deepEqual(transformCurve(original,2,3,2,5),[10,45,65,40]);assert.deepEqual(original,[10,20,30,40]);
  assert.throws(()=>transformCurve(original,0,3,2,0));assert.throws(()=>transformCurve(original,1,4,1,-50));assert.throws(()=>transformCurve(original,1,4,Infinity,0));
});
const plan={interval_minutes:15,input_snapshot:{batteries:[{id:'b',capacity_kwh:100}]},dispatch:[{step:0,generators:{g:{power_kw:80,on:1,fuel_lph:24}},batteries:{b:{charge_kw:0,discharge_kw:20,soc_kwh:50}},renewables:{r:12},flexible_loads:{f:8},grid_import_kw:10,grid_export_kw:0}]};
test('resource details preserve power, fuel units and SOC',()=>{
 assert.deepEqual(resultView(plan,'g:g','fuel').rows[0],[1,80,1,24,6]);
 assert.deepEqual(resultView(plan,'b:b','soc').rows[0],[1,0,20,50,50]);
 assert.equal(resultView(plan,'b:b','soc').unit,'kWh');
 assert.deepEqual(resultView(plan,'f:f','power').series[0].values,[8]);
});
test('historical missing metrics stay unavailable rather than fake zero',()=>{assert.equal(statistics({},'cost')[0][1],undefined);});
