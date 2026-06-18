from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any, Iterable, Literal

DecisionKind = Literal["approved", "continue", "handoff"]


@dataclass(frozen=True)
class PolicyDecision:
    kind: DecisionKind
    reason: str


def protected_path_matches(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch(normalized, pattern.replace("\\", "/")) for pattern in patterns)


def decide_review(
    *,
    review: dict[str, Any],
    cycle: int,
    previous_findings: list[list[dict[str, Any]]] | None,
    max_review_cycles: int,
    max_findings_per_cycle: int,
    stagnant_cycles: int,
    protected_paths: Iterable[str],
) -> PolicyDecision:
    status = str(review.get("status", "blocking"))
    findings = list(review.get("findings", []))
    if status == "approved" and not findings:
        return PolicyDecision("approved", "review approved")
    if len(findings) > max_findings_per_cycle:
        return PolicyDecision("handoff", "too many findings")
    if any(_finding_is_conflicting(finding) for finding in findings):
        return PolicyDecision("handoff", "conflicting finding")
    if any(_finding_touches_protected_path(finding, protected_paths) for finding in findings):
        return PolicyDecision("handoff", "protected path finding")
    if cycle >= max_review_cycles:
        return PolicyDecision("handoff", "max review cycles reached")
    history = previous_findings or []
    if _has_repeated_findings(findings, history):
        return PolicyDecision("handoff", "repeated finding")
    if _is_stagnant(findings, history, stagnant_cycles):
        return PolicyDecision("handoff", "stagnant findings")
    return PolicyDecision("continue", "blocking findings can be remediated")


def _finding_key(finding: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(finding.get("path", "")),
        str(finding.get("title", "")),
        str(finding.get("message", "")),
    )


def _has_repeated_findings(findings: list[dict[str, Any]], history: list[list[dict[str, Any]]]) -> bool:
    if not history:
        return False
    current = {_finding_key(item) for item in findings}
    previous = {_finding_key(item) for item in history[-1]}
    return bool(current and current.issubset(previous))


def _is_stagnant(findings: list[dict[str, Any]], history: list[list[dict[str, Any]]], stagnant_cycles: int) -> bool:
    if stagnant_cycles <= 1 or len(history) + 1 < stagnant_cycles:
        return False
    current = {_finding_key(item) for item in findings}
    if not current:
        return False
    recent = history[-(stagnant_cycles - 1):]
    return all({_finding_key(item) for item in group} == current for group in recent)


def _finding_is_conflicting(finding: dict[str, Any]) -> bool:
    return bool(finding.get("conflicting")) or str(finding.get("severity", "")).lower() == "conflict"


def _finding_touches_protected_path(finding: dict[str, Any], protected_paths: Iterable[str]) -> bool:
    path = str(finding.get("path", ""))
    return bool(path and protected_path_matches(path, protected_paths))
