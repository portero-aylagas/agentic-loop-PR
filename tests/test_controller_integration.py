from pathlib import Path
from agentic_loop.cli import _resolve_issue_file, seed_demo
from agentic_loop.command import CommandResult
from agentic_loop.config import LoopConfig, validate_all
from agentic_loop.controller import Controller
from agentic_loop.git_client import DiffFile, DiffStats, StatusFile
from agentic_loop.github_cli import Issue, PullRequest
from agentic_loop.provider import RoleResult
from agentic_loop.state import WorkflowState, decode_states, encode_state

ROOT = Path(__file__).resolve().parents[1]


class FakeGitHub:
    def __init__(
        self,
        existing_pr=None,
        label_results=None,
        failed_label_ops=None,
        issue_comments=None,
        pr_comments=None,
        issue_labels=None,
        pr_labels=None,
    ):
        self.issue = Issue(7, "demo", "make a file", "https://example.test/issues/7")
        self.existing_pr = existing_pr
        self.created_prs = []
        self.pr_bodies = {}
        if existing_pr is not None:
            self.pr_bodies[existing_pr.number] = "Existing body"
        self.issue_comments_log = list(issue_comments or [])
        self.pr_comments_log = list(pr_comments or [])
        self.label_results = list(label_results or [])
        self.created_issue_labels = None
        self.failed_label_ops = set(failed_label_ops or [])
        self.label_ops = []
        self._issue_labels = set(issue_labels or [])
        self._pr_labels = set(pr_labels or [])

    def issue_view(self, number):
        assert number == self.issue.number
        return self.issue

    def issue_comments(self, number):
        assert number == self.issue.number
        return [{"body": body} for _, body in self.issue_comments_log]

    def pr_comments(self, number):
        return [{"body": body} for _, body in self.pr_comments_log if _ == number]

    def pr_body(self, number):
        return self.pr_bodies.get(number, "")

    def edit_pr_body(self, number, body):
        self.pr_bodies[number] = body

    def comment_issue(self, number, body):
        self.issue_comments_log.append((number, body))

    def comment_pr(self, number, body):
        self.pr_comments_log.append((number, body))

    def find_open_pr_by_branch(self, branch):
        return self.existing_pr

    def create_pr(self, *, title, body, head, base):
        pr = PullRequest(11, "https://example.test/pull/11", head, base)
        self.created_prs.append((title, body, head, base))
        self.pr_bodies[pr.number] = body
        self.label_ops.append(("create_pr", pr.number))
        return pr

    def ensure_label(self, name, color="6f42c1", description="Agentic loop demo label"):
        self.label_ops.append(("ensure", name))
        if ("ensure", name) in self.failed_label_ops:
            return False
        if self.label_results:
            return self.label_results.pop(0)
        return True

    def issue_labels(self, number):
        assert number == self.issue.number
        self.label_ops.append(("issue_labels", number))
        return set(self._issue_labels)

    def pr_labels(self, number):
        self.label_ops.append(("pr_labels", number))
        return set(self._pr_labels)

    def add_issue_label(self, number, label):
        self.label_ops.append(("add_issue", number, label))
        if ("add_issue", number, label) in self.failed_label_ops:
            return False
        self._issue_labels.add(label)
        return True

    def remove_issue_label(self, number, label):
        self.label_ops.append(("remove_issue", number, label))
        if ("remove_issue", number, label) in self.failed_label_ops:
            return False
        self._issue_labels.discard(label)
        return True

    def add_pr_label(self, number, label):
        self.label_ops.append(("add_pr", number, label))
        if ("add_pr", number, label) in self.failed_label_ops:
            return False
        self._pr_labels.add(label)
        return True

    def remove_pr_label(self, number, label):
        self.label_ops.append(("remove_pr", number, label))
        if ("remove_pr", number, label) in self.failed_label_ops:
            return False
        self._pr_labels.discard(label)
        return True

    def create_issue(self, title, body, labels):
        self.created_issue_labels = labels
        return self.issue


