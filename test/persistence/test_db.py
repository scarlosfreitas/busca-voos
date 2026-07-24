"""Unit tests for connection-URL assembly (persistence.db.build_database_url).

Pure logic: no database is touched. These pin the contract that architecture.md
§5/§7 impose — URL built from env vars, docker service name as default host, no
hardcoded localhost, fail-fast on missing required variables, ``DATABASE_URL``
as a full override.
"""

from __future__ import annotations

import pytest

from persistence.db import DEFAULT_HOST, DEFAULT_PORT, DRIVER, build_database_url

_REQUIRED = {
    "POSTGRES_USER": "u",
    "POSTGRES_PASSWORD": "p",
    "POSTGRES_DB": "d",
}


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for key, value in _REQUIRED.items():
        monkeypatch.setenv(key, value)


class TestBuildDatabaseUrl:
    def test_assembles_from_components(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _set_required(monkeypatch)
        monkeypatch.setenv("POSTGRES_HOST", "postgres")
        monkeypatch.setenv("POSTGRES_PORT", "5432")
        assert build_database_url() == f"{DRIVER}://u:p@postgres:5432/d"

    def test_defaults_to_docker_service_host_and_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No POSTGRES_HOST/POSTGRES_PORT -> falls back to the compose service name,
        # never localhost (architecture.md §7).
        _set_required(monkeypatch)
        monkeypatch.delenv("POSTGRES_HOST", raising=False)
        monkeypatch.delenv("POSTGRES_PORT", raising=False)
        assert build_database_url() == f"{DRIVER}://u:p@{DEFAULT_HOST}:{DEFAULT_PORT}/d"

    def test_never_targets_localhost_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_required(monkeypatch)
        monkeypatch.delenv("POSTGRES_HOST", raising=False)
        assert "localhost" not in build_database_url()
        assert "127.0.0.1" not in build_database_url()

    def test_database_url_env_overrides_components(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _set_required(monkeypatch)
        override = "postgresql+psycopg://override:pw@managed-host:6543/prod"
        monkeypatch.setenv("DATABASE_URL", override)
        assert build_database_url() == override

    @pytest.mark.parametrize("missing", sorted(_REQUIRED))
    def test_missing_required_variable_raises(
        self, monkeypatch: pytest.MonkeyPatch, missing: str
    ) -> None:
        _set_required(monkeypatch)
        monkeypatch.delenv(missing, raising=False)
        # ``match`` pins that the error names the offending variable — this also
        # keeps the test failing now (NotImplementedError, subclass of
        # RuntimeError, carries no message) until the contract is implemented.
        with pytest.raises(RuntimeError, match=missing):
            build_database_url()
