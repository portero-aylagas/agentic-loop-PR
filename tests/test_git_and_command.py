import subprocess

from agentic_loop.command import CommandRunner
from agentic_loop.git_client import GitClient, parse_name_status


def test_parse_name_status():
    parsed = parse_name_status("M\tREADME.md\nA\ttests/demo.py\nR100\told.py\tnew.py\n")
    assert [(item.status, item.path) for item in parsed] == [("M", "README.md"), ("A", "tests/demo.py"), ("R100", "new.py")]


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
