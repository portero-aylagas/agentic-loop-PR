from pathlib import Path
from types import SimpleNamespace

from agentic_loop.cli import _resolve_issue_file, seed_demo
from agentic_loop.config import validate_all
from agentic_loop.controller import Controller
from agentic_loop.github_cli import Issue, PullRequest

ROOT = Path(__file__).resolve().parents[1]


class FakeGitHub:
    def __init__(self, existing_pr=None, label_results=None):
        self.issue = Issue(7, "demo", "make a file", "https://example.test/issues/7")
        self.existing_pr = existing_pr
        self.created_prs = []
        self.issue_comments_log = []
        self.pr_comments_log = []
        self.label_results = list(label_results or [])
        self.created_issue_labels = None

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
        return pr

    def ensure_label(self, name):
        if self.label_results:
            return self.label_results.pop(0)
        return True

    def create_issue(self, title, body, labels):
        self.created_issue_labels = labels
        return self.issue


class FakeGit:
    def __init__(self):
        self.branches = []
        self.commits = []
        self.pushes = []

    def checkout_or_create_branch(self, branch, base):
        self.branches.append((branch, base))

    def commit(self, message):
        self.commits.append(message)
        return True

    def push_branch(self, branch):
        self.pushes.append(branch)


class FakeCodex:
    def __init__(self, reviews):
        self.reviews = list(reviews)
        self.roles = []

    def run_role(self, *, role, prompt_path, schema_path, payload):
        self.roles.append(role)
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
        {"status": "blocking", "summary": "missing beta", "findings": [{"title": "missing beta", "path": "tests/agentic_demo/sample.txt", "message": "Add beta", "severity": "medium"}]},
        {"status": "approved", "summary": "ok", "findings": []},
    ])
    result = Controller(config=config, github=github, git=git, codex=codex).run(7)
    assert result.decision.kind == "approved"
    assert codex.roles == ["planner", "implementer", "reviewer", "remediator", "reviewer"]
    assert git.commits == ["Implement demo fixture", "Remediate demo fixture"]
    assert any("Human handoff" in body for _, body in github.pr_comments_log)


def test_pr_reuse_by_branch():
    config = validate_all(ROOT / "agentic-loop.yaml")
    existing = PullRequest(22, "https://example.test/pull/22", "agentic/issue-7", "main")
    github = FakeGitHub(existing_pr=existing)
    codex = FakeCodex([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), codex=codex).run(7)
    assert result.pr == 22
    assert github.created_prs == []


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
