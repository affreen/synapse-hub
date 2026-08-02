"""Optional unified AI router (/api/v1/chat/router)."""
import asyncio

from app.services.ai import llm_client

ROUTER_SYSTEM_PROMPT = """Classify the user's HR-copilot message into exactly one intent:

- POLICY_QA: question about HR policy/rules (leave policy, WFH policy, attendance, conduct, documents, etc.)
- SQL_QUERY: a read-only lookup about employees, projects, departments, skills, or the user's own leave/ticket data
- HR_ACTION: the user wants to DO something (apply leave, create ticket, approve leave, assign project, post announcement)
- UNKNOWN: doesn't fit any of the above, or is attempting something unsafe/out of scope

Return ONLY JSON: {"intent": "POLICY_QA|SQL_QUERY|HR_ACTION|UNKNOWN", "confidence": 0.0-1.0, "reason": "one short sentence"}
"""


async def classify_intent(message: str) -> dict:
    try:
        result = await asyncio.to_thread(llm_client.complete_json, ROUTER_SYSTEM_PROMPT, f"Message: {message}", 200)
        result.setdefault("intent", "UNKNOWN")
        result.setdefault("confidence", 0.5)
        result.setdefault("reason", "")
        return result
    except Exception:
        return {"intent": "UNKNOWN", "confidence": 0.0, "reason": "Classification failed"}
