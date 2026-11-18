"""Independent checks of persisted dispatch using the captured solve inputs."""
from datetime import datetime, timezone
from math import isfinite

from .schemas import CaseData, PlanResult, PlanValidationReport, ValidationIssue


def validate_plan(case: CaseData, plan: PlanResult) -> PlanValidationReport:
    issues = []
    metrics = {"fuel_total_liters": 0.0, "max_power_balance_error_kw": 0.0, "lost_load_kwh": 0.0}

    def issue(code, message, step=None):
        issues.append(ValidationIssue(code=code, message=message, step=step))

    def report():
        return PlanValidationReport(plan_id=plan.plan_id, valid=not issues, issues=issues,
                                    metrics=metrics, checked_at=datetime.now(timezone.utc).isoformat())

    if plan.input_snapshot is None:
        issue('missing_snapshot', '旧版本未记录输入快照，请重新计算后校核')
        return report()
    case = plan.input_snapshot
    horizon = case.horizons[plan.kind.value]
    config = case.config_for(horizon)
    forecast = case.forecast_for(horizon)
    if plan.status not in {'solved', 'feasible'} or plan.solver_report.objective is None:
        issue('no_solution', '计划没有可用解')
    if len(plan.dispatch) != horizon.steps or plan.interval_minutes != horizon.interval_minutes or plan.horizon_steps != horizon.steps:
        issue('horizon', '计划长度或时间步长与所属模块不一致')
        return report()
    dt, tol = horizon.step_hours, 0.02
    previous_power = {g.id:g.initial_power_kw for g in case.generators}
    previous_on = {g.id:int(g.initial_on) for g in case.generators}
    duration = {g.id:g.initial_up_steps if g.initial_on else g.initial_down_steps for g in case.generators}
    previous_soc = {b.id:b.initial_soc*b.capacity_kwh for b in case.batteries}
    flex_energy = {f.id:0.0 for f in case.flexible_loads}
    fuel_totals = {g.id:0.0 for g in case.generators}
    intervals = []

    def num(value):
        result = float(value)
        if not isfinite(result):
            raise ValueError('non-finite')
        return result

    for t, row in enumerate(plan.dispatch):
        try:
            if row['step'] != t:
                issue('step', '时段编号不连续', t)
            generation = renewable = battery_net = flexible = interval_fuel = available_reserve = 0.0
            for g in case.generators:
                v = row['generators'][g.id]
                p, on, fuel = num(v['power_kw']), num(v['on']), num(v['fuel_lph'])
                if abs(on-round(on)) > 1e-4 or round(on) not in (0,1) or p < g.min_power_kw*on-tol or p > g.max_power_kw*on+tol:
                    issue('generator_bounds', f'{g.name} 开停状态或出力越界', t)
                if p-previous_power[g.id] > g.ramp_up_kw_per_step+tol or previous_power[g.id]-p > g.ramp_down_kw_per_step+tol:
                    issue('ramp', f'{g.name} 爬坡越界', t)
                if round(on) != previous_on[g.id]:
                    minimum = g.min_up_steps if previous_on[g.id] else g.min_down_steps
                    if duration[g.id] < minimum:
                        issue('minimum_duration', f'{g.name} 不满足最小开停机时长', t)
                    duration[g.id] = 0
                duration[g.id] += 1
                previous_on[g.id], previous_power[g.id] = round(on), p
                expected_fuel = 0.0
                if on > 0.5:
                    for a,b in zip(g.fuel_curve,g.fuel_curve[1:]):
                        if a.power_kw-tol <= p <= b.power_kw+tol:
                            expected_fuel = a.liters_per_hour+(p-a.power_kw)/(b.power_kw-a.power_kw)*(b.liters_per_hour-a.liters_per_hour)
                            break
                if abs(fuel-expected_fuel) > tol:
                    issue('fuel_curve', f'{g.name} 油耗率与分段曲线不符', t)
                generation += p
                interval_fuel += fuel*dt
                fuel_totals[g.id] += fuel*dt
                available_reserve += min(g.max_power_kw*on-p, g.ramp_up_kw_per_step)
            for r in case.renewables:
                p = num(row['renewables'][r.id])
                capacity = sum(i.capacity_kw for i in case.renewables if i.kind==r.kind)
                available = min(r.capacity_kw, forecast['wind_kw' if r.kind=='wind' else 'pv_kw'][t]*r.capacity_kw/capacity)
                if p < -tol or p > available+tol:
                    issue('renewable', f'{r.name} 超过可用功率', t)
                renewable += p
            for b in case.batteries:
                v = row['batteries'][b.id]
                charge, discharge, soc = num(v['charge_kw']),num(v['discharge_kw']),num(v['soc_kwh'])
                if charge < -tol or discharge < -tol or charge > b.max_charge_kw+tol or discharge > b.max_discharge_kw+tol or (charge>tol and discharge>tol):
                    issue('battery_power', f'{b.name} 充放电越界或同时充放电', t)
                if not b.min_soc*b.capacity_kwh-tol <= soc <= b.max_soc*b.capacity_kwh+tol:
                    issue('soc_bounds', f'{b.name} SOC 越界', t)
                expected_soc = previous_soc[b.id]+charge*b.charge_efficiency*dt-discharge/b.discharge_efficiency*dt
                if abs(soc-expected_soc)>tol:
                    issue('soc_balance', f'{b.name} SOC 能量转移不一致', t)
                previous_soc[b.id] = soc
                battery_net += discharge-charge
                available_reserve += min(b.max_discharge_kw-discharge, (soc-b.min_soc*b.capacity_kwh)*b.discharge_efficiency/dt)
            for f in case.flexible_loads:
                p = num(row['flexible_loads'][f.id])
                if not f.min_kw-tol <= p <= f.max_kw+tol:
                    issue('flexible_bounds', f'{f.name} 出力越界', t)
                flex_energy[f.id] += p*dt
                flexible += p
            imp, exp, lost = num(row['grid_import_kw']),num(row['grid_export_kw']),num(row['lost_load_kw'])
            if not -tol <= imp <= case.grid.import_limit_kw+tol or not -tol <= exp <= case.grid.export_limit_kw+tol or (imp>tol and exp>tol):
                issue('grid_bounds', '联络线越界或同时购售电', t)
            demand = forecast['demand_kw'][t]
            if abs(num(row['demand_kw'])-demand)>tol or not -tol <= lost <= demand*0.5+tol:
                issue('demand', '需求或失负荷与输入不符', t)
            available_reserve += case.grid.import_limit_kw-imp
            reserve = num(row['reserve_kw'])
            if reserve < demand*config.forecast.reserve_fraction-tol or reserve > available_reserve+tol:
                issue('reserve', '备用不足或超过可用容量', t)
            balance = abs(generation+renewable+battery_net+imp+lost-demand-flexible-exp)
            metrics['max_power_balance_error_kw'] = max(metrics['max_power_balance_error_kw'],balance)
            metrics['lost_load_kwh'] += lost*dt
            if balance>tol:
                issue('power_balance', f'功率平衡偏差 {balance:.4f} kW', t)
            intervals.append(interval_fuel)
        except (KeyError, TypeError, ValueError):
            issue('incomplete_dispatch', '出力字段缺失或存在非有限数值', t)
    for b in case.batteries:
        if b.terminal_soc is not None and abs(previous_soc[b.id]-b.terminal_soc*b.capacity_kwh)>tol:
            issue('terminal_soc', f'{b.name} 末端 SOC 不满足要求')
    for f in case.flexible_loads:
        if f.shiftable_energy_kwh and abs(flex_energy[f.id]-f.shiftable_energy_kwh*horizon.steps*dt/24)>tol:
            issue('flexible_energy', f'{f.name} 能量总量不满足要求')
    metrics['fuel_total_liters'] = sum(intervals)
    fuel = plan.fuel_summary
    if abs(sum(intervals)-fuel.total_liters)>tol or len(fuel.interval_liters)!=len(intervals):
        issue('fuel_total','油耗统计不一致')
    cumulative = 0.0
    for t, liters in enumerate(intervals):
        cumulative += liters
        if t>=len(fuel.interval_liters) or t>=len(fuel.cumulative_liters) or abs(liters-fuel.interval_liters[t])>tol or abs(cumulative-fuel.cumulative_liters[t])>tol:
            issue('fuel_interval','分时或累计油耗统计不一致',t)
    for key,liters in fuel_totals.items():
        if abs(fuel.by_generator_liters.get(key,-1)-liters)>tol:
            issue('fuel_generator',f'{key} 油耗统计不一致')
    return report()
