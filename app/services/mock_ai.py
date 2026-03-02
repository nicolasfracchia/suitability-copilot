def evaluate_account(account):
    # primitive deterministic mock logic
    mismatch = account.risk_tolerance.lower() == "low" and "growth" in account.investment_choice.lower()

    if mismatch:
        return {
            "suitability_score": 40,
            "confidence": 0.85,
            "decision": "ESCALATE",
            "reasoning": "Risk mismatch detected.",
            "justification_note": "Client selected high-growth strategy despite low risk tolerance.",
            "model_version": "mock-v1"
        }
    else:
        return {
            "suitability_score": 85,
            "confidence": 0.95,
            "decision": "APPROVE",
            "reasoning": "Profile consistent.",
            "justification_note": "Investment strategy aligned with stated tolerance.",
            "model_version": "mock-v1"
        }