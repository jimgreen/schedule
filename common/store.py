from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .schemas import (
    Battery,
    CaseData,
    ControlEvent,
    ControlState,
    DieselGenerator,
    FlexibleLoad,
    Forecast,
    FuelCurvePoint,
    GridConnection,
    NetworkModel,
    OptimizationParameters,
    PlanResult,
    Renewable,
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS diesel_generators (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fuel_curve_points (
    generator_id TEXT NOT NULL REFERENCES diesel_generators(id) ON DELETE CASCADE,
    point_index INTEGER NOT NULL,
    power_kw REAL NOT NULL,
    liters_per_hour REAL NOT NULL,
    PRIMARY KEY (generator_id, point_index)
);
CREATE TABLE IF NOT EXISTS renewables (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batteries (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flexible_loads (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS grid_connections (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS optimization_parameters (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS network_models (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    plan_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    horizon_steps INTEGER NOT NULL,
    interval_minutes INTEGER NOT NULL,
    status TEXT NOT NULL,
    solver TEXT NOT NULL,
    objective REAL,
    mip_gap REAL,
    elapsed_seconds REAL NOT NULL,
    total_liters REAL NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plans_kind_created ON plans(kind, created_at DESC);
CREATE TABLE IF NOT EXISTS control_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    auto_hourly_enabled INTEGER NOT NULL DEFAULT 1,
    last_published_plan_id TEXT,
    last_executed_plan_id TEXT
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    plan_id TEXT,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScheduleStore:
    """SQLite repository shared by the optimizer and the web API."""

    def __init__(self, db_path: str | Path | None = None):
        # Runtime SQLite is kept with the realtime database service rather than
        # inside the source checkout. SCHEDULE_DB_PATH remains an override for
        # tests and deployments that use another database directory.
        default_path = Path(r"D:\codex\sqldb\realtime\schedule") / "schedule.db"
        self.db_path = Path(db_path or os.getenv("SCHEDULE_DB_PATH", default_path))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(SCHEMA_SQL)
            connection.execute("INSERT OR IGNORE INTO control_state(id) VALUES (1)")
            connection.commit()

    def save_case(self, case: CaseData) -> None:
        timestamp = _now()
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM fuel_curve_points")
            for table in ("diesel_generators", "renewables", "batteries", "flexible_loads"):
                connection.execute(f"DELETE FROM {table}")
            for generator in case.generators:
                connection.execute("INSERT INTO diesel_generators(id,payload,updated_at) VALUES(?,?,?)", (generator.id, generator.model_dump_json(), timestamp))
                connection.executemany(
                    "INSERT INTO fuel_curve_points(generator_id,point_index,power_kw,liters_per_hour) VALUES(?,?,?,?)",
                    [(generator.id, index, point.power_kw, point.liters_per_hour) for index, point in enumerate(generator.fuel_curve)],
                )
            for table, values in (("renewables", case.renewables), ("batteries", case.batteries), ("flexible_loads", case.flexible_loads)):
                connection.executemany(f"INSERT INTO {table}(id,payload,updated_at) VALUES(?,?,?)", [(item.id, item.model_dump_json(), timestamp) for item in values])
            connection.execute("INSERT OR REPLACE INTO grid_connections(id,payload,updated_at) VALUES(1,?,?)", (case.grid.model_dump_json(), timestamp))
            connection.execute("INSERT OR REPLACE INTO forecasts(id,payload,updated_at) VALUES(1,?,?)", (case.forecast.model_dump_json(), timestamp))
            connection.execute("INSERT OR REPLACE INTO optimization_parameters(id,payload,updated_at) VALUES(1,?,?)", (case.optimization.model_dump_json(), timestamp))
            connection.execute("INSERT OR REPLACE INTO network_models(id,payload,updated_at) VALUES(1,?,?)", (case.network_model.model_dump_json(), timestamp))
            connection.commit()

    def load_case(self) -> CaseData | None:
        with self._lock, self._connect() as connection:
            generator_rows = connection.execute("SELECT payload FROM diesel_generators ORDER BY id").fetchall()
            grid_row = connection.execute("SELECT payload FROM grid_connections WHERE id=1").fetchone()
            forecast_row = connection.execute("SELECT payload FROM forecasts WHERE id=1").fetchone()
            optimization_row = connection.execute("SELECT payload FROM optimization_parameters WHERE id=1").fetchone()
            network_row = connection.execute("SELECT payload FROM network_models WHERE id=1").fetchone()
            if not generator_rows or grid_row is None or forecast_row is None:
                return None
            generators = [DieselGenerator.model_validate_json(row["payload"]) for row in generator_rows]
            points = connection.execute("SELECT generator_id,point_index,power_kw,liters_per_hour FROM fuel_curve_points ORDER BY generator_id,point_index").fetchall()
            point_map: dict[str, list[FuelCurvePoint]] = {}
            for row in points:
                point_map.setdefault(row["generator_id"], []).append(FuelCurvePoint(power_kw=row["power_kw"], liters_per_hour=row["liters_per_hour"]))
            generators = [generator.model_copy(update={"fuel_curve": point_map.get(generator.id, generator.fuel_curve)}) for generator in generators]
            renewables = [Renewable.model_validate_json(row["payload"]) for row in connection.execute("SELECT payload FROM renewables ORDER BY id")]
            batteries = [Battery.model_validate_json(row["payload"]) for row in connection.execute("SELECT payload FROM batteries ORDER BY id")]
            flexible_loads = [FlexibleLoad.model_validate_json(row["payload"]) for row in connection.execute("SELECT payload FROM flexible_loads ORDER BY id")]
            return CaseData(
                generators=generators,
                renewables=renewables,
                batteries=batteries,
                flexible_loads=flexible_loads,
                grid=GridConnection.model_validate_json(grid_row["payload"]),
                forecast=Forecast.model_validate_json(forecast_row["payload"]),
                optimization=OptimizationParameters.model_validate_json(optimization_row["payload"]) if optimization_row else OptimizationParameters(),
                network_model=NetworkModel.model_validate_json(network_row["payload"]) if network_row else NetworkModel(),
            )

    def save_optimization(self, parameters: OptimizationParameters) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("INSERT OR REPLACE INTO optimization_parameters(id,payload,updated_at) VALUES(1,?,?)", (parameters.model_dump_json(), _now()))
            connection.commit()

    def load_optimization(self) -> OptimizationParameters:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT payload FROM optimization_parameters WHERE id=1").fetchone()
            return OptimizationParameters.model_validate_json(row["payload"]) if row else OptimizationParameters()

    def save_network_model(self, model: NetworkModel) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("INSERT OR REPLACE INTO network_models(id,payload,updated_at) VALUES(1,?,?)", (model.model_dump_json(), _now()))
            connection.commit()

    def load_network_model(self) -> NetworkModel:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT payload FROM network_models WHERE id=1").fetchone()
            return NetworkModel.model_validate_json(row["payload"]) if row else NetworkModel()

    def save_plan(self, plan: PlanResult) -> None:
        report = plan.solver_report
        with self._lock, self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO plans
                (plan_id,kind,horizon_steps,interval_minutes,status,solver,objective,mip_gap,elapsed_seconds,total_liters,created_at,payload)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (plan.plan_id, plan.kind.value, plan.horizon_steps, plan.interval_minutes, plan.status,
                 report.solver, report.objective, report.mip_gap, report.elapsed_seconds,
                 plan.fuel_summary.total_liters, plan.created_at, plan.model_dump_json()),
            )
            connection.commit()

    def get_plan(self, plan_id: str) -> PlanResult | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT payload FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
            return None if row is None else PlanResult.model_validate_json(row["payload"])

    def list_plans(self, kind: str | None = None, limit: int = 20) -> list[PlanResult]:
        with self._lock, self._connect() as connection:
            if kind:
                rows = connection.execute("SELECT payload FROM plans WHERE kind=? ORDER BY created_at DESC LIMIT ?", (kind, limit)).fetchall()
            else:
                rows = connection.execute("SELECT payload FROM plans ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [PlanResult.model_validate_json(row["payload"]) for row in rows]

    def control_state(self) -> ControlState:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT auto_hourly_enabled,last_published_plan_id,last_executed_plan_id FROM control_state WHERE id=1").fetchone()
            if row is None:
                return ControlState()
            return ControlState(auto_hourly_enabled=bool(row["auto_hourly_enabled"]), last_published_plan_id=row["last_published_plan_id"], last_executed_plan_id=row["last_executed_plan_id"])

    def update_control(self, state: ControlState) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("UPDATE control_state SET auto_hourly_enabled=?,last_published_plan_id=?,last_executed_plan_id=? WHERE id=1", (int(state.auto_hourly_enabled), state.last_published_plan_id, state.last_executed_plan_id))
            connection.commit()

    def add_event(self, event: ControlEvent) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("INSERT INTO audit_events(action,plan_id,detail,created_at) VALUES(?,?,?,?)", (event.action, event.plan_id, event.detail, event.created_at))
            connection.commit()

    def list_events(self, limit: int = 100) -> list[ControlEvent]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT action,plan_id,detail,created_at FROM audit_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [ControlEvent(action=row["action"], plan_id=row["plan_id"], detail=row["detail"], created_at=row["created_at"]) for row in rows]