class FakeGit:
    def __init__(self, dirty=False, changed_files=None, diff_lines=0, status_files=None, cwd=ROOT):
        self.dirty = dirty
        self.changed = list(changed_files or [])
        self.diff_lines = diff_lines
        if status_files is None:
            status_files = [StatusFile("tests/agentic_demo/sample.txt", " ", "M")]
        self.status = list(status_files)
        self.changed_calls = 0
        self.cwd = Path(cwd)
        self.prepared_worktrees = []
        self.branches = []
        self.commits = []
        self.pushes = []
        self.synced_bases = []
        self.staged_paths = []

    def with_cwd(self, cwd):
        clone = FakeGit(dirty=self.dirty, changed_files=self.changed, diff_lines=self.diff_lines, status_files=self.status, cwd=cwd)
        clone.changed_calls = self.changed_calls
        clone.prepared_worktrees = self.prepared_worktrees
        clone.branches = self.branches
        clone.commits = self.commits
        clone.pushes = self.pushes
        clone.synced_bases = self.synced_bases
        clone.staged_paths = self.staged_paths
        return clone

    def prepare_issue_worktree(self, *, issue, branch, base, repo_root):
        worktree = Path(repo_root) / ".worktrees" / f"agentic-issue-{issue}"
        self.prepared_worktrees.append((issue, branch, base, worktree))
        if self.dirty:
            raise RuntimeError(f"target worktree has uncommitted changes: {worktree}")
        return worktree

    def has_changes(self):
        return self.dirty

    def status_files(self):
        return list(self.status)

    def stage_paths(self, paths):
        self.staged_paths.append((self.cwd, list(paths)))
        reported = set(paths)
        self.status = [
            StatusFile(item.path, item.index_status if item.path not in reported else _staged_status(item), " ")
            for item in self.status
        ]

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

    def diff_stats(self, base):
        changed = self.changed
        if changed and all(isinstance(item, list) for item in changed):
            index = min(max(self.changed_calls - 1, 0), len(changed) - 1)
            changed = changed[index]
        diff_lines = self.diff_lines
        if isinstance(diff_lines, list):
            index = min(max(self.changed_calls - 1, 0), len(diff_lines) - 1)
            diff_lines = diff_lines[index]
        return DiffStats(changed_files=len(changed), diff_lines=diff_lines)

    def commit(self, message):
        self.commits.append((self.cwd, message))
        return True

    def commit_staged(self, message):
        if not any(item.index_status != " " for item in self.status):
            return False
        self.commits.append((self.cwd, message))
        self.status = [StatusFile("tests/agentic_demo/sample.txt", " ", "M")]
        return True

    def push_branch(self, branch):
        self.pushes.append((self.cwd, branch))


class FakeProvider:
    def __init__(self, reviews, cwd=ROOT):
        self.reviews = list(reviews)
        self.cwd = Path(cwd)
        self.roles = []
        self.payloads = []
        self.cwd_log = []

    def with_cwd(self, cwd):
        clone = type(self)(self.reviews, cwd=cwd)
        clone.roles = self.roles
        clone.payloads = self.payloads
        clone.cwd_log = self.cwd_log
        return clone

    def run_role(self, *, role, prompt_path, schema_path, payload):
        self.roles.append(role)
        self.payloads.append(payload)
        self.cwd_log.append(self.cwd)
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
        return RoleResult(role=role, data=data)


