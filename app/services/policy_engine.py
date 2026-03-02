from app.schemas.ai_output import AIReviewOutput

# Minimum confidence required for automatic approval
CONFIDENCE_THRESHOLD = 0.90


def apply_policy(ai_result: AIReviewOutput) -> str:
    """
    Translates an AI recommendation into a final operational decision.

    AI suggests. Policy decides. This separation is intentional.

    Rules (applied in priority order):
      1. BLOCK  → always ESCALATED  — never auto-block without human sign-off.
      2. High-confidence APPROVE    → AUTO_APPROVED.
      3. Everything else            → ESCALATED.

    Returns one of: "AUTO_APPROVED", "ESCALATED"
    """
    if ai_result.decision == "BLOCK":
        return "ESCALATED"

    if ai_result.decision == "APPROVE" and ai_result.confidence >= CONFIDENCE_THRESHOLD:
        return "AUTO_APPROVED"

    return "ESCALATED"
