"""Deterministic, offline suitability reviewer.

Used automatically when no OPENAI_API_KEY is configured, so the full
human-in-the-loop pipeline can be demonstrated — and tested — with zero
credentials and zero network access.

This is NOT a model. It is a small rule table that produces the same decision
shapes a model would, so the policy engine, audit trail, and escalation queue
can all be exercised end to end. Reviews it produces are stamped
`model_version="stub-v1"` so stub output is never mistaken for model output in
the audit trail or in the drift metrics.

The rules are chosen to cover every branch of the policy engine:
  * high-confidence APPROVE  -> AUTO_APPROVED
  * borderline APPROVE       -> ESCALATED (confidence below threshold)
  * ESCALATE                 -> ESCALATED
  * BLOCK                    -> ESCALATED (never auto-rejected)
"""
from app.schemas.ai_output import AIReviewOutput

MODEL_VERSION = "stub-v1"

# Product risk buckets, matched against the free-text investment_choice.
HIGH_RISK_TERMS = (
    "growth", "crypto", "aggressive", "emerging", "equit",
    "option", "derivative", "leverage", "margin", "speculative",
)
LOW_RISK_TERMS = (
    "bond", "gic", "treasury", "money market", "savings",
    "fixed income", "index", "balanced",
)

LOW_TOLERANCE = ("low", "conservative", "cautious")
HIGH_TOLERANCE = ("high", "aggressive", "growth")


def _matches(haystack: str, terms: tuple[str, ...]) -> bool:
    lowered = (haystack or "").lower()
    return any(term in lowered for term in terms)


class StubProvider:
    """Rule-based stand-in for the LLM reviewer."""

    model_version = MODEL_VERSION

    async def review(self, account) -> AIReviewOutput:
        age = account.age
        income = float(account.income)
        net_worth = float(account.net_worth)
        horizon = account.investment_horizon
        tolerance = (account.risk_tolerance or "").lower()

        high_risk_product = _matches(account.investment_choice, HIGH_RISK_TERMS)
        low_risk_product = _matches(account.investment_choice, LOW_RISK_TERMS)
        low_tolerance = any(t in tolerance for t in LOW_TOLERANCE)
        high_tolerance = any(t in tolerance for t in HIGH_TOLERANCE)

        # ── Rule 1: regulatory red flags → BLOCK (policy will still escalate) ──
        if net_worth <= 0:
            return AIReviewOutput(
                suitability_score=5,
                confidence=0.97,
                decision="BLOCK",
                reasoning=(
                    "Reported net worth is zero or negative, which fails the minimum "
                    "financial-capacity requirement for any investment account."
                ),
                justification_note="Reported net worth does not meet the minimum requirement for this account type.",
            )

        if age >= 70 and high_risk_product and horizon <= 3:
            return AIReviewOutput(
                suitability_score=12,
                confidence=0.94,
                decision="BLOCK",
                reasoning=(
                    f"Client is {age} with a {horizon}-year horizon in a high-risk product. "
                    "Concentration of speculative exposure at this age and horizon is a "
                    "recognised suitability red flag."
                ),
                justification_note="The selected strategy is not appropriate for the stated age and time horizon.",
            )

        # ── Rule 2: internal contradictions → ESCALATE ────────────────────────
        if low_tolerance and high_risk_product:
            return AIReviewOutput(
                suitability_score=38,
                confidence=0.88,
                decision="ESCALATE",
                reasoning=(
                    f"Stated risk tolerance is '{account.risk_tolerance}' but the selected product "
                    f"('{account.investment_choice}') carries high volatility. This contradiction "
                    "needs a human to confirm the client understands the mismatch."
                ),
                justification_note="Your selected strategy carries more risk than your stated tolerance suggests.",
            )

        if high_risk_product and horizon <= 2:
            return AIReviewOutput(
                suitability_score=41,
                confidence=0.86,
                decision="ESCALATE",
                reasoning=(
                    f"A {horizon}-year horizon leaves no room to recover from a drawdown in a "
                    "high-risk product. Short-horizon growth allocations require human sign-off."
                ),
                justification_note="Your time horizon may be too short for the selected strategy.",
            )

        if income > 0 and net_worth < income * 0.10 and high_risk_product:
            return AIReviewOutput(
                suitability_score=44,
                confidence=0.83,
                decision="ESCALATE",
                reasoning=(
                    "Net worth is disproportionately low relative to stated income, suggesting "
                    "limited loss-absorption capacity for a high-risk allocation."
                ),
                justification_note="Your reported assets suggest limited capacity to absorb losses in this strategy.",
            )

        # ── Rule 3: plausible but not clear-cut → low-confidence APPROVE ──────
        # Falls below the 0.90 policy threshold, so it still reaches a human.
        if high_risk_product and not high_tolerance:
            return AIReviewOutput(
                suitability_score=63,
                confidence=0.74,
                decision="APPROVE",
                reasoning=(
                    "No direct contradiction found, but a high-risk product without an explicitly "
                    "high risk tolerance leaves the assessment inconclusive."
                ),
                justification_note="Your profile is broadly consistent, with some ambiguity worth confirming.",
            )

        # ── Rule 4: consistent profile → high-confidence APPROVE ──────────────
        aligned = (low_tolerance and low_risk_product) or (high_tolerance and high_risk_product)
        score = 88 if aligned else 79
        return AIReviewOutput(
            suitability_score=score,
            confidence=0.95 if aligned else 0.92,
            decision="APPROVE",
            reasoning=(
                f"Profile is internally consistent: risk tolerance '{account.risk_tolerance}' aligns "
                f"with '{account.investment_choice}' over a {horizon}-year horizon, and reported "
                "financial capacity supports the allocation."
            ),
            justification_note="Your investment selection aligns with your stated risk tolerance and time horizon.",
        )