class CustomFileProvider(FakeProvider):
    def __init__(self, reviews, *, implementation_files, remediation_files=None, cwd=ROOT):
        super().__init__(reviews, cwd=cwd)
        self.implementation_files = implementation_files
        self.remediation_files = remediation_files if remediation_files is not None else implementation_files

    def with_cwd(self, cwd):
        clone = type(self)(
            self.reviews,
            implementation_files=self.implementation_files,
            remediation_files=self.remediation_files,
            cwd=cwd,
        )
        clone.roles = self.roles
        clone.payloads = self.payloads
        clone.cwd_log = self.cwd_log
        return clone

    def run_role(self, *, role, prompt_path, schema_path, payload):
        result = super().run_role(role=role, prompt_path=prompt_path, schema_path=schema_path, payload=payload)
        if role == "implementer":
            result.data["files_changed"] = list(self.implementation_files)
        elif role == "remediator":
            result.data["files_changed"] = list(self.remediation_files)
        return result


def _staged_status(item):
    if item.worktree_status == "?":
        return "A"
    if item.worktree_status != " ":
        return item.worktree_status
    return item.index_status


class FakeValidationRunner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run(self, args, *, input_text=None, cwd=None, check=True):
        self.calls.append((list(args), cwd, check))
        result = self.results.pop(0)
        return CommandResult(tuple(args), result["returncode"], result.get("stdout", ""), result.get("stderr", ""))


def config_without_validation():
    config = validate_all(ROOT / "agentic-loop.yaml")
    data = {key: dict(value) if isinstance(value, dict) else value for key, value in config.data.items()}
    data.pop("validation", None)
    return LoopConfig(config.path, data)


def config_with_policy(**policy):
    config = config_without_validation()
    data = {key: dict(value) if isinstance(value, dict) else value for key, value in config.data.items()}
    data["policy"] = {**data["policy"], **policy}
    return LoopConfig(config.path, data)


def config_with_validation(commands, **policy):
    config = config_without_validation()
    data = {key: dict(value) if isinstance(value, dict) else value for key, value in config.data.items()}
    data["validation"] = {"commands": commands}
    if policy:
        data["policy"] = {**data["policy"], **policy}
    return LoopConfig(config.path, data)


def test_blocking_finding_remediation_rereview_handoff():
    config = config_without_validation()
    github = FakeGitHub()
    git = FakeGit()
    codex = FakeProvider([
        {"status": "blocking", "summary": "missing beta", "findings": [{"title": "missing beta", "path": "tests/agentic_demo/sample.txt", "message": "Add beta", "severity": "medium", "conflicting": False}]},
        {"status": "approved", "summary": "ok", "findings": []},
    ])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    assert result.decision.kind == "approved"
    assert codex.roles == ["planner", "implementer", "reviewer", "remediator", "reviewer"]
    assert all(payload["base_ref"] == "main" for payload in codex.payloads)
    assert all(payload["remote_base_ref"] == "origin/main" for payload in codex.payloads)
    worktree = ROOT / ".worktrees" / "agentic-issue-7"
    assert git.prepared_worktrees == [(7, "agentic/issue-7", "main", worktree)]
    assert codex.cwd_log == [worktree, worktree, worktree, worktree, worktree]
    assert git.commits == [(worktree, "Implement demo fixture"), (worktree, "Remediate demo fixture")]
    assert git.pushes == [(worktree, "agentic/issue-7"), (worktree, "agentic/issue-7")]
    assert git.staged_paths == [
        (worktree, ["tests/agentic_demo/sample.txt"]),
        (worktree, ["tests/agentic_demo/sample.txt"]),
    ]
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
    config = config_without_validation()
    github = FakeGitHub()
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    create_pr_index = github.label_ops.index(("create_pr", 11))
    before_pr_ops = github.label_ops[:create_pr_index]
    assert ("add_issue", 7, "agentic:planning") in before_pr_ops
    assert ("add_issue", 7, "agentic:implementing") in before_pr_ops
    assert not any(op[0] in {"add_pr", "remove_pr"} for op in before_pr_ops)


def test_phase_label_permission_failure_posts_visible_comment():
    config = config_without_validation()
    github = FakeGitHub(failed_label_ops={("add_issue", 7, "agentic:planning")})
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    assert result.decision.kind == "approved"
    assert any(
        "label update failed" in body
        and "add label `agentic:planning` on issue #7" in body
        and "Manual action: create `agentic:planning` if it is missing, then add it to issue #7." in body
        for _, body in github.issue_comments_log
    )


