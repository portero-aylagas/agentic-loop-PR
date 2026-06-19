from __future__ import annotations

AUTOMATED_COMMENT_FOOTER = "_Automated comment by agentic-loop PR._"

ROLE_DISPLAY = {
    "orchestrator": "\U0001f9e0 Orchestrator",
    "planner": "\U0001f9d1\u200d\U0001f4bc\U0001f4dd Planner",
    "implementer": "\U0001f9d1\u200d\U0001f4bb\U0001f6e0\ufe0f Implementer",
    "reviewer": "\U0001f575\ufe0f\U0001f50e Reviewer",
    "remediator": "\U0001f9d1\u200d\u2695\ufe0f\U0001f48a Remediator",
}


def role_display(role: str) -> str:
    return ROLE_DISPLAY.get(role, ROLE_DISPLAY["orchestrator"])


def automated_comment(role: str, body: str) -> str:
    return f"{role_display(role)}: {body}\n\n{AUTOMATED_COMMENT_FOOTER}"
