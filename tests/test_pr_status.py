from agentic_loop.pr_status import END_MARKER, START_MARKER, upsert_status_section


def test_status_section_is_created():
    body = upsert_status_section(
        "Closes #7",
        {
            "issue": 7,
            "phase": "reviewing",
            "branch": "agentic/issue-7",
            "plan_summary": "create fixture",
            "trace_artifact": "agentic-loop-traces/issue-7.md",
            "validation_results": {"skipped": False, "passed": True, "commands": []},
            "review_summary": "looks good",
            "remediation_count": 1,
            "cycle": 1,
            "handoff_status": "review approved",
        },
    )
    assert START_MARKER in body
    assert END_MARKER in body
    assert "- Source issue: #7" in body
    assert "- Trace artifact: agentic-loop-traces/issue-7.md" in body
    assert "- Validation status: passed" in body
    assert "- Automation will not merge." in body


def test_status_section_is_updated_once():
    original = upsert_status_section(
        "Before",
        {"issue": 7, "phase": "reviewing", "branch": "agentic/issue-7"},
    )
    updated = upsert_status_section(
        original,
        {"issue": 7, "phase": "human-review", "branch": "agentic/issue-7", "handoff_status": "review approved"},
    )
    assert updated.count(START_MARKER) == 1
    assert "- Current phase: human-review" in updated
    assert "- Handoff status: review approved" in updated
    assert "Before" in updated


def test_status_section_preserves_unmanaged_body_text():
    body = "Intro text\n\nFooter note"
    updated = upsert_status_section(body, {"issue": 7, "phase": "reviewing", "branch": "agentic/issue-7"})
    assert updated.startswith("Intro text\n\nFooter note")
    assert START_MARKER in updated