def test_phase_label_creation_failure_posts_visible_comment_and_continues():
    config = config_without_validation()
    github = FakeGitHub(failed_label_ops={("ensure", "agentic:planning")})
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    assert result.decision.kind == "approved"
    assert any(
        "could not create label `agentic:planning` on issue #7" in body
        and "Manual action: create `agentic:planning` in the repository" in body
        for _, body in github.issue_comments_log
    )


def test_phase_label_remove_failure_posts_visible_comment_and_continues():
    config = config_without_validation()
    github = FakeGitHub(
        failed_label_ops={("remove_issue", 7, "agentic:implementing")},
        issue_labels={"agentic:implementing"},
    )
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    assert result.decision.kind == "approved"
    assert any(
        "could not remove label `agentic:implementing` on issue #7" in body
        and "Manual action: remove `agentic:implementing` from issue #7 if it is present" in body
        for _, body in github.issue_comments_log
    )


def test_phase_label_success_path_does_not_post_label_failure_comment():
    config = config_without_validation()
    github = FakeGitHub()
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    assert result.decision.kind == "approved"
    assert not any("label update failed" in body.lower() for _, body in [*github.issue_comments_log, *github.pr_comments_log])


def test_absent_phase_labels_are_not_removed_or_reported():
    config = config_without_validation()
    github = FakeGitHub(failed_label_ops={("remove_issue", 7, "agentic:remediating")})
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    assert result.decision.kind == "approved"
    assert ("remove_issue", 7, "agentic:remediating") not in github.label_ops
    assert not any("agentic:remediating" in body and "label update failed" in body.lower() for _, body in github.issue_comments_log)


def test_present_phase_labels_are_removed_before_new_phase_label():
    config = config_without_validation()
    github = FakeGitHub(issue_labels={"agentic:reviewing"})
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    assert result.decision.kind == "approved"
    assert ("remove_issue", 7, "agentic:reviewing") in github.label_ops


def test_failed_phase_label_is_applied_when_controller_errors_before_pr():
    class FailingProvider(FakeProvider):
        def run_role(self, *, role, prompt_path, schema_path, payload):
            raise RuntimeError("planner failed")

    config = config_without_validation()
    github = FakeGitHub()
    try:
        Controller(config=config, github=github, git=FakeGit(), provider=FailingProvider([])).run(7)
    except RuntimeError as exc:
        assert "planner failed" in str(exc)
    else:
        raise AssertionError("controller error should propagate")
    assert ("add_issue", 7, "agentic:failed") in github.label_ops
    assert not any(op[0] in {"add_pr", "remove_pr"} for op in github.label_ops)


def test_pr_reuse_by_branch():
    config = config_without_validation()
    existing = PullRequest(22, "https://example.test/pull/22", "agentic/issue-7", "main")
    github = FakeGitHub(existing_pr=existing)
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    assert result.pr == 22
    assert github.created_prs == []


def test_created_pr_body_includes_managed_status_section():
    config = config_without_validation()
    github = FakeGitHub()
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    body = github.pr_bodies[11]
    assert "<!-- agentic-loop-status:start -->" in body
    assert "<!-- agentic-loop-status:end -->" in body
    assert "- Source issue: #7" in body
    assert "- Plan summary: create fixture" in body
    assert "- Automation will not merge." in body


def test_pr_body_refresh_preserves_unmanaged_text():
    config = config_without_validation()
    existing = PullRequest(22, "https://example.test/pull/22", "agentic/issue-7", "main")
    github = FakeGitHub(existing_pr=existing)
    github.pr_bodies[22] = "Keep this intro\n\n<!-- agentic-loop-status:start -->\nold\n<!-- agentic-loop-status:end -->\n\nKeep this footer"
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    body = github.pr_bodies[22]
    assert body.startswith("Keep this intro")
    assert body.rstrip().endswith("Keep this footer")
    assert body.count("<!-- agentic-loop-status:start -->") == 1
    assert "- Current phase: human-review" in body
    assert "- Handoff status: review approved" in body


