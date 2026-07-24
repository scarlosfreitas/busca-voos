"""SQLAlchemy Core schema for the Medallion layers (bronze/silver/gold).

This module is the single in-code definition of the persisted data schema. It is
a *schema contract* only — no business logic and no I/O. Two consumers read it:

* ``persistence.repositories`` builds INSERT/SELECT statements against these
  :class:`~sqlalchemy.Table` objects;
* the Alembic migration under ``migrations/versions/`` is the versioned DDL that
  actually creates these tables in production.

Per ``docs/standards/architecture.md`` §4, production schema changes go through
Alembic migrations — never ``metadata.create_all`` in production. The schemas
``bronze``/``silver``/``gold`` themselves are created by ``scripts/init-db.sql``
(architecture.md §3); these tables live inside them.

Table/column conventions follow architecture.md §3:
* table names are ``snake_case``, singular per entity;
* bronze/silver rows carry ``execution_id`` (logical FK to the run) and
  ``captured_at`` (UTC timestamp);
* nothing is ever deleted (indefinite retention; no purge job).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Index,
    MetaData,
    Numeric,
    Table,
    Text,
    Time,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

# Money is stored as NUMERIC(12, 2): exact decimal, never float. 12/2 covers any
# realistic fare (up to 9_999_999_999.99) while forcing 2-decimal cents.
_PRICE = Numeric(12, 2)

metadata = MetaData()

# ── Bronze ────────────────────────────────────────────────────────────────────
# Raw network payload intercepted from Gol, stored as-is plus run metadata.
# Append-only, never edited (architecture.md §3). ``payload`` is NULL and
# ``error_message`` is set when the extraction failed for the run.
raw_search_response = Table(
    "raw_search_response",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("execution_id", UUID(as_uuid=True), nullable=False),
    Column("route_origin", Text, nullable=False),
    Column("route_destination", Text, nullable=False),
    Column("departure_date", Date, nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("success", Boolean, nullable=False),
    Column("payload", JSONB, nullable=True),
    Column("error_message", Text, nullable=True),
    Index("ix_raw_search_response_execution_id", "execution_id"),
    schema="bronze",
)

# ── Silver ─────────────────────────────────────────────────────────────────────
# Normalized flights derived from bronze: typed price (Decimal), typed date/time.
# ``flight_id`` is the denormalized deduplication key (Flight.flight_id) so gold
# history can be joined/derived without re-parsing.
flight = Table(
    "flight",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("execution_id", UUID(as_uuid=True), nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("route_origin", Text, nullable=False),
    Column("route_destination", Text, nullable=False),
    Column("departure_date", Date, nullable=False),
    Column("carrier", Text, nullable=False),
    Column("flight_number", Text, nullable=False),
    Column("departure_time", Time(timezone=False), nullable=False),
    Column("price", _PRICE, nullable=False),
    Column("currency", Text, nullable=False),
    Column("flight_id", Text, nullable=False),
    Index("ix_flight_execution_id", "execution_id"),
    Index("ix_flight_flight_id", "flight_id"),
    schema="silver",
)

# ── Gold ───────────────────────────────────────────────────────────────────────
# Append-only history of alerts effectively sent (the "Último preço alertado"
# concept). Each row is one Alert event. The current "last alerted price" for a
# flight is the most recent row (max ``alerted_at``) per ``flight_id`` — this is
# what ``GoldRepository.last_alerted_prices`` derives for the dedup rule.
flight_alert = Table(
    "flight_alert",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("execution_id", UUID(as_uuid=True), nullable=False),
    Column("flight_id", Text, nullable=False),
    Column("price", _PRICE, nullable=False),
    Column("currency", Text, nullable=False),
    Column("alerted_at", DateTime(timezone=True), nullable=False),
    Index("ix_flight_alert_flight_id_alerted_at", "flight_id", "alerted_at"),
    schema="gold",
)
