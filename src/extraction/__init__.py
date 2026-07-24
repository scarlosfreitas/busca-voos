"""Extraction layer: Playwright + stealth scraping of the Gol search via network
interception (no HTML parsing).

Public surface re-exported for the ``orchestration`` layer. The pure parser and
config helpers are unit-tested with synthetic fixtures; the browser-driving
functions are integration-only.
"""

from __future__ import annotations

from .browser import (
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    DEFAULT_USER_AGENT,
    BrowserConfig,
    ProxyConfig,
    human_delay,
    pick_delay_seconds,
    stealth_page_session,
)
from .errors import (
    BlockedError,
    ExtractionError,
    ExtractionTimeoutError,
    MalformedPayloadError,
)
from .gol import (
    MVP_SEARCH_PARAMS,
    CapturedFlight,
    GolCaptureResult,
    GolSearchParams,
    capture_gol_search,
    parse_gol_response,
)

__all__ = [
    "DEFAULT_NAVIGATION_TIMEOUT_MS",
    "DEFAULT_USER_AGENT",
    "MVP_SEARCH_PARAMS",
    "BlockedError",
    "BrowserConfig",
    "CapturedFlight",
    "ExtractionError",
    "ExtractionTimeoutError",
    "GolCaptureResult",
    "GolSearchParams",
    "MalformedPayloadError",
    "ProxyConfig",
    "capture_gol_search",
    "human_delay",
    "parse_gol_response",
    "pick_delay_seconds",
    "stealth_page_session",
]