def test_terminal_state_stops_without_force():
    config = config_without_validation()
    existing = PullRequest(22, "https://example.test/pull/22", "agentic/issue-7", "main")
    state = WorkflowState(issue=7, phase="human-review", cycle=1, branch="agentic/issue-7", pr=22)
    github = FakeGitHub(existing_pr=existing, issue_comments=[(7, encode_state(state))])
    git = FakeGit()
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    assert result.pr == 22
    assert result.decision.kind == "handoff"
    assert "already terminal" in result.decision.reason
    assert git.prepared_worktrees == []
    assert codex.roles == []


def test_force_ignores_terminal_state_and_runs():
    config = config_without_validation()
    existing = PullRequest(22, "https://example.test/pull/22", "agentic/issue-7", "main")
    state = WorkflowState(issue=7, phase="failed", cycle=1, branch="agentic/issue-7", pr=22)
    github = FakeGitHub(existing_pr=existing, issue_comments=[(7, encode_state(state))])
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7, force=True)
    assert result.pr == 22
    assert codex.roles == ["planner", "implementer", "reviewer"]
    assert github.created_prs == []


def test_reviewed_state_resumes_at_remediation():
    config = config_without_validation()
    existing = PullRequest(22, "https://example.test/pull/22", "agentic/issue-7", "main")
    findings = [{"title": "missing beta", "path": "tests/agentic_demo/sample.txt", "message": "Add beta", "severity": "medium", "conflicting": False}]
    state = WorkflowState(issue=7, phase="reviewed", cycle=0, branch="agentic/issue-7", pr=22, status="continue", findings=findings)
    github = FakeGitHub(existing_pr=existing, pr_comments=[(22, encode_state(state))])
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    assert result.pr == 22
    assert codex.roles == ["remediator", "reviewer"]
    assert github.created_prs == []


def test_dirty_target_worktree_aborts_before_github_mutation():
    config = config_without_validation()
    github = FakeGitHub()
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    try:
        Controller(config=config, github=github, git=FakeGit(dirty=True), provider=codex).run(7)
    except RuntimeError as exc:
        assert "uncommitted changes" in str(exc)
    else:
        raise AssertionError("dirty worktree should abort")
    assert github.issue_comments_log == []
    assert github.created_prs == []
    assert codex.roles == []


def test_protected_path_change_hands_off_before_reviewer():
    config = config_without_validation()
    github = FakeGitHub()
    git = FakeGit(changed_files=[DiffFile("agentic_loop_assets/schemas/review.schema.json", "M")])
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    assert result.decision.kind == "handoff"
    assert result.decision.reason == "protected path changed before review"
    assert codex.roles == ["planner", "implementer"]
    assert any("Protected path changed" in body for _, body in github.pr_comments_log)


def test_protected_path_change_after_remediation_hands_off_before_rereview():
    config = config_without_validation()
    github = FakeGitHub()
    git = FakeGit(changed_files=[
        [],
        [DiffFile("agentic_loop_assets/schemas/review.schema.json", "M")],
    ])
    codex = FakeProvider([
        {"status": "blocking", "summary": "bad revert", "findings": [{"title": "Remove unrelated changes", "path": "agentic-loop.yaml", "message": "Restore unrelated files from the base branch.", "severity": "medium", "conflicting": False}]},
        {"status": "approved", "summary": "ok", "findings": []},
    ])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    assert result.decision.kind == "handoff"
    assert result.decision.reason == "protected path changed before review"
    assert codex.roles == ["planner", "implementer", "reviewer", "remediator"]


