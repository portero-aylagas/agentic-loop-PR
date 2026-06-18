from agentic_loop.state import WorkflowState, decode_states, encode_state, newest_state


def test_hidden_state_round_trip():
    encoded = encode_state(WorkflowState(issue=7, phase="reviewing", cycle=1, branch="agentic/issue-7", pr=3))
    states = decode_states(encoded)
    assert states[0]["issue"] == 7
    assert states[0]["phase"] == "reviewing"


def test_newest_state_selection():
    older = {"body": '<!-- agentic-workflow-state:v1 {"issue":1,"updated_at":"2024-01-01T00:00:00+00:00"} -->'}
    newer = {"body": '<!-- agentic-workflow-state:v1 {"issue":2,"updated_at":"2024-01-02T00:00:00+00:00"} -->'}
    assert newest_state([older, newer])["issue"] == 2
