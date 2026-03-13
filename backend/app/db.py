from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock

from sqlalchemy import Boolean, Column, Float, Index, Integer, MetaData, Table, Text, case, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url


@dataclass(frozen=True)
class TelemetryRow:
    id: int
    ts: datetime
    temp_c: float
    amps: float
    vibration: float
    pulses: int
    pwm: int
    is_running: bool


@dataclass(frozen=True)
class ControlCommandRow:
    id: int
    ts: datetime
    action: str
    status: str
    source: str | None
    claimed_by: str | None
    claimed_at: datetime | None
    done_at: datetime | None
    error: str | None


@dataclass(frozen=True)
class ControlStateRow:
    key: str
    ts: datetime
    int_value: int | None


class Db:
    def __init__(self, *, db_url: str) -> None:
        self._lock = Lock()

        self._db_url = db_url
        self._engine = create_engine(self._db_url, future=True)
        if make_url(self._db_url).get_backend_name() != "postgresql":
            raise RuntimeError("Only PostgreSQL is supported. Set DT_DB_URL=postgresql+psycopg://...")

        self._meta = MetaData()
        self._telemetry = Table(
            "telemetry",
            self._meta,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("ts", Text, nullable=False),
            Column("temp_c", Float, nullable=False),
            Column("amps", Float, nullable=False),
            Column("vibration", Float, nullable=False),
            Column("pulses", Integer, nullable=False),
            Column("pwm", Integer, nullable=False),
            Column("is_running", Boolean, nullable=False),
        )
        Index("idx_telemetry_ts", self._telemetry.c.ts)

        self._control = Table(
            "control_commands",
            self._meta,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("ts", Text, nullable=False),
            Column("action", Text, nullable=False),
            Column("status", Text, nullable=False),
            Column("source", Text, nullable=True),
            Column("claimed_by", Text, nullable=True),
            Column("claimed_at", Text, nullable=True),
            Column("done_at", Text, nullable=True),
            Column("error", Text, nullable=True),
        )
        Index("idx_control_status", self._control.c.status)

        self._control_state = Table(
            "control_state",
            self._meta,
            Column("key", Text, primary_key=True),
            Column("ts", Text, nullable=False),
            Column("int_value", Integer, nullable=True),
        )

        self._init_schema()

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def url(self) -> str:
        return self._db_url

    def safe_url(self) -> str:
        return make_url(self._db_url).render_as_string(hide_password=True)

    def kind(self) -> str:
        return make_url(self._db_url).get_backend_name()

    def _init_schema(self) -> None:
        with self._lock:
            self._meta.create_all(self._engine)

            now = datetime.now(timezone.utc)
            with self._engine.begin() as conn:
                existing = (
                    conn.execute(select(self._control_state).where(self._control_state.c.key == "desired_pwm"))
                    .mappings()
                    .first()
                )
                if existing is None:
                    conn.execute(
                        self._control_state.insert().values(key="desired_pwm", ts=now.isoformat(), int_value=0)
                    )

    def insert(
        self,
        *,
        ts: datetime,
        temp_c: float,
        amps: float,
        vibration: float,
        pulses: int,
        pwm: int,
        is_running: bool,
    ) -> TelemetryRow:
        with self._lock:
            with self._engine.begin() as conn:
                stmt = self._telemetry.insert().values(
                    ts=ts.isoformat(),
                    temp_c=float(temp_c),
                    amps=float(amps),
                    vibration=float(vibration),
                    pulses=int(pulses),
                    pwm=int(pwm),
                    is_running=bool(is_running),
                )
                stmt = stmt.returning(self._telemetry.c.id)
                row_id = int(conn.execute(stmt).scalar_one())

        return TelemetryRow(
            id=row_id,
            ts=ts,
            temp_c=float(temp_c),
            amps=float(amps),
            vibration=float(vibration),
            pulses=int(pulses),
            pwm=int(pwm),
            is_running=bool(is_running),
        )

    def _row_to_model(self, row) -> TelemetryRow:
        return TelemetryRow(
            id=int(row["id"]),
            ts=datetime.fromisoformat(row["ts"]),
            temp_c=float(row["temp_c"]),
            amps=float(row["amps"]),
            vibration=float(row["vibration"]),
            pulses=int(row["pulses"]),
            pwm=int(row["pwm"]),
            is_running=bool(row["is_running"]),
        )

    def latest(self) -> TelemetryRow | None:
        with self._lock:
            with self._engine.connect() as conn:
                stmt = select(self._telemetry).order_by(self._telemetry.c.id.desc()).limit(1)
                r = conn.execute(stmt).mappings().first()
        if r is None:
            return None
        return self._row_to_model(r)

    def previous(self, *, before_id: int) -> TelemetryRow | None:
        with self._lock:
            with self._engine.connect() as conn:
                stmt = (
                    select(self._telemetry)
                    .where(self._telemetry.c.id < int(before_id))
                    .order_by(self._telemetry.c.id.desc())
                    .limit(1)
                )
                r = conn.execute(stmt).mappings().first()
        if r is None:
            return None
        return self._row_to_model(r)

    def history(self, *, limit: int = 300) -> list[TelemetryRow]:
        limit = max(1, min(int(limit), 10_000))
        with self._lock:
            with self._engine.connect() as conn:
                stmt = select(self._telemetry).order_by(self._telemetry.c.id.desc()).limit(limit)
                rows = list(conn.execute(stmt).mappings().all())
        items: list[TelemetryRow] = []
        for r in reversed(rows):
            items.append(self._row_to_model(r))
        return items

    def _control_row_to_model(self, row) -> ControlCommandRow:
        claimed_at = row.get("claimed_at")
        done_at = row.get("done_at")
        return ControlCommandRow(
            id=int(row["id"]),
            ts=datetime.fromisoformat(row["ts"]),
            action=str(row["action"]),
            status=str(row["status"]),
            source=str(row["source"]) if row.get("source") is not None else None,
            claimed_by=str(row["claimed_by"]) if row.get("claimed_by") is not None else None,
            claimed_at=datetime.fromisoformat(claimed_at) if claimed_at else None,
            done_at=datetime.fromisoformat(done_at) if done_at else None,
            error=str(row["error"]) if row.get("error") is not None else None,
        )

    def get_desired_pwm(self) -> ControlStateRow:
        with self._lock:
            with self._engine.connect() as conn:
                row = (
                    conn.execute(select(self._control_state).where(self._control_state.c.key == "desired_pwm"))
                    .mappings()
                    .first()
                )
        if row is None:
            now = datetime.now(timezone.utc)
            return ControlStateRow(key="desired_pwm", ts=now, int_value=0)
        return ControlStateRow(
            key=str(row["key"]),
            ts=datetime.fromisoformat(row["ts"]),
            int_value=int(row["int_value"]) if row.get("int_value") is not None else None,
        )

    def set_desired_pwm(self, *, value: int) -> ControlStateRow:
        v = max(0, min(int(value), 255))
        now = datetime.now(timezone.utc)
        with self._lock:
            with self._engine.begin() as conn:
                upd = (
                    self._control_state.update()
                    .where(self._control_state.c.key == "desired_pwm")
                    .values(ts=now.isoformat(), int_value=v)
                )
                res = conn.execute(upd)
                if int(getattr(res, "rowcount", 0) or 0) == 0:
                    conn.execute(self._control_state.insert().values(key="desired_pwm", ts=now.isoformat(), int_value=v))
                row = (
                    conn.execute(select(self._control_state).where(self._control_state.c.key == "desired_pwm"))
                    .mappings()
                    .one()
                )
        return ControlStateRow(
            key=str(row["key"]),
            ts=datetime.fromisoformat(row["ts"]),
            int_value=int(row["int_value"]) if row.get("int_value") is not None else None,
        )

    def insert_command(self, *, action: str, source: str | None = None) -> ControlCommandRow:
        now = datetime.now(timezone.utc)
        with self._lock:
            with self._engine.begin() as conn:
                stmt = self._control.insert().values(
                    ts=now.isoformat(),
                    action=str(action),
                    status="pending",
                    source=source,
                    claimed_by=None,
                    claimed_at=None,
                    done_at=None,
                    error=None,
                )

                stmt = stmt.returning(self._control.c.id)
                row_id = int(conn.execute(stmt).scalar_one())

                row = conn.execute(select(self._control).where(self._control.c.id == row_id)).mappings().one()
        return self._control_row_to_model(row)

    def claim_next_command(self, *, claimed_by: str) -> ControlCommandRow | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            with self._engine.begin() as conn:
                for _ in range(3):
                    prio = case(
                        (self._control.c.action == "stop", 0),
                        (self._control.c.action == "start", 1),
                        else_=2,
                    )
                    row = (
                        conn.execute(
                            select(self._control)
                            .where(self._control.c.status == "pending")
                            .order_by(prio.asc(), self._control.c.id.asc())
                            .limit(1)
                        )
                        .mappings()
                        .first()
                    )
                    if row is None:
                        return None

                    cmd_id = int(row["id"])
                    upd = (
                        self._control.update()
                        .where(self._control.c.id == cmd_id)
                        .where(self._control.c.status == "pending")
                        .values(status="claimed", claimed_by=str(claimed_by), claimed_at=now.isoformat())
                    )
                    res = conn.execute(upd)
                    if int(getattr(res, "rowcount", 0) or 0) != 1:
                        continue

                    claimed = conn.execute(select(self._control).where(self._control.c.id == cmd_id)).mappings().one()
                    return self._control_row_to_model(claimed)

        return None

    def ack_command(self, *, cmd_id: int, ok: bool, error: str | None = None) -> ControlCommandRow | None:
        now = datetime.now(timezone.utc)
        status = "done" if ok else "failed"
        with self._lock:
            with self._engine.begin() as conn:
                upd = (
                    self._control.update()
                    .where(self._control.c.id == int(cmd_id))
                    .values(status=status, done_at=now.isoformat(), error=error)
                )
                conn.execute(upd)
                row = conn.execute(select(self._control).where(self._control.c.id == int(cmd_id))).mappings().first()
        if row is None:
            return None
        return self._control_row_to_model(row)