def test_diff_size_within_policy_allows_review():
    config = config_with_policy(max_changed_files=2, max_diff_lines=10)
    github = FakeGitHub()
    git = FakeGit(changed_files=[DiffFile("tests/agentic_demo/sample.txt", "M")], diff_lines=7)
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    assert result.decision.kind == "approved"
    assert codex.roles == ["planner", "implementer", "reviewer"]


def test_diff_size_too_many_files_hands_off_before_reviewer():
    config = config_with_policy(max_changed_files=1, max_diff_lines=100)
    github = FakeGitHub()
    git = FakeGit(changed_files=[
        DiffFile("tests/agentic_demo/one.txt", "M"),
        DiffFile("tests/agentic_demo/two.txt", "A"),
    ], diff_lines=5)
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    assert result.decision.kind == "handoff"
    assert result.decision.reason == "worktree diff exceeds policy limits"
    assert codex.roles == ["planner", "implementer"]
    assert ("add_issue", 7, "agentic:human-review") in github.label_ops
    assert ("add_pr", 11, "agentic:human-review") in github.label_ops
    assert any("2 changed files exceeds policy.max_changed_files=1" in body for _, body in github.pr_comments_log)


def test_diff_size_too_many_lines_hands_off_before_reviewer():
    config = config_with_policy(max_changed_files=10, max_diff_lines=5)
    github = FakeGitHub()
    git = FakeGit(changed_files=[DiffFile("tests/agentic_demo/sample.txt", "M")], diff_lines=6)
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    assert result.decision.kind == "handoff"
    assert result.decision.reason == "worktree diff exceeds policy limits"
    assert codex.roles == ["planner", "implementer"]
    assert any("6 diff lines exceeds policy.max_diff_lines=5" in body for _, body in github.pr_comments_log)


def test_absent_diff_size_policy_defaults_do_not_limit():
    config = config_without_validation()
    data = {key: dict(value) if isinstance(value, dict) else value for key, value in config.data.items()}
    data["policy"].pop("max_changed_files", None)
    data["policy"].pop("max_diff_lines", None)
    config = LoopConfig(config.path, data)
    github = FakeGitHub()
    git = FakeGit(changed_files=[
        DiffFile(f"tests/agentic_demo/{index}.txt", "A")
        for index in range(30)
    ], diff_lines=2000)
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    assert result.decision.kind == "approved"
    assert codex.roles == ["planner", "implementer", "reviewer"]


def test_reported_only_files_are_staged_and_committed():
    config = config_without_validation()
    github = FakeGitHub()
    git = FakeGit(status_files=[StatusFile("tests/agentic_demo/sample.txt", " ", "M")])
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    worktree = ROOT / ".worktrees" / "agentic-issue-7"
    assert result.decision.kind == "approved"
    assert git.staged_paths == [(worktree, ["tests/agentic_demo/sample.txt"])]
    assert git.commits == [(worktree, "Implement demo fixture")]


def test_reported_directory_stages_dirty_children():
    config = config_without_validation()
    github = FakeGitHub()
    git = FakeGit(status_files=[StatusFile("tests/agentic_demo/sample.txt", "?", "?")])
    codex = CustomFileProvider(
        [{ "status": "approved", "summary": "ok", "findings": [] }],
        implementation_files=["tests/agentic_demo/"],
    )
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    worktree = ROOT / ".worktrees" / "agentic-issue-7"
    assert result.decision.kind == "approved"
    assert git.staged_paths == [(worktree, ["tests/agentic_demo/sample.txt"])]
    assert git.commits == [(worktree, "Implement demo fixture")]


def test_reported_directory_does_not_cover_unreported_sibling_file():
    config = config_without_validation()
    github = FakeGitHub()
    git = FakeGit(status_files=[
        StatusFile("tests/agentic_demo/sample.txt", "?", "?"),
        StatusFile("tests/test_agentic_demo_fixture.py", "?", "?"),
    ])
    codex = CustomFileProvider(
        [{ "status": "approved", "summary": "ok", "findings": [] }],
        implementation_files=["tests/agentic_demo/"],
    )
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    assert result.decision.kind == "handoff"
    assert result.decision.reason == "unexpected dirty files"
    assert git.staged_paths == []
    assert any("unexpected dirty files: tests/test_agentic_demo_fixture.py" in body for _, body in github.issue_comments_log)


