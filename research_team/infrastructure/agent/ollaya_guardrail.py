"""Ollaya-backed safety guardrail for autonomous tool executions."""

import logging
from typing import Any

from research_team.infrastructure.decision.ollaya_client import OllayaDecisionClient

logger = logging.getLogger(__name__)

_GUARDRAIL_QUESTION = {
    "action": {
        "type": "choice",
        "instructions": (
            "Evaluate whether this automated tool call poses security, privacy, or "
            "runaway risk that requires pausing for human approval."
        ),
        "criteria": {
            "allow": (
                "Safe, routine research or file inspection on legitimate public domains "
                "or internal workspace"
            ),
            "block": (
                "Suspicious, potentially destructive, sensitive credential access, "
                "or unverified high-risk external URL"
            ),
        },
    }
}


class OllayaToolGuardrail:
    """Evaluates tool call safety in milliseconds before allowing autonomous execution."""

    def __init__(self, client: OllayaDecisionClient, *, model: str = "laya") -> None:
        self._client = client
        self._model = model

    async def should_intercept(
        self, tool_name: str, tool_args: dict[str, Any], context_goal: str = ""
    ) -> bool:
        """Return True if the tool call should be intercepted for human approval."""
        state = (
            f"Goal: {context_goal or 'Autonomous Research'}\n"
            f"Tool: {tool_name}\n"
            f"Arguments: {tool_args}"
        )
        try:
            res = await self._client.decide_raw(
                model=self._model,
                state=state,
                questions=_GUARDRAIL_QUESTION,
            )
            ans = res.get("answers", {}).get("action", {})
            choice = ans.get("choice", "allow")
            prob_block = float(ans.get("probabilities", {}).get("block", 0.0))

            # Intercept if model flags as block with high confidence
            return (choice == "block") or (prob_block >= 0.75)
        except Exception:
            # On decision client error, fail open or closed depending on tool
            logger.warning("Ollaya guardrail check failed", exc_info=True)
            return False
