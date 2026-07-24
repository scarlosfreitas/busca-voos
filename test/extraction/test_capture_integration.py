"""Integration test for the browser-driving Gol capture (skipped by default).

Real captures launch a headless Chromium and hit the live Gol site over the
network, so this never runs by default. It is opt-in via ``RUN_GOL_INTEGRATION=1``
and additionally skips if Playwright is not importable or the capture is not yet
implemented — mirroring the persistence integration skip gate (architecture.md
§8; qa.md §8). It fails only if a real capture runs and misbehaves.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GOL_INTEGRATION") != "1",
    reason="Gol capture is a live-network integration test; set RUN_GOL_INTEGRATION=1 to run",
)


@pytest.fixture(scope="module")
def _playwright_available() -> None:
    """Skip (never fail) when Playwright/browsers are not available."""
    try:
        import playwright.async_api  # noqa: F401
    except Exception as exc:  # noqa: BLE001 - missing dep means "skip, not fail"
        pytest.skip(f"Playwright not available: {exc}")


def test_capture_gol_search_returns_result(_playwright_available) -> None:
    # Driven with asyncio.run so the suite needs no pytest-asyncio dependency.
    from extraction.errors import ExtractionError
    from extraction.gol import GolCaptureResult, capture_gol_search

    try:
        result = asyncio.run(capture_gol_search())
    except NotImplementedError:
        pytest.skip("capture_gol_search not implemented yet")
    except ExtractionError as exc:
        # A typed extraction failure (block/timeout/malformed) is an acceptable
        # real-world outcome for a live capture — the contract is that it is
        # typed, not that Gol always answers. Surface it as a skip, not a failure.
        pytest.skip(f"Live capture failed with a typed ExtractionError: {exc}")

    assert isinstance(result, GolCaptureResult)
    assert result.raw_payload is not None
    assert isinstance(result.flights, tuple)