def test_unexpected_dirty_files_hand_off_without_commit():
    config = config_without_validation()
    github = FakeGitHub()
    git = FakeGit(status_files=[
        StatusFile("tests/agentic_demo/sample.txt", " ", "M"),
        StatusFile("README.md", " ", "M"),
    ])
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    assert result.decision.kind == "handoff"
    assert result.decision.reason == "unexpected dirty files"
    assert git.staged_paths == []
    assert git.commits == []
    assert any("unexpected dirty files: README.md" in body for _, body in github.issue_comments_log)


def test_deleted_reported_file_is_staged_and_committed():
    config = config_without_validation()
    github = FakeGitHub()
    git = FakeGit(status_files=[StatusFile("tests/agentic_demo/sample.txt", " ", "D")])
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    worktree = ROOT / ".worktrees" / "agentic-issue-7"
    assert result.decision.kind == "approved"
    assert git.staged_paths == [(worktree, ["tests/agentic_demo/sample.txt"])]
    assert git.commits == [(worktree, "Implement demo fixture")]


def test_no_change_output_skips_commit_but_pushes_branch():
    config = config_without_validation()
    github = FakeGitHub()
    git = FakeGit(status_files=[])
    codex = CustomFileProvider([{ "status": "approved", "summary": "ok", "findings": [] }], implementation_files=[])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    worktree = ROOT / ".worktrees" / "agentic-issue-7"
    assert result.decision.kind == "approved"
    assert git.staged_paths == []
    assert git.commits == []
    assert git.pushes == [(worktree, "agentic/issue-7")]


def test_reported_file_not_in_git_status_hands_off():
    config = config_without_validation()
    github = FakeGitHub()
    git = FakeGit(status_files=[])
    codex = CustomFileProvider([{ "status": "approved", "summary": "ok", "findings": [] }], implementation_files=["tests/agentic_demo/sample.txt"])
    result = Controller(config=config, github=github, git=git, provider=codex).run(7)
    assert result.decision.kind == "handoff"
    assert result.decision.reason == "reported files are not dirty: tests/agentic_demo/sample.txt"
    assert git.commits == []


def test_validation_success_posts_comment_and_reaches_reviewer():
    config = config_with_validation(["python -m pytest"])
    github = FakeGitHub()
    runner = FakeValidationRunner([{"returncode": 0, "stdout": "ok\n"}])
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex, validation_runner=runner).run(7)
    worktree = ROOT / ".worktrees" / "agentic-issue-7"
    assert result.decision.kind == "approved"
    assert runner.calls == [(["python", "-m", "pytest"], str(worktree), False)]
    assert any("Validation passed: 1 command(s)." in body for _, body in github.pr_comments_log)
    reviewer_payload = codex.payloads[codex.roles.index("reviewer")]
    assert reviewer_payload["validation_results"]["passed"] is True
    assert reviewer_payload["validation_results"]["commands"][0]["stdout"] == "ok\n"


def test_validation_failure_is_included_in_reviewer_and_remediator_payloads():
    config = config_with_validation(["python -m pytest"])
    github = FakeGitHub()
    runner = FakeValidationRunner([
        {"returncode": 1, "stdout": "failed\n", "stderr": "boom\n"},
        {"returncode": 0, "stdout": "fixed\n"},
    ])
    codex = FakeProvider([
        {"status": "blocking", "summary": "tests fail", "findings": [{"title": "fix tests", "path": "tests/test_demo.py", "message": "Make validation pass.", "severity": "medium", "conflicting": False}]},
        {"status": "approved", "summary": "ok", "findings": []},
    ])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex, validation_runner=runner).run(7)
    assert result.decision.kind == "approved"
    reviewer_payload = codex.payloads[codex.roles.index("reviewer")]
    remediator_payload = codex.payloads[codex.roles.index("remediator")]
    assert reviewer_payload["validation_results"]["passed"] is False
    assert reviewer_payload["validation_results"]["commands"][0]["stderr"] == "boom\n"
    assert remediator_payload["validation_results"]["passed"] is False
    assert any("Validation failed: 1 command(s)." in body for _, body in github.pr_comments_log)


