"""Esquema inicial de tracking_db: hypertable de telemetría + outbox.

Revision ID: 0001_tracking
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.config import get_settings
from app.models import JSONPortable

revision: str = "0001_tracking"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "telemetry",
        sa.Column("vehicle_id", sa.String(36), nullable=False),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_id", sa.String(64), nullable=True),
        sa.Column("fabricante", sa.String(40), nullable=False, server_default="generico"),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("speed_kmh", sa.Float(), nullable=True),
        sa.Column("engine_temp_c", sa.Float(), nullable=True),
        sa.Column("fuel_level_pct", sa.Float(), nullable=True),
        sa.Column("odometer_km", sa.Float(), nullable=True),
        sa.Column("engine_hours", sa.Float(), nullable=True),
        sa.Column("obd2_codes", JSONPortable, nullable=False),
        sa.Column("ingestado_en", sa.DateTime(timezone=True), nullable=False),
        # La PK incluye la columna de partición: requisito de TimescaleDB.
        sa.PrimaryKeyConstraint("vehicle_id", "time"),
    )
    op.create_index("ix_telemetry_vehiculo_tiempo", "telemetry", ["vehicle_id", "time"])
    op.create_index("ix_telemetry_time", "telemetry", ["time"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload", JSONPortable, nullable=False),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_events_published_at", "outbox_events", ["published_at"])

    _convertir_en_hypertable()


def _convertir_en_hypertable() -> None:
    """Activa TimescaleDB si está disponible; si no, deja una tabla normal."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    settings = get_settings()
    disponible = bind.execute(
        sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")
    ).scalar()
    if not disponible:
        print(
            "[tracking] AVISO: la extensión timescaledb no está disponible en este "
            "PostgreSQL. 'telemetry' queda como tabla normal (funciona igual, sin "
            "particionado automático)."
        )
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.execute(
        sa.text(
            "SELECT create_hypertable('telemetry', 'time', "
            f"chunk_time_interval => INTERVAL '{settings.chunk_dias} days', "
            "if_not_exists => TRUE, migrate_data => TRUE)"
        )
    )
    if settings.retencion_dias > 0:
        op.execute(
            sa.text(
                "SELECT add_retention_policy('telemetry', "
                f"INTERVAL '{settings.retencion_dias} days', if_not_exists => TRUE)"
            )
        )


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("telemetry")
