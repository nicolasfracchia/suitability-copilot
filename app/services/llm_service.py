import logging
import asyncio
from app.core.config import settings
from app.schemas.ai_output import AIReviewOutput

logger = logging.getLogger(__name__)

# Required at module-level to prevent MagicMock attribute error in tests.
MODEL_VERSION = "gpt-4o"

# Limit concurrent LLM calls to prevent rate limits or resource exhaustion.
llm_semaphore = asyncio.Semaphore(5)

class LLMService:
    """
    Wraps an OpenAI chat completion call with prompt engineering,
    strict JSON validation, and a fail-safe fallback.
    Now fully asynchronous with semaphore-based rate limiting.

    Design contract:
      - evaluate() ALWAYS returns an AIReviewOutput.
      - On ANY failure (timeout, bad JSON, validation error), it returns
        a fail-safe ESCALATE result with confidence=0.0 so that the
        policy engine never auto-approves under uncertainty.
    """

    MODEL_VERSION = MODEL_VERSION 

    def __init__(self):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def evaluate(self, account) -> AIReviewOutput:
        async with llm_semaphore:
            try:
                messages = self._build_prompt(account)
                raw = await self._call_model(messages)
                return self._parse_and_validate(raw)
            except Exception as exc:
                logger.error(
                    "LLM evaluation failed for account %s — applying fail-safe escalation: %s",
                    getattr(account, "id", "unknown"),
                    exc,
                )
                return self._fail_safe()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, account) -> list[dict]:
        system_prompt = (
            "You are a licensed financial suitability analyst AI. "
            "Your task is to evaluate a client's investment profile and produce a suitability assessment.\n\n"
            "You MUST respond with a single valid JSON object only — no prose, no markdown, no code fences.\n"
            "The JSON must conform exactly to this schema:\n"
            '{"suitability_score": <integer 0-100>, '
            '"confidence": <float 0.0-1.0>, '
            '"decision": <"APPROVE"|"ESCALATE"|"BLOCK">, '
            '"reasoning": <string explaining the assessment>, '
            '"justification_note": <short client-facing summary>}\n\n'
            "Decision guidelines:\n"
            "  APPROVE   — profile is internally consistent and suitable.\n"
            "  ESCALATE  — profile has concerns that require human review.\n"
            "  BLOCK     — profile contains a clear regulatory red flag.\n\n"
            "Example response:\n"
            '{"suitability_score": 72, "confidence": 0.91, "decision": "APPROVE", '
            '"reasoning": "Client demonstrates a balanced risk profile consistent with the selected strategy.", '
            '"justification_note": "Risk tolerance aligns with the chosen investment vehicle."}'
        )

        user_prompt = (
            "Evaluate the following client profile:\n"
            f"  Age:                {account.age}\n"
            f"  Annual income:      ${float(account.income):,.2f}\n"
            f"  Net worth:          ${float(account.net_worth):,.2f}\n"
            f"  Risk tolerance:     {account.risk_tolerance}\n"
            f"  Investment choice:  {account.investment_choice}\n"
            f"  Investment horizon: {account.investment_horizon} years\n"
            f"  Notes:              {account.notes or 'None'}\n\n"
            "Return ONLY the JSON object."
        )

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    async def _call_model(self, messages: list[dict]) -> str:
        # Added strict 10s timeout to model calls as per production hardening
        response = await self._client.chat.completions.create(
            model=self.MODEL_VERSION,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=10,
        )
        return response.choices[0].message.content

    def _parse_and_validate(self, raw: str) -> AIReviewOutput:
        """Raises pydantic.ValidationError if the model output is non-conforming."""
        return AIReviewOutput.model_validate_json(raw)

    def _fail_safe(self) -> AIReviewOutput:
        """
        Returned whenever the LLM pipeline raises any exception.
        Confidence=0.0 guarantees the policy engine will ESCALATE.
        Never auto-approve on model uncertainty.
        """
        return AIReviewOutput(
            suitability_score=0,
            confidence=0.0,
            decision="ESCALATE",
            reasoning=(
                "LLM evaluation failed — defaulting to manual escalation. "
                "This is a fail-safe response; no automated decision was made."
            ),
            justification_note=(
                "Automated assessment unavailable. A human reviewer will evaluate this profile."
            ),
        )
