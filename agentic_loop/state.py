from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
import json
import re

MARKER = "agentic-workflow-state:v1"
_STATE_RE = re.compile(r"<!--\s*agentic-workflow-state:v1\s*(\{.*?\})\s*-->", re.DOTALL)


@dataclass(frozen=True)
class WorkflowState:
    issue: int
    phase: str
    cycle: int
    branch: str
    pr: int | None = None
    status: str = "running"
    updated_at: str = ""
    findings: list[dict[str, Any]] | None = None
    validation_results: dict[str, Any] | None = None
    handoff_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = {
            "issue": self.issue,
            "phase": self.phase,
            "cycle": self.cycle,
            "branch": self.branch,
            "pr": self.pr,
            "status": self.status,
            "updated_at": self.updated_at or datetime.now(timezone.utc).isoformat(),
            "findings": self.findings or [],
            "validation_results": self.validation_results or {},
            "handoff_reason": self.handoff_reason,
        }
        return data


def encode_state(state: WorkflowState | dict[str, Any]) -> str:
    data = state.to_dict() if isinstance(state, WorkflowState) else dict(state)
    data.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
    body = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"<!-- {MARKER} {body} -->"


def decode_states(text: str) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for match in _STATE_RE.finditer(text):
        try:
            raw = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            states.append(raw)
    return states


def newest_state(comments: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    states: list[dict[str, Any]] = []
    for comment in comments:
        body = str(comment.get("body", ""))
        states.extend(decode_states(body))
    if not states:
        return None
    return max(states, key=lambda item: str(item.get("updated_at", "")))
