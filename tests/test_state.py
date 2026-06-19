from agentic_loop.state import WorkflowState, decode_states, encode_state, newest_state


def test_hidden_state_round_trip():
    encoded = encode_state(
        WorkflowState(
            issue=7,
            phase="reviewing",
            cycle=1,
            branch="agentic/issue-7",
            pr=3,
            review_invocation_count=2,
            remediation_attempt_count=1,
            model_provider={"provider": "CodexProvider", "model": "gpt-5"},
            timestamp="2026-06-19T00:00:00+00:00",
        )
    )
    states = decode_states(encoded)
    assert states[0]["issue"] == 7
    assert states[0]["phase"] == "reviewing"
    assert states[0]["pr"] == 3
    assert states[0]["branch"] == "agentic/issue-7"
    assert states[0]["status"] == "running"
    assert states[0]["cycle"] == 1
    assert states[0]["review_invocation_count"] == 2
    assert states[0]["remediation_attempt_count"] == 1
    assert states[0]["model_provider"] == {"provider": "CodexProvider", "model": "gpt-5"}
    assert states[0]["timestamp"] == "2026-06-19T00:00:00+00:00"
    assert states[0]["updated_at"] == "2026-06-19T00:00:00+00:00"


def test_backward_compatible_decode_of_older_state():
    encoded = '<!-- agentic-workflow-state:v1 {"issue":7,"phase":"reviewing","cycle":1,"branch":"agentic/issue-7"} -->'
    states = decode_states(encoded)
    assert states == [{"issue": 7, "phase": "reviewing", "cycle": 1, "branch": "agentic/issue-7"}]


def test_newest_state_selection():
    older = {"body": '<!-- agentic-workflow-state:v1 {"issue":1,"updated_at":"2024-01-01T00:00:00+00:00"} -->'}
    newer = {"body": '<!-- agentic-workflow-state:v1 {"issue":2,"updated_at":"2024-01-02T00:00:00+00:00"} -->'}
    timestamp_only = {"body": '<!-- agentic-workflow-state:v1 {"issue":3,"timestamp":"2024-01-03T00:00:00+00:00"} -->'}
    assert newest_state([older, timestamp_only, newer])["issue"] == 3


def test_state_with_validation_and_finding_data():
    finding = {
        "title": "Fix validation",
        "path": "tests/test_demo.py",
        "message": "Make pytest pass.",
        "severity": "medium",
        "conflicting": False,
    }
    validation_results = {
        "skipped": False,
        "passed": False,
        "commands": [{"command": "python -m pytest", "exit_code": 1, "stdout": "", "stderr": "failed"}],
    }
    encoded = encode_state(
        WorkflowState(
            issue=7,
            phase="reviewed",
            cycle=2,
            branch="agentic/issue-7",
            pr=11,
            status="handoff",
            findings=[finding],
            validation_results=validation_results,
            handoff_reason="validation failed after policy limits",
            review_invocation_count=3,
            remediation_attempt_count=2,
        )
    )
    state = decode_states(encoded)[0]
    assert state["findings"] == [finding]
    assert state["validation_results"] == validation_results
    assert state["handoff_reason"] == "validation failed after policy limits"
