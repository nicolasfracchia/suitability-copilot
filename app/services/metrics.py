"""
In-memory metrics counters for the review pipeline.

These are intentionally simple — no Prometheus, no external dependency.
They measure themselves so production systems can show they're alive.

Counter semantics:
  total_reviews   — every submitted review (regardless of outcome)
  auto_approved   — AI+Policy both agreed: AUTO_APPROVED
  escalated       — sent to human review queue
  overridden      — human changed the effective decision post-review
  llm_failures    — LLM pipeline hit the fail-safe path
"""
import threading
from typing import Any

_lock = threading.Lock()

_counters: dict[str, int] = {
    "total_reviews": 0,
    "auto_approved": 0,
    "escalated": 0,
    "overridden": 0,
    "llm_failures": 0,
}


def increment(name: str) -> None:
    """Thread-safe counter increment. Silently ignores unknown counter names."""
    with _lock:
        if name in _counters:
            _counters[name] += 1


def get_all() -> dict[str, Any]:
    """Return a snapshot of all counters."""
    with _lock:
        return dict(_counters)


def reset_all() -> None:
    """Reset all counters to zero. Intended for test isolation only."""
    with _lock:
        for key in _counters:
            _counters[key] = 0
