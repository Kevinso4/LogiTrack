"""Esquema inicial de fleet_db: vehicles, drivers, outbox y dedupe.

Revision ID: 0001_fleet
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models import JSONPortable

revision: str = "0001_fleet"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("plate", sa.String(20), nullable=False, unique=True),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("capacity_kg", sa.Float(), nullable=False),
        sa.Column("capacity_m3", sa.Float(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("insurance_expiry", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="activo"),
        sa.Column("motivo_estado", sa.Text(), nullable=True),
        sa.Column("refrigeration_capable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("hazmat_certified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("zona", sa.String(60), nullable=False, server_default="sin_asignar"),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_vehicles_plate", "vehicles", ["plate"])
    op.create_index("ix_vehicles_type", "vehicles", ["type"])
    op.create_index("ix_vehicles_status", "vehicles", ["status"])
    op.create_index("ix_vehicles_zona", "vehicles", ["zona"])
    # Índice compuesto: es la consulta que más golpea Routing Service.
    op.create_index("ix_vehicles_disponibilidad", "vehicles", ["status", "type", "zona"])

    op.create_table(
        "drivers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("license_number", sa.String(40), nullable=False, unique=True),
        sa.Column("license_categories", JSONPortable, nullable=False),
        sa.Column("license_expiry", sa.Date(), nullable=False),
        sa.Column("hazmat_certification", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "refrigerated_certification", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("vehicle_id", sa.String(36), sa.ForeignKey("vehicles.id"), nullable=True),
        sa.Column("hours_driven_week", sa.Float(), nullable=False, server_default="0"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_drivers_license_number", "drivers", ["license_number"])
    op.create_index("ix_drivers_vehicle_id", "drivers", ["vehicle_id"])

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

    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("procesado_en", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("processed_events")
    op.drop_table("outbox_events")
    op.drop_table("drivers")
    op.drop_table("vehicles")
