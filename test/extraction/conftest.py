"""Shared fixtures for the extraction test suite.

Two kinds of tests live here, mirroring the persistence convention:

* **Unit tests** for the pure logic (payload parsing, config-from-env, delay
  picking) — no browser, always run. They fail with ``NotImplementedError`` until
  dev-runner implements the bodies.
* **Integration test** for the browser-driving capture — automatically *skipped*
  unless explicitly opted-in *and* Playwright is available. Real captures hit the
  live Gol site over the network, so they never run by default (architecture.md
  §8 — integração testada separadamente; qa.md §8 — recurso opcional pulável).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    """Load a synthetic payload fixture (``fixtures/{name}.json``)."""
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def sample_payload() -> Any:
    """Valid Gol availability payload with two flights."""
    return load_fixture("gol_response_sample")


@pytest.fixture
def empty_payload() -> Any:
    """Well-formed payload with no availability (empty ``flights``)."""
    return load_fixture("gol_response_empty")


@pytest.fixture
def malformed_payload() -> Any:
    """Correct container, but a flight record missing the mandatory ``fare``."""
    return load_fixture("gol_response_malformed")


@pytest.fixture
def blocked_payload() -> Any:
    """Non-API response (WAF/access-denied envelope, no ``trips`` key)."""
    return load_fixture("gol_response_blocked")
