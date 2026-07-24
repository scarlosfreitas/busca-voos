"""Database connection/engine wiring for the persistence layer.

Holds the SQLAlchemy Engine and the connection-string assembly. Per
``docs/standards/architecture.md`` §5 and §7:

* no credential or connection string is hardcoded — everything comes from
  environment variables;
* the app never targets ``localhost``; the default host is the docker-compose
  service name ``postgres``.

Only the *contract* lives here. Bodies raising :class:`NotImplementedError` are
to be implemented by dev-runner; the assembly logic in :func:`build_database_url`
is fully specified by its unit tests.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.engine import URL

# SQLAlchemy driver token for psycopg 3 (the project's Postgres driver).
DRIVER = "postgresql+psycopg"

# Default host is the docker-compose service name (architecture.md §7), never
# ``localhost``. Default port matches the postgres service.
DEFAULT_HOST = "postgres"
DEFAULT_PORT = "5432"


def build_database_url() -> str:
    """Assemble the SQLAlchemy connection URL from the environment.

    Contract (fully specified by ``test/persistence/test_db.py``):

    * If ``DATABASE_URL`` is set and non-empty, return it verbatim (full
      override, e.g. for a managed/secret-manager URL in production).
    * Otherwise assemble ``{DRIVER}://{user}:{password}@{host}:{port}/{db}``
      from environment variables:

      - required: ``POSTGRES_USER``, ``POSTGRES_PASSWORD``, ``POSTGRES_DB``;
      - optional: ``POSTGRES_HOST`` (default :data:`DEFAULT_HOST`),
        ``POSTGRES_PORT`` (default :data:`DEFAULT_PORT`).

    * If any required variable is missing/empty, raise :class:`RuntimeError`
      naming the missing variable(s) — fail fast, never silently target a
      default database.

    Implementation note for dev-runner: build the URL with
    :meth:`sqlalchemy.engine.URL.create` so special characters in the password
    are escaped correctly, then render it. For simple credentials (as used in
    the tests) the rendered string equals the plain URL above.
    """
    override = os.environ.get("DATABASE_URL")
    if override:
        return override

    required = {
        "POSTGRES_USER": os.environ.get("POSTGRES_USER"),
        "POSTGRES_PASSWORD": os.environ.get("POSTGRES_PASSWORD"),
        "POSTGRES_DB": os.environ.get("POSTGRES_DB"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            f"Missing required environment variable(s): {', '.join(missing)}"
        )

    host = os.environ.get("POSTGRES_HOST") or DEFAULT_HOST
    port = os.environ.get("POSTGRES_PORT") or DEFAULT_PORT

    url = URL.create(
        DRIVER,
        username=required["POSTGRES_USER"],
        password=required["POSTGRES_PASSWORD"],
        host=host,
        port=int(port),
        database=required["POSTGRES_DB"],
    )
    return url.render_as_string(hide_password=False)


_engine: Engine | None = None


def get_engine() -> Engine:
    """Return the process-wide singleton :class:`~sqlalchemy.Engine`.

    Contract: lazily create the Engine from :func:`build_database_url` on first
    call and cache it at module level (subsequent calls return the same object).
    Uses ``future=True`` semantics (SQLAlchemy 2.0). Connection pooling defaults
    are acceptable for a daily batch job — no custom pool sizing required.
    """
    global _engine
    if _engine is None:
        _engine = create_engine(build_database_url(), future=True)
    return _engine


@contextmanager
def connection_scope() -> Generator[Connection, None, None]:
    """Return a context manager yielding a transactional Connection.

    Contract: ``with connection_scope() as conn: ...`` opens a connection from
    :func:`get_engine` inside a transaction (``engine.begin()`` semantics) that
    commits on clean exit and rolls back on exception. Repositories operate on
    the yielded :class:`~sqlalchemy.Connection`.
    """
    with get_engine().begin() as conn:
        yield conn
