# Schedule MILP 调度平台

本项目提供柴油微电网的三层优化调度：`weekly_plan` 采用 168 个小时步长，`daily_plan` 采用 96 个 15 分钟步长，`hourly_plan` 采用未来 16 个 15 分钟步长并只执行当前 1 个步长。模型包含柴油机启停、爬坡、储能 SOC、风光消纳、可调负荷、联络线、备用和失负荷约束；柴油机油耗曲线用分段线性 MILP 表示。

## 启动

```powershell
python -m pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

浏览器访问 `http://localhost:8000/`。后台自动创建 `D:\codex\sqldb\realtime\schedule\schedule.db` SQLite 数据库，保存资产、油耗曲线、预测、计划版本、柴油消耗统计和控制审计。测试或其他部署可以通过 `SCHEDULE_DB_PATH` 覆盖默认路径。

求解器可切换 `cplex`、`highs`、`cbc`；三个计划始终按 MILP 求解。CPLEX 需要本机安装 CPLEX Python API，HiGHS 由 `highspy` 提供，CBC 需要 `cbc` 命令在 PATH 中。不可用的求解器会返回明确错误，不会降级为 LP。
