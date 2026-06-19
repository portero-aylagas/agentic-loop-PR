from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TraceRecorder:
    issue: int
    branch: str
    artifact_path: str
    enabled: bool = True

    def append(self, repo_root: Path, event: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = repo_root / self.artifact_path
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else _header(self.issue, self.branch)
        path.write_text(existing.rstrip() + "\n\n" + render_trace_event(event).rstrip() + "\n", encoding="utf-8")


def trace_artifact_path(issue: int, artifact_dir: str) -> str:
    clean = artifact_dir.strip().strip("/\\").replace("\\", "/")
    return f"{clean}/issue-{issue}.md"


def render_trace_event(event: dict[str, Any]) -> str:
    role = str(event.get("role", "orchestrator"))
    timestamp = str(event.get("timestamp") or datetime.now(timezone.utc).isoformat())
    if role == "planner":
        return _render_planner(event, timestamp)
    if role == "implementer":
        return _render_file_role("Implementer", event, timestamp)
    if role == "remediator":
        return _render_file_role("Remediator", event, timestamp)
    if role == "validation":
        return _render_validation(event, timestamp)
    if role == "reviewer":
        return _render_review(event, timestamp)
    if role == "orchestrator":
        return _render_orchestrator(event, timestamp)
    return f"## {role.title()} - {timestamp}\n\n- Summary: {_text(event.get('summary'), 'not available')}"


def trace_issue_summary(events: list[dict[str, Any]]) -> str:
    if not events:
        return "No trace events were recorded before handoff."
    return "\n\n".join(render_trace_event(event).rstrip() for event in events)


def _header(issue: int, branch: str) -> str:
    return "\n".join([
        f"# Agentic Loop Trace for Issue #{issue}",
        "",
        f"- Branch: `{branch}`",
        "- Purpose: committed audit trail of agent decisions for human review.",
    ])


def _render_planner(event: dict[str, Any], timestamp: str) -> str:
    plan = _dict(event.get("plan"))
    lines = [
        f"## Planner - {timestamp}",
        "",
        f"- Summary: {_text(plan.get('summary'), 'not available')}",
        "",
        "### Steps",
    ]
    steps = plan.get("steps")
    if isinstance(steps, list) and steps:
        for index, step in enumerate(steps, start=1):
            item = _dict(step)
            lines.append(f"{index}. {_text(item.get('description'), 'not described')}")
            lines.append(f"   - Verify: {_text(item.get('verify'), 'not specified')}")
    else:
        lines.append("- Not provided.")
    lines.extend(["", "### Risks"])
    risks = plan.get("risks")
    if isinstance(risks, list) and risks:
        lines.extend(f"- {_text(risk, 'not specified')}" for risk in risks)
    else:
        lines.append("- None reported.")
    return "\n".join(lines)


def _render_file_role(title: str, event: dict[str, Any], timestamp: str) -> str:
    output = _dict(event.get("output"))
    lines = [
        f"## {title} - {timestamp}",
        "",
        f"- Summary: {_text(output.get('summary'), 'not available')}",
        f"- Commit message: `{_text(output.get('commit_message'), 'not available')}`",
        "",
        "### Files changed",
    ]
    files = output.get("files_changed") or output.get("changed_files")
    if isinstance(files, list) and files:
        lines.extend(f"- `{_text(path, 'unknown')}`" for path in files)
    else:
        lines.append("- None reported.")
    return "\n".join(lines)


def _render_validation(event: dict[str, Any], timestamp: str) -> str:
    results = _dict(event.get("results"))
    status = "skipped" if results.get("skipped") else "passed" if results.get("passed") else "failed"
    lines = [f"## Validation - {timestamp}", "", f"- Status: {status}", "", "### Commands"]
    commands = results.get("commands")
    if isinstance(commands, list) and commands:
        for command in commands:
            item = _dict(command)
            lines.append(f"- `{_text(item.get('command'), 'validation command')}` exited `{_text(item.get('exit_code'), 'unknown')}`")
            snippet = _failure_snippet(item)
            if snippet:
                lines.append(f"  - Output: `{snippet}`")
    else:
        lines.append("- No validation commands were configured.")
    return "\n".join(lines)


def _render_review(event: dict[str, Any], timestamp: str) -> str:
    review = _dict(event.get("review"))
    decision = _dict(event.get("decision"))
    lines = [
        f"## Reviewer - {timestamp}",
        "",
        f"- Cycle: {_text(event.get('cycle'), '0')}",
        f"- Review status: {_text(review.get('status'), 'unknown')}",
        f"- Summary: {_text(review.get('summary'), 'not available')}",
        f"- Policy decision: {_text(decision.get('kind'), 'unknown')}",
        f"- Decision reason: {_text(decision.get('reason'), 'not available')}",
        "",
        "### Findings",
    ]
    findings = review.get("findings")
    if isinstance(findings, list) and findings:
        for finding in findings:
            item = _dict(finding)
            path = _text(item.get("path"), "no path")
            severity = _text(item.get("severity"), "unknown")
            lines.append(f"- **{_text(item.get('title'), 'Finding')}** (`{path}`, {severity}): {_text(item.get('message'), '')}")
    else:
        lines.append("- None.")
    return "\n".join(lines)


def _render_orchestrator(event: dict[str, Any], timestamp: str) -> str:
    return "\n".join([
        f"## Orchestrator - {timestamp}",
        "",
        f"- Phase: {_text(event.get('phase'), 'unknown')}",
        f"- Handoff reason: {_text(event.get('reason'), 'not available')}",
    ])


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text or default


def _failure_snippet(command: dict[str, Any]) -> str:
    try:
        if int(command.get("exit_code", 0)) == 0:
            return ""
    except (TypeError, ValueError):
        pass
    text = _text(command.get("stderr") or command.get("stdout"), "")
    return text[:200]
