"""Provider selection.

`LLM_PROVIDER` controls which reviewer backs the pipeline:
  auto    (default) — use OpenAI when an API key is present, otherwise the stub
  openai            — force OpenAI; fail loudly at startup if no key is set
  stub              — force the deterministic offline reviewer

'auto' is what makes `docker compose up --build` work on a bare clone: with no
key configured the stack still runs a complete, inspectable review pipeline.
"""
import logging

from app.core.config import settings
from app.services.providers.base import ReviewProvider
from app.services.providers.stub_provider import StubProvider

logger = logging.getLogger(__name__)


def get_provider() -> ReviewProvider:
    """Build the configured review provider."""
    choice = (settings.LLM_PROVIDER or "auto").strip().lower()
    has_key = bool(settings.OPENAI_API_KEY and settings.OPENAI_API_KEY.strip())

    if choice == "stub":
        return StubProvider()

    if choice == "openai":
        if not has_key:
            raise RuntimeError(
                "LLM_PROVIDER=openai but OPENAI_API_KEY is not set. "
                "Set a key, or use LLM_PROVIDER=auto to fall back to the stub reviewer."
            )
        from app.services.providers.openai_provider import OpenAIProvider

        return OpenAIProvider()

    if choice != "auto":
        raise RuntimeError(
            f"Unknown LLM_PROVIDER={choice!r}. Expected one of: auto, openai, stub."
        )

    if has_key:
        from app.services.providers.openai_provider import OpenAIProvider

        return OpenAIProvider()

    logger.warning(
        "No OPENAI_API_KEY configured — falling back to the deterministic stub reviewer. "
        "Reviews will be stamped model_version=%s.",
        StubProvider.model_version,
    )
    return StubProvider()


__all__ = ["ReviewProvider", "StubProvider", "get_provider"]
