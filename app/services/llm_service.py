import asyncio
import logging
import weakref

from app.schemas.ai_output import AIReviewOutput
from app.services.providers import get_provider

logger = logging.getLogger(__name__)

# Ceiling on evaluations running concurrently inside a single event loop.
# Note this is not the primary scaling control: the Celery worker runs one
# asyncio.run() per task, so cross-task concurrency is governed by the worker's
# own concurrency/prefetch settings (see app/worker/celery.py). This semaphore
# guards the case where several evaluations share one loop.
MAX_CONCURRENT_EVALUATIONS = 5

# Keyed by event loop: asyncio primitives bind to the first loop that awaits
# them, and every Celery task creates a fresh loop via asyncio.run(). A single
# module-level semaphore would eventually raise "bound to a different event
# loop" once it saw contention.
_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def _get_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_EVALUATIONS)
        _semaphores[loop] = semaphore
    return semaphore


class LLMService:
    """
    Facade over the configured review provider.

    Design contract:
      - evaluate() ALWAYS returns an AIReviewOutput.
      - On ANY failure (timeout, bad JSON, validation error, provider crash) it
        returns a fail-safe ESCALATE result with confidence=0.0, so the policy
        engine can never auto-approve under uncertainty.

    The fail-safe lives here rather than in the providers so that adding a
    provider cannot introduce a path that bypasses it.
    """

    def __init__(self, provider=None):
        self._provider = provider if provider is not None else get_provider()

    @property
    def model_version(self) -> str:
        """Identifier of the reviewer that actually produced the assessment."""
        return self._provider.model_version

    async def evaluate(self, account) -> AIReviewOutput:
        async with _get_semaphore():
            try:
                return await self._provider.review(account)
            except Exception as exc:
                logger.error(
                    "Review evaluation failed for account %s via %s — applying fail-safe escalation: %s",
                    getattr(account, "id", "unknown"),
                    self.model_version,
                    exc,
                )
                return self._fail_safe()

    def _fail_safe(self) -> AIReviewOutput:
        """
        Returned whenever the evaluation pipeline raises.
        Confidence=0.0 guarantees the policy engine will ESCALATE.
        Never auto-approve on model uncertainty.
        """
        return AIReviewOutput(
            suitability_score=0,
            confidence=0.0,
            decision="ESCALATE",
            reasoning=(
                "Automated evaluation failed — defaulting to manual escalation. "
                "This is a fail-safe response; no automated decision was made."
            ),
            justification_note=(
                "Automated assessment unavailable. A human reviewer will evaluate this profile."
            ),
        )
