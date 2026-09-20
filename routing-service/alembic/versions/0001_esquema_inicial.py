"""Esquema inicial de routing_db: rutas, paradas, outbox y dedupe.

Revision ID: 0001_routing
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models import JSONPortable

revision: str = "0001_routing"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rutas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("shipment_id", sa.String(36), nullable=False),
        sa.Column("vehicle_id", sa.String(36), nullable=True),
        sa.Column("vehicle_plate", sa.String(20), nullable=True),
        sa.Column("estado", sa.String(30), nullable=False, server_default="pendiente"),
        sa.Column("origen", JSONPortable, nullable=False),
        sa.Column("destino", JSONPortable, nullable=False),
        sa.Column("peso_kg", sa.Float(), nullable=False),
        sa.Column("volumen_m3", sa.Float(), nullable=False),
        sa.Column(
            "requiere_refrigeracion", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("requiere_hazmat", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("distancia_km", sa.Float(), nullable=True),
        sa.Column("duracion_min", sa.Float(), nullable=True),
        sa.Column("eta_actual", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tipo_calculo", sa.String(20), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("intentos_recalculo", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creada_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizada_en", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rutas_shipment_id", "rutas", ["shipment_id"])
    op.create_index("ix_rutas_vehicle_id", "rutas", ["vehicle_id"])
    op.create_index("ix_rutas_estado", "rutas", ["estado"])
    # Consulta caliente: rutas ACTIVAS por vehículo (recálculo por incidente).
    op.create_index("ix_rutas_activas_vehiculo", "rutas", ["estado", "vehicle_id"])

    op.create_table(
        "paradas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ruta_id", sa.String(36), sa.ForeignKey("rutas.id"), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("direccion", sa.String(200), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("ventana_desde", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ventana_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("eta_llegada", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_paradas_ruta_id", "paradas", ["ruta_id"])

    op.create_table(
        "intentos_asignacion",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ruta_id", sa.String(36), sa.ForeignKey("rutas.id"), nullable=False),
        sa.Column("shipment_id", sa.String(36), nullable=False),
        sa.Column("causa", sa.String(50), nullable=False),
        sa.Column("vehicle_anterior", sa.String(36), nullable=True),
        sa.Column("fallido", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("creada_en", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_intentos_asignacion_ruta_id", "intentos_asignacion", ["ruta_id"])
    op.create_index("ix_intentos_asignacion_shipment_id", "intentos_asignacion", ["shipment_id"])

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
    op.drop_table("intentos_asignacion")
    op.drop_table("paradas")
    op.drop_table("rutas")
