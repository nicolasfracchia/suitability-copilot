"""OpenAI-backed suitability reviewer.

Prompt construction, the model call, and strict schema validation live here.
Anything non-conforming raises, and LLMService converts that into a fail-safe
escalation — the model is never trusted to shape the final record.
"""
import logging

from app.core.config import settings
from app.schemas.ai_output import AIReviewOutput

logger = logging.getLogger(__name__)

# Hard ceiling on a single model call. On breach, the fail-safe escalates to a
# human rather than leaving the review in limbo.
REQUEST_TIMEOUT_SECONDS = 10


class OpenAIProvider:
    """Calls an OpenAI chat model and validates the reply against AIReviewOutput."""

    def __init__(self, model: str | None = None, api_key: str | None = None):
        from openai import AsyncOpenAI

        self.model_version = model or settings.OPENAI_MODEL
        self._client = AsyncOpenAI(api_key=api_key or settings.OPENAI_API_KEY)

    async def review(self, account) -> AIReviewOutput:
        messages = self._build_prompt(account)
        raw = await self._call_model(messages)
        return AIReviewOutput.model_validate_json(raw)

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
        response = await self._client.chat.completions.create(
            model=self.model_version,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return response.choices[0].message.content