def test_validation_skips_when_commands_absent():
    config = config_without_validation()
    github = FakeGitHub()
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex).run(7)
    assert result.decision.kind == "approved"
    assert not any("Validation " in body for _, body in github.pr_comments_log)
    reviewer_payload = codex.payloads[codex.roles.index("reviewer")]
    assert reviewer_payload["validation_results"] == {"skipped": True, "passed": True, "commands": []}


def test_validation_results_are_encoded_in_pr_state():
    config = config_with_validation(["python -m pytest"])
    github = FakeGitHub()
    runner = FakeValidationRunner([{"returncode": 0, "stdout": "ok\n"}])
    codex = FakeProvider([{ "status": "approved", "summary": "ok", "findings": [] }])
    Controller(config=config, github=github, git=FakeGit(), provider=codex, validation_runner=runner).run(7)
    states = []
    for _, body in github.pr_comments_log:
        states.extend(decode_states(body))
    reviewed = [state for state in states if state.get("phase") == "reviewed"]
    assert reviewed[-1]["validation_results"]["commands"][0]["command"] == "python -m pytest"
    assert reviewed[-1]["validation_results"]["commands"][0]["exit_code"] == 0
    assert reviewed[-1]["review_invocation_count"] == 1
    assert reviewed[-1]["remediation_attempt_count"] == 0
    assert reviewed[-1]["model_provider"] == {"provider": "FakeProvider"}
    assert reviewed[-1]["timestamp"]


def test_failing_validation_hands_off_after_review_policy_limit():
    config = config_with_validation(["python -m pytest"], max_review_cycles=1)
    github = FakeGitHub()
    runner = FakeValidationRunner([
        {"returncode": 1, "stderr": "first failure\n"},
        {"returncode": 1, "stderr": "still failing\n"},
    ])
    codex = FakeProvider([
        {"status": "blocking", "summary": "tests fail", "findings": [{"title": "fix tests", "path": "tests/test_demo.py", "message": "Make validation pass.", "severity": "medium", "conflicting": False}]},
        {"status": "approved", "summary": "ok", "findings": []},
    ])
    result = Controller(config=config, github=github, git=FakeGit(), provider=codex, validation_runner=runner).run(7)
    assert result.decision.kind == "handoff"
    assert result.decision.reason == "validation failed after policy limits"
    assert codex.roles == ["planner", "implementer", "reviewer", "remediator"]
    assert ("add_pr", 11, "agentic:human-review") in github.label_ops


def test_seed_demo_label_creation_fallback_comment(tmp_path):
    config = config_without_validation()
    issue_file = tmp_path / "issue.md"
    issue_file.write_text("demo body", encoding="utf-8")
    github = FakeGitHub(label_results=[True, False])
    issue = seed_demo(config, issue_file, github=github)
    assert issue.number == 7
    assert github.created_issue_labels == [config.ready_label]
    assert "could not create label" in github.issue_comments_log[0][1]
    assert "Manual action: create the label in GitHub and add it to this issue if needed." in github.issue_comments_log[0][1]


def test_issue_file_resolves_relative_to_repository_root():
    config = config_without_validation()
    issue_file = _resolve_issue_file(config, Path("demo/issues/isolated_text_fixture.md"))
    assert issue_file == ROOT / "demo/issues/isolated_text_fixture.md"

