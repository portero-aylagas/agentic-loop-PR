from pathlib import Path
from types import SimpleNamespace

from agentic_loop.cli import _resolve_issue_file, seed_demo
from agentic_loop.config import validate_all
from agentic_loop.controller import Controller
from agentic_loop.git_client import DiffFile
from agentic_loop.github_cli import Issue, PullRequest

ROOT = Path(__file__).resolve().parents[1]


class FakeGitHub:
    def __init__(self, existing_pr=None, label_results=None, failed_label_ops=None):
        self.issue = Issue(7, "demo", "make a file", "https://example.test/issues/7")
        self.existing_pr = existing_pr
        self.created_prs = []
        self.issue_comments_log = []
        self.pr_comments_log = []
        self.label_results = list(label_results or [])
        self.created_issue_labels = None
        self.failed_label_ops = set(failed_label_ops or [])
        self.label_ops = []

    def issue_view(self, number):
        assert number == self.issue.number
        return self.issue

    def comment_issue(self, number, body):
        self.issue_comments_log.append((number, body))

    def comment_pr(self, number, body):
        self.pr_comments_log.append((number, body))

    def find_open_pr_by_branch(self, branch):
        return self.existing_pr

    def create_pr(self, *, title, body, head, base):
        pr = PullRequest(11, "https://example.test/pull/11", head, base)
        self.created_prs.append((title, body, head, base))
        self.label_ops.append(("create_pr", pr.number))
        return pr

    def ensure_label(self, name, color="6f42c1", description="Agentic loop demo label"):
        self.label_ops.append(("ensure", name))
        if ("ensure", name) in self.failed_label_ops:
            return False
        if self.label_results:
            return self.label_results.pop(0)
        return True

    def add_issue_label(self, number, label):
        self.label_ops.append(("add_issue", number, label))
        return ("add_issue", number, label) not in self.failed_label_ops

    def remove_issue_label(self, number, label):
        self.label_ops.append(("remove_issue", number, label))
        return ("remove_issue", number, label) not in self.failed_label_ops

    def add_pr_label(self, number, label):
        self.label_ops.append(("add_pr", number, label))
        return ("add_pr", number, label) not in self.failed_label_ops

    def remove_pr_label(self, number, label):
        self.label_ops.append(("remove_pr", number, label))
        return ("remove_pr", number, label) not in self.failed_label_ops

    def create_issue(self, title, body, labels):
        self.created_issue_labels = labels
        return self.issue


class FakeGit:
    def __init__(self, dirty=False, changed_files=None):
        self.dirty = dirty
        self.changed = list(changed_files or [])
        self.changed_calls = 0
        self.branches = []
        self.commits = []
        self.pushes = []
        self.synced_bases = []

    def has_changes(self):
        return self.dirty

    def checkout_or_create_branch(self, branch, base):
        self.branches.append((branch, base))

    def sync_base(self, base):
        self.synced_bases.append(base)

    def remote_ref(self, base):
        return f"origin/{base}"

    def changed_files(self, base):
        if self.changed and all(isinstance(item, list) for item in self.changed):
            index = min(self.changed_calls, len(self.changed) - 1)
            self.changed_calls += 1
            return self.changed[index]
        return self.changed

    def commit(self, message):
        self.commits.append(message)
        return True

    def push_branch(self, branch):
        self.pushes.append(branch)


class FakeCodex:
    def __init__(self, reviews):
        self.reviews = list(reviews)
        self.roles = []
        self.payloads = []

    def run_role(self, *, role, prompt_path, schema_path, payload):
        self.roles.append(role)
        self.payloads.append(payload)
        if role == "planner":
            data = {"summary": "create fixture", "steps": [{"description": "write file", "verify": "run tests"}], "risks": []}
        elif role == "implementer":
            data = {"summary": "implemented", "files_changed": ["tests/agentic_demo/sample.txt"], "commit_message": "Implement demo fixture"}
        elif role == "reviewer":
            data = self.reviews.pop(0)
        elif role == "remediator":
            data = {"summary": "fixed", "files_changed": ["tests/agentic_demo/sample.txt"], "commit_message": "Remediate demo fixture"}
        else:
            raise AssertionError(role)
        return SimpleNamespace(data=data)


def test_blocking_finding_remediation_rereview_handoff():
    config = validate_all(ROOT / "agentic-loop.yaml")
    github = FakeGitHub()
    git = FakeGit()
    codex = FakeCodex([
        {"status": "blocking", "summary": "missing beta", "findings": [{"title": "missing beta", "path": "tests/agentic_demo/sample.txt", "message": "Add beta", "severity": "medium", "conflicting": False}]},
        {"status": "approved", "summary": "ok", "findings": []},
    ])
    result = Controller(config=config, github=github, git=git, codex=codex).run(7)
    assert result.decision.kind == "approved"
    assert git.synced_bases == ["main"]
    assert codex.roles == ["planner", "implementer", "reviewer", "remediator", "reviewer"]
    assert all(payload["base_ref"] == "main" for payload in codex.payloads)
    assert all(payload["remote_base_ref"] == "origin/main" for payload in codex.payloads)
    assert git.commits == ["Implement demo fixture", "Remediate demo fixture"]
    assert any("Human handoff" in body for _, body in github.pr_comments_log)
    assert any("Agentic workflow:" in body for _, body in github.issue_comments_log)
    assert ("add_issue", 7, "agentic:planning") in github.label_ops
    assert ("add_issue", 7, "agentic:implementing") in github.label_ops
    assert ("add_issue", 7, "agentic:reviewing") in github.label_ops
    assert ("add_pr", 11, "agentic:reviewing") in github.label_ops
    assert ("add_issue", 7, "agentic:remediating") in github.label_ops
    assert ("add_pr", 11, "agentic:remediating") in github.label_ops
    assert ("add_issue", 7, "agentic:human-review") in github.label_ops
    assert ("add_pr", 11, "agentic:human-review") in github.label_ops


