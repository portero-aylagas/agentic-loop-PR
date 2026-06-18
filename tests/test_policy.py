from agentic_loop.policy import decide_review, protected_path_matches


def finding(title="bad", path="src/demo.py", severity="medium", **extra):
    return {"title": title, "path": path, "message": title, "severity": severity, **extra}


def decision(review, **kwargs):
    defaults = dict(
        cycle=0,
        previous_findings=[],
        max_review_cycles=2,
        max_findings_per_cycle=3,
        stagnant_cycles=2,
        protected_paths=[".github/**"],
    )
    defaults.update(kwargs)
    return decide_review(review=review, **defaults)


def test_approved_decision():
    assert decision({"status": "approved", "findings": []}).kind == "approved"


def test_blocking_decision_continues():
    assert decision({"status": "blocking", "findings": [finding()]}).kind == "continue"


def test_repeated_finding_hands_off():
    item = finding()
    assert decision({"status": "blocking", "findings": [item]}, previous_findings=[[item]]).reason == "repeated finding"


def test_stagnant_finding_hands_off():
    item = finding()
    assert decision({"status": "blocking", "findings": [item]}, previous_findings=[[item]], stagnant_cycles=2).kind == "handoff"


def test_conflicting_finding_hands_off():
    assert decision({"status": "blocking", "findings": [finding(severity="conflict")]}).reason == "conflicting finding"


def test_max_cycle_hands_off():
    assert decision({"status": "blocking", "findings": [finding()]}, cycle=2).reason == "max review cycles reached"


def test_max_finding_hands_off():
    findings = [finding(str(index)) for index in range(4)]
    assert decision({"status": "blocking", "findings": findings}).reason == "too many findings"


def test_protected_path_matching():
    assert protected_path_matches(".github/workflows/validate.yml", [".github/**"])
    assert decision({"status": "blocking", "findings": [finding(path=".github/workflows/validate.yml")]}).reason == "protected path finding"
