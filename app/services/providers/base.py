"""Provider contract for suitability evaluation.

A provider turns an Account into a validated AIReviewOutput. It is allowed to
raise — LLMService owns the fail-safe. Keeping the failure policy in one place
means a new provider cannot accidentally introduce a path that auto-approves
under uncertainty.
"""
from typing import Protocol, runtime_checkable

from app.schemas.ai_output import AIReviewOutput


@runtime_checkable
class ReviewProvider(Protocol):
    #: Stamped onto every review this provider produces, and onto the
    #: AI_EVALUATED audit row. Must uniquely identify the decision-maker.
    model_version: str

    async def review(self, account) -> AIReviewOutput:
        """Evaluate an account. May raise; the caller applies the fail-safe."""
        ...
