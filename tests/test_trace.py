from pathlib import Path

from agentic_loop.trace import TraceRecorder, render_trace_event, trace_artifact_path


def test_trace_artifact_path_is_issue_scoped():
    assert trace_artifact_path(7, "agentic-loop-traces") == "agentic-loop-traces/issue-7.md"
    assert trace_artifact_path(7, "agentic-loop-traces\\") == "agentic-loop-traces/issue-7.md"


def test_trace_renders_planner_steps_and_risks():
    body = render_trace_event({
        "role": "planner",
        "timestamp": "2026-06-19T00:00:00+00:00",
        "plan": {
            "summary": "create fixture",
            "steps": [{"description": "write file", "verify": "run tests"}],
            "risks": ["fixture path typo"],
        },
    })
    assert "## Planner - 2026-06-19T00:00:00+00:00" in body
    assert "- Summary: create fixture" in body
    assert "1. write file" in body
    assert "- Verify: run tests" in body
    assert "- fixture path typo" in body


def test_trace_renders_review_decision_and_findings():
    body = render_trace_event({
        "role": "reviewer",
        "timestamp": "2026-06-19T00:00:00+00:00",
        "cycle": 1,
        "review": {
            "status": "blocking",
            "summary": "missing beta",
            "findings": [{
                "title": "missing beta",
                "path": "tests/agentic_demo/sample.txt",
                "message": "Add beta",
                "severity": "medium",
            }],
        },
        "decision": {"kind": "continue", "reason": "review findings require remediation"},
    })
    assert "- Policy decision: continue" in body
    assert "- Decision reason: review findings require remediation" in body
    assert "**missing beta**" in body


def test_trace_recorder_appends_markdown(tmp_path: Path):
    recorder = TraceRecorder(issue=7, branch="agentic/issue-7", artifact_path="agentic-loop-traces/issue-7.md")
    recorder.append(tmp_path, {"role": "implementer", "timestamp": "now", "output": {"summary": "done", "files_changed": ["demo.txt"], "commit_message": "Demo"}})
    recorder.append(tmp_path, {"role": "orchestrator", "timestamp": "later", "phase": "human-review", "reason": "review approved"})
    body = (tmp_path / "agentic-loop-traces/issue-7.md").read_text(encoding="utf-8")
    assert "# Agentic Loop Trace for Issue #7" in body
    assert "## Implementer - now" in body
    assert "`demo.txt`" in body
    assert "## Orchestrator - later" in body
