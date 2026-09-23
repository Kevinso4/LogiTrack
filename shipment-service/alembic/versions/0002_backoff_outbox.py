"""Añade `outbox_events.proximo_intento_en`: backoff exponencial del relay.

Antes el filtro era `intentos < max`, un tope duro que abandonaba el evento
para siempre a los pocos segundos de caído el broker. Ahora la fila se
reprograma con backoff (1 s, 2 s, 4 s… con techo) y sigue reintentando;
`outbox_max_intentos` pasa a ser solo un umbral de alarma.

Revision ID: 0002_shipment
Revises: 0001_shipment
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_shipment"
down_revision: Union[str, None] = "0001_shipment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("proximo_intento_en", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_outbox_events_proximo_intento_en", "outbox_events", ["proximo_intento_en"]
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_proximo_intento_en", table_name="outbox_events")
    op.drop_column("outbox_events", "proximo_intento_en")
