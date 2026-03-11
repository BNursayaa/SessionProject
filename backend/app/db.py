from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock

from sqlalchemy import Boolean, Column, Float, Index, Integer, MetaData, Table, Text, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.sql import func


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


def _sqlite_url_from_path(path: Path) -> str:
    # SQLAlchemy wants forward slashes in sqlite file URLs on Windows.
    p = path.resolve().as_posix()
    return f"sqlite+pysqlite:///{p}"


class Db:
    def __init__(self, *, db_path: Path, db_url: str | None = None) -> None:
        self._lock = Lock()

        if db_url:
            self._db_url = db_url
            self._db_path = None
        else:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db_path = db_path
            self._db_url = _sqlite_url_from_path(db_path)

        connect_args = {}
        if self._db_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}

        self._engine = create_engine(self._db_url, connect_args=connect_args, future=True)

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

    @property
    def path(self) -> Path | None:
        return self._db_path

    def _init_schema(self) -> None:
        with self._lock:
            self._meta.create_all(self._engine)

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

                if self._engine.dialect.name == "postgresql":
                    stmt = stmt.returning(self._telemetry.c.id)
                    row_id = int(conn.execute(stmt).scalar_one())
                else:
                    res = conn.execute(stmt)
                    row_id = int(res.lastrowid or 0)
                    if row_id == 0:
                        row_id = int(conn.execute(select(func.max(self._telemetry.c.id))).scalar_one() or 0)

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
