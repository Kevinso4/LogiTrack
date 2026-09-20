"""Esquema inicial de shipment_db: envios, historial, POD, outbox y dedupe.

Revision ID: 0001_shipment
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.models import JSONPortable

revision: str = "0001_shipment"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "envios",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("client_id", sa.String(60), nullable=True),
        sa.Column("estado", sa.String(30), nullable=False, server_default="en_almacen"),
        sa.Column("origen", JSONPortable, nullable=False),
        sa.Column("destino", JSONPortable, nullable=False),
        sa.Column("peso_kg", sa.Float(), nullable=False),
        sa.Column("volumen_m3", sa.Float(), nullable=False),
        sa.Column("is_international", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sla_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "requiere_refrigeracion",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("requiere_hazmat", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ventana_entrega", JSONPortable, nullable=True),
        sa.Column("ruta_id", sa.String(36), nullable=True),
        sa.Column("vehicle_id", sa.String(36), nullable=True),
        sa.Column("vehicle_plate", sa.String(20), nullable=True),
        sa.Column("eta", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_envios_estado", "envios", ["estado"])
    op.create_index("ix_envios_ruta_id", "envios", ["ruta_id"])
    # Consulta caliente: envíos ACTIVOS de un cliente (broadcast/soporte).
    op.create_index("ix_envios_estado_cliente", "envios", ["estado", "client_id"])

    op.create_table(
        "historial_envios",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shipment_id", sa.String(36), sa.ForeignKey("envios.id"), nullable=False),
        sa.Column("desde", sa.String(30), nullable=True),
        sa.Column("hasta", sa.String(30), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=True),
        sa.Column("creada_en", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_historial_envios_shipment_id", "historial_envios", ["shipment_id"])

    op.create_table(
        "pruebas_entrega",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "shipment_id",
            sa.String(36),
            sa.ForeignKey("envios.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("nombre_recibe", sa.String(120), nullable=False),
        sa.Column("documento_recibe", sa.String(40), nullable=True),
        sa.Column("firma_foto_url", sa.String(250), nullable=True),
        sa.Column("comentario", sa.Text(), nullable=True),
        sa.Column("recibido_en", sa.DateTime(timezone=True), nullable=False),
    )

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
    op.drop_table("pruebas_entrega")
    op.drop_table("historial_envios")
    op.drop_table("envios")
