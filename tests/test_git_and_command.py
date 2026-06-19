import subprocess

from agentic_loop.command import CommandRunner
from agentic_loop.git_client import GitClient, parse_name_status, parse_numstat_lines, parse_status
from agentic_loop.github_cli import GitHubCli
from agentic_loop.validation import parse_command


def test_parse_name_status():
    parsed = parse_name_status("M\tREADME.md\nA\ttests/demo.py\nR100\told.py\tnew.py\n")
    assert [(item.status, item.path) for item in parsed] == [("M", "README.md"), ("A", "tests/demo.py"), ("R100", "new.py")]


def test_parse_numstat_lines():
    assert parse_numstat_lines("2\t3\tREADME.md\n-\t-\timage.png\n0\t4\ttests/demo.py\n") == 9


def test_parse_status_supports_modified_added_deleted_and_renamed():
    parsed = parse_status(" M README.md\n?? tests/demo.py\n D old.txt\nR  before.py -> after.py\n")
    assert [(item.index_status, item.worktree_status, item.path) for item in parsed] == [
        (" ", "M", "README.md"),
        ("?", "?", "tests/demo.py"),
        (" ", "D", "old.txt"),
        ("R", " ", "after.py"),
    ]


def test_command_runner_uses_list_args_and_stdin_for_untrusted_text(monkeypatch):
    calls = {}

    def fake_run(args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, "{}", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    untrusted = "hello; rm -rf nope"
    CommandRunner().run(["codex", "exec", "-"], input_text=untrusted)
    assert calls["args"] == ["codex", "exec", "-"]
    assert calls["kwargs"]["input"] == untrusted
    assert calls["kwargs"]["shell"] is False


def test_validation_command_parser_returns_argv():
    assert parse_command("python -m pytest") == ["python", "-m", "pytest"]
    assert parse_command('"C:\\Program Files\\Python\\python.exe" -m pytest') == ["C:\\Program Files\\Python\\python.exe", "-m", "pytest"]


def test_git_client_uses_configured_remote():
    calls = []

    class FakeRunner:
        def run(self, args, *, cwd=None, check=True):
            calls.append(list(args))
            if args[:3] == ["git", "rev-parse", "--verify"]:
                return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    git = GitClient(runner=FakeRunner(), remote="upstream")
    git.checkout_or_create_branch("agentic/issue-7", "trunk")
    git.push_branch("agentic/issue-7")
    assert ["git", "fetch", "upstream", "trunk"] in calls
    assert ["git", "checkout", "-B", "agentic/issue-7", "upstream/trunk"] in calls
    assert ["git", "push", "-u", "upstream", "agentic/issue-7"] in calls


def test_git_client_sync_base_fast_forwards_local_base():
    calls = []

    class FakeRunner:
        def run(self, args, *, cwd=None, check=True):
            calls.append(list(args))
            if args[:3] == ["git", "rev-parse", "--verify"]:
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            if args == ["git", "rev-parse", "main"]:
                return type("Result", (), {"returncode": 0, "stdout": "local\n", "stderr": ""})()
            if args == ["git", "rev-parse", "origin/main"]:
                return type("Result", (), {"returncode": 0, "stdout": "remote\n", "stderr": ""})()
            if args[:3] == ["git", "merge-base", "--is-ancestor"]:
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            if args == ["git", "branch", "--show-current"]:
                return type("Result", (), {"returncode": 0, "stdout": "feature\n", "stderr": ""})()
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    GitClient(runner=FakeRunner()).sync_base("main")
    assert ["git", "fetch", "origin", "main"] in calls
    assert ["git", "branch", "--force", "main", "origin/main"] in calls


def test_git_client_sync_base_aborts_when_local_base_diverged():
    class FakeRunner:
        def run(self, args, *, cwd=None, check=True):
            if args[:3] == ["git", "rev-parse", "--verify"]:
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            if args == ["git", "rev-parse", "main"]:
                return type("Result", (), {"returncode": 0, "stdout": "local\n", "stderr": ""})()
            if args == ["git", "rev-parse", "origin/main"]:
                return type("Result", (), {"returncode": 0, "stdout": "remote\n", "stderr": ""})()
            if args[:3] == ["git", "merge-base", "--is-ancestor"]:
                return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    try:
        GitClient(runner=FakeRunner()).sync_base("main")
    except RuntimeError as exc:
        assert "diverged" in str(exc)
    else:
        raise AssertionError("diverged base should abort")


def test_git_client_stages_specific_paths():
    calls = []

    class FakeRunner:
        def run(self, args, *, cwd=None, check=True):
            calls.append((list(args), cwd, check))
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    GitClient(runner=FakeRunner(), cwd="repo").stage_paths(["README.md", "tests/demo.py"])
    assert calls == [(["git", "add", "--", "README.md", "tests/demo.py"], "repo", True)]


def test_git_client_prepares_new_issue_worktree_from_remote_base(tmp_path):
    calls = []

    class FakeRunner:
        def run(self, args, *, cwd=None, check=True):
            calls.append((list(args), cwd, check))
            if args[:3] == ["git", "rev-parse", "--verify"]:
                return type("Result", (), {"returncode": 1, "stdout": "", "stderr": ""})()
            if args[:2] == ["git", "status"]:
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    root = tmp_path / "repo"
    worktree = GitClient(runner=FakeRunner(), cwd=str(root), remote="upstream").prepare_issue_worktree(
        issue=7,
        branch="agentic/issue-7",
        base="trunk",
        repo_root=root,
    )
    expected = root / ".worktrees" / "agentic-issue-7"
    assert worktree == expected
    assert (["git", "fetch", "upstream", "trunk"], str(root), True) in calls
    assert (["git", "worktree", "add", str(expected), "-b", "agentic/issue-7", "upstream/trunk"], str(root), True) in calls
    assert (["git", "status", "--porcelain"], str(expected), True) in calls


def test_git_client_reuses_clean_issue_worktree_on_expected_branch(tmp_path):
    calls = []

    class FakeRunner:
        def run(self, args, *, cwd=None, check=True):
            calls.append((list(args), cwd, check))
            if args == ["git", "branch", "--show-current"]:
                return type("Result", (), {"returncode": 0, "stdout": "agentic/issue-7\n", "stderr": ""})()
            if args[:2] == ["git", "status"]:
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    root = tmp_path / "repo"
    expected = root / ".worktrees" / "agentic-issue-7"
    expected.mkdir(parents=True)
    worktree = GitClient(runner=FakeRunner(), cwd=str(root)).prepare_issue_worktree(
        issue=7,
        branch="agentic/issue-7",
        base="main",
        repo_root=root,
    )
    assert worktree == expected
    assert not any(call[0][:3] == ["git", "worktree", "add"] for call in calls)
    assert (["git", "rev-parse", "--is-inside-work-tree"], str(expected), True) in calls
    assert (["git", "status", "--porcelain"], str(expected), True) in calls


def test_github_cli_label_helpers_use_non_throwing_edit_commands():
    calls = []

    class FakeRunner:
        def run(self, args, *, check=True):
            calls.append((list(args), check))
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    github = GitHubCli(runner=FakeRunner())
    assert github.add_issue_label(7, "agentic:planning")
    assert github.remove_issue_label(7, "agentic:implementing")
    assert github.add_pr_label(11, "agentic:reviewing")
    assert github.remove_pr_label(11, "agentic:remediating")
    assert calls == [
        (["gh", "issue", "edit", "7", "--add-label", "agentic:planning"], False),
        (["gh", "issue", "edit", "7", "--remove-label", "agentic:implementing"], False),
        (["gh", "pr", "edit", "11", "--add-label", "agentic:reviewing"], False),
        (["gh", "pr", "edit", "11", "--remove-label", "agentic:remediating"], False),
    ]


def test_github_cli_label_helpers_return_false_on_failures():
    class FakeRunner:
        def run(self, args, *, check=True):
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "permission denied"})()

    github = GitHubCli(runner=FakeRunner())
    assert not github.ensure_label("agentic:planning")
    assert not github.add_issue_label(7, "agentic:planning")
    assert not github.remove_issue_label(7, "agentic:implementing")


def test_github_cli_label_create_already_exists_is_success():
    class FakeRunner:
        def run(self, args, *, check=True):
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "already exists"})()

    assert GitHubCli(runner=FakeRunner()).ensure_label("agentic:planning")


def test_github_cli_reads_and_edits_pr_body():
    calls = []

    class FakeRunner:
        def run(self, args, *, check=True):
            calls.append((list(args), check))
            if args[:3] == ["gh", "pr", "view"]:
                return type("Result", (), {"returncode": 0, "stdout": '{"body":"hello"}', "stderr": ""})()
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    github = GitHubCli(runner=FakeRunner())
    assert github.pr_body(11) == "hello"
    github.edit_pr_body(11, "updated")
    assert calls == [
        (["gh", "pr", "view", "11", "--json", "body"], True),
        (["gh", "pr", "edit", "11", "--body", "updated"], True),
    ]