def test_phase_labels_update_issue_only_before_pr_exists():
    config = validate_all(ROOT / "agentic-loop.yaml")
    github = FakeGitHub()
    codex = FakeCodex([{ "status": "approved", "summary": "ok", "findings": [] }])
    Controller(config=config, github=github, git=FakeGit(), codex=codex).run(7)
    create_pr_index = github.label_ops.index(("create_pr", 11))
    before_pr_ops = github.label_ops[:create_pr_index]
    assert ("add_issue", 7, "agentic:planning") in before_pr_ops
    assert ("add_issue", 7, "agentic:implementing") in before_pr_ops
    assert not any(op[0] in {"add_pr", "remove_pr"} for op in before_pr_ops)


def test_phase_label_permission_failure_posts_visible_comment():
    config = validate_all(ROOT / "agentic-loop.yaml")
    github = FakeGitHub(failed_label_ops={("add_issue", 7, "agentic:planning")})
    codex = FakeCodex([{ "status": "approved", "summary": "ok", "findings": [] }])
    Controller(config=config, github=github, git=FakeGit(), codex=codex).run(7)
    assert any("label update failed" in body and "add label `agentic:planning`" in body for _, body in github.issue_comments_log)


def test_failed_phase_label_is_applied_when_controller_errors_before_pr():
    class FailingCodex(FakeCodex):
        def run_role(self, *, role, prompt_path, schema_path, payload):
            raise RuntimeError("planner failed")

    config = validate_all(ROOT / "agentic-loop.yaml")
    github = FakeGitHub()
    try:
        Controller(config=config, github=github, git=FakeGit(), codex=FailingCodex([])).run(7)
    except RuntimeError as exc:
        assert "planner failed" in str(exc)
    else:
        raise AssertionError("controller error should propagate")
    assert ("add_issue", 7, "agentic:failed") in github.label_ops
    assert not any(op[0] in {"add_pr", "remove_pr"} for op in github.label_ops)


def test_pr_reuse_by_branch():
    config = validate_all(ROOT / "agentic-loop.yaml")
    existing = PullRequest(22, "https://example.test/pull/22", "agentic/issue-7", "main")
    github = FakeGitHub(existing_pr=existing)
    codex = FakeCodex([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), codex=codex).run(7)
    assert result.pr == 22
    assert github.created_prs == []


def test_dirty_worktree_aborts_before_github_mutation():
    config = validate_all(ROOT / "agentic-loop.yaml")
    github = FakeGitHub()
    codex = FakeCodex([{ "status": "approved", "summary": "ok", "findings": [] }])
    try:
        Controller(config=config, github=github, git=FakeGit(dirty=True), codex=codex).run(7)
    except RuntimeError as exc:
        assert "uncommitted changes" in str(exc)
    else:
        raise AssertionError("dirty worktree should abort")
    assert github.issue_comments_log == []
    assert github.created_prs == []
    assert codex.roles == []


def test_protected_path_change_hands_off_before_reviewer():
    config = validate_all(ROOT / "agentic-loop.yaml")
    github = FakeGitHub()
    git = FakeGit(changed_files=[DiffFile("agentic_loop_assets/schemas/review.schema.json", "M")])
    codex = FakeCodex([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=git, codex=codex).run(7)
    assert result.decision.kind == "handoff"
    assert result.decision.reason == "protected path changed before review"
    assert codex.roles == ["planner", "implementer"]
    assert any("Protected path changed" in body for _, body in github.pr_comments_log)


def test_protected_path_change_after_remediation_hands_off_before_rereview():
    config = validate_all(ROOT / "agentic-loop.yaml")
    github = FakeGitHub()
    git = FakeGit(changed_files=[
        [],
        [DiffFile("agentic_loop_assets/schemas/review.schema.json", "M")],
    ])
    codex = FakeCodex([
        {"status": "blocking", "summary": "bad revert", "findings": [{"title": "Remove unrelated changes", "path": "agentic-loop.yaml", "message": "Restore unrelated files from the base branch.", "severity": "medium", "conflicting": False}]},
        {"status": "approved", "summary": "ok", "findings": []},
    ])
    result = Controller(config=config, github=github, git=git, codex=codex).run(7)
    assert result.decision.kind == "handoff"
    assert result.decision.reason == "protected path changed before review"
    assert codex.roles == ["planner", "implementer", "reviewer", "remediator"]


def test_seed_demo_label_creation_fallback_comment(tmp_path):
    config = validate_all(ROOT / "agentic-loop.yaml")
    issue_file = tmp_path / "issue.md"
    issue_file.write_text("demo body", encoding="utf-8")
    github = FakeGitHub(label_results=[True, False])
    issue = seed_demo(config, issue_file, github=github)
    assert issue.number == 7
    assert github.created_issue_labels == [config.ready_label]
    assert "Label creation failed" in github.issue_comments_log[0][1]


def test_issue_file_resolves_relative_to_repository_root():
    config = validate_all(ROOT / "agentic-loop.yaml")
    issue_file = _resolve_issue_file(config, Path("demo/issues/isolated_text_fixture.md"))
    assert issue_file == ROOT / "demo/issues/isolated_text_fixture.md"
