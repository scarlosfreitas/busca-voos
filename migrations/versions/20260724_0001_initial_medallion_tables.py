"""initial medallion tables (bronze/silver/gold)

Creates the first set of tables for the Medallion architecture, incremental over
the schemas already created by ``scripts/init-db.sql``:

* ``bronze.raw_search_response`` — raw intercepted payload + run metadata;
* ``silver.flight`` — normalized flights;
* ``gold.flight_alert`` — append-only history of alerts effectively sent.

The DDL is kept in sync with :mod:`persistence.tables`. The schemas themselves
are created idempotently here too, so the migration is self-contained on a fresh
database that only has ``init-db.sql`` applied (or not).

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PRICE = sa.Numeric(12, 2)


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    op.execute("CREATE SCHEMA IF NOT EXISTS silver")
    op.execute("CREATE SCHEMA IF NOT EXISTS gold")

    op.create_table(
        "raw_search_response",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_origin", sa.Text(), nullable=False),
        sa.Column("route_destination", sa.Text(), nullable=False),
        sa.Column("departure_date", sa.Date(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        schema="bronze",
    )
    op.create_index(
        "ix_raw_search_response_execution_id",
        "raw_search_response",
        ["execution_id"],
        schema="bronze",
    )

    op.create_table(
        "flight",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route_origin", sa.Text(), nullable=False),
        sa.Column("route_destination", sa.Text(), nullable=False),
        sa.Column("departure_date", sa.Date(), nullable=False),
        sa.Column("carrier", sa.Text(), nullable=False),
        sa.Column("flight_number", sa.Text(), nullable=False),
        sa.Column("departure_time", sa.Time(timezone=False), nullable=False),
        sa.Column("price", _PRICE, nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("flight_id", sa.Text(), nullable=False),
        schema="silver",
    )
    op.create_index(
        "ix_flight_execution_id", "flight", ["execution_id"], schema="silver"
    )
    op.create_index("ix_flight_flight_id", "flight", ["flight_id"], schema="silver")

    op.create_table(
        "flight_alert",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flight_id", sa.Text(), nullable=False),
        sa.Column("price", _PRICE, nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=False),
        schema="gold",
    )
    op.create_index(
        "ix_flight_alert_flight_id_alerted_at",
        "flight_alert",
        ["flight_id", "alerted_at"],
        schema="gold",
    )


def downgrade() -> None:
    op.drop_index("ix_flight_alert_flight_id_alerted_at", "flight_alert", schema="gold")
    op.drop_table("flight_alert", schema="gold")

    op.drop_index("ix_flight_flight_id", "flight", schema="silver")
    op.drop_index("ix_flight_execution_id", "flight", schema="silver")
    op.drop_table("flight", schema="silver")

    op.drop_index(
        "ix_raw_search_response_execution_id", "raw_search_response", schema="bronze"
    )
    op.drop_table("raw_search_response", schema="bronze")
