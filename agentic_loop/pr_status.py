from __future__ import annotations

from typing import Any
import re

START_MARKER = "<!-- agentic-loop-status:start -->"
END_MARKER = "<!-- agentic-loop-status:end -->"
_SECTION_RE = re.compile(
    rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}",
    re.DOTALL,
)


def upsert_status_section(body: str, status: dict[str, Any]) -> str:
    section = render_status_section(status)
    if _SECTION_RE.search(body):
        return _SECTION_RE.sub(section, body, count=1)
    if body.strip():
        return f"{body.rstrip()}\n\n{section}"
    return section


def render_status_section(status: dict[str, Any]) -> str:
    validation = _validation_status(status.get("validation_results"))
    handoff = str(status.get("handoff_status") or "not handed off")
    lines = [
        START_MARKER,
        "## Agentic Loop Status",
        "",
        f"- Source issue: #{status.get('issue')}",
        f"- Current phase: {status.get('phase', 'unknown')}",
        f"- Branch: `{status.get('branch', '')}`",
        f"- Plan summary: {status.get('plan_summary') or 'not available'}",
        f"- Validation status: {validation}",
        f"- Latest review summary: {status.get('review_summary') or 'not reviewed yet'}",
        f"- Remediation count/cycle: {status.get('remediation_count', 0)}/{status.get('cycle', 0)}",
        f"- Handoff status: {handoff}",
        "- Automation will not merge.",
        END_MARKER,
    ]
    return "\n".join(lines)


def extract_status_value(body: str, label: str) -> str:
    match = _SECTION_RE.search(body)
    if not match:
        return ""
    prefix = f"- {label}: "
    for line in match.group(0).splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _validation_status(results: Any) -> str:
    if not isinstance(results, dict) or results.get("skipped"):
        return "skipped"
    return "passed" if results.get("passed") else "failed"
