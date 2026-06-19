from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .command import CommandRunner


@dataclass(frozen=True)
class DiffFile:
    path: str
    status: str


@dataclass(frozen=True)
class DiffStats:
    changed_files: int
    diff_lines: int


@dataclass(frozen=True)
class StatusFile:
    path: str
    index_status: str
    worktree_status: str

    @property
    def is_dirty(self) -> bool:
        return self.index_status != " " or self.worktree_status != " "


class GitClient:
    def __init__(self, runner: CommandRunner | None = None, cwd: str | None = None, remote: str = "origin"):
        self.runner = runner or CommandRunner()
        self.cwd = cwd
        self.remote = remote

    def with_cwd(self, cwd: str | Path) -> GitClient:
        return GitClient(runner=self.runner, cwd=str(cwd), remote=self.remote)

    def current_branch(self) -> str:
        return self.runner.run(["git", "branch", "--show-current"], cwd=self.cwd).stdout.strip()

    def checkout_or_create_branch(self, branch: str, base: str) -> None:
        exists = self.runner.run(["git", "rev-parse", "--verify", branch], cwd=self.cwd, check=False).returncode == 0
        if exists:
            self.runner.run(["git", "checkout", branch], cwd=self.cwd)
            return
        self.runner.run(["git", "fetch", self.remote, base], cwd=self.cwd, check=False)
        self.runner.run(["git", "checkout", "-B", branch, f"{self.remote}/{base}"], cwd=self.cwd)

    def prepare_issue_worktree(self, *, issue: int, branch: str, base: str, repo_root: Path) -> Path:
        worktree_path = repo_root / ".worktrees" / f"agentic-issue-{issue}"
        remote_ref = self.remote_ref(base)
        self.runner.run(["git", "fetch", self.remote, base], cwd=self.cwd)
        if worktree_path.exists():
            self._verify_worktree_branch(worktree_path, branch)
        else:
            worktree_path.parent.mkdir(parents=True, exist_ok=True)
            branch_exists = self.runner.run(["git", "rev-parse", "--verify", branch], cwd=self.cwd, check=False).returncode == 0
            args = ["git", "worktree", "add", str(worktree_path)]
            if branch_exists:
                args.append(branch)
            else:
                args.extend(["-b", branch, remote_ref])
            self.runner.run(args, cwd=self.cwd)

        worktree = self.with_cwd(worktree_path)
        if worktree.has_changes():
            raise RuntimeError(f"target worktree has uncommitted changes: {worktree_path}")
        return worktree_path

    def remote_ref(self, base: str) -> str:
        return f"{self.remote}/{base}"

    def sync_base(self, base: str) -> None:
        remote_ref = self.remote_ref(base)
        self.runner.run(["git", "fetch", self.remote, base], cwd=self.cwd)
        exists = self.runner.run(["git", "rev-parse", "--verify", base], cwd=self.cwd, check=False).returncode == 0
        if not exists:
            self.runner.run(["git", "branch", base, remote_ref], cwd=self.cwd)
            return

        local_sha = self.runner.run(["git", "rev-parse", base], cwd=self.cwd).stdout.strip()
        remote_sha = self.runner.run(["git", "rev-parse", remote_ref], cwd=self.cwd).stdout.strip()
        if local_sha == remote_sha:
            return

        can_fast_forward = self.runner.run(["git", "merge-base", "--is-ancestor", base, remote_ref], cwd=self.cwd, check=False).returncode == 0
        if not can_fast_forward:
            raise RuntimeError(f"local {base} has diverged from {remote_ref}; resolve it before running automation")

        if self.current_branch() == base:
            self.runner.run(["git", "merge", "--ff-only", remote_ref], cwd=self.cwd)
        else:
            self.runner.run(["git", "branch", "--force", base, remote_ref], cwd=self.cwd)

    def changed_files(self, base: str = "HEAD") -> list[DiffFile]:
        result = self.runner.run(["git", "diff", "--name-status", base], cwd=self.cwd)
        return parse_name_status(result.stdout)

    def diff_stats(self, base: str = "HEAD") -> DiffStats:
        changed_files = len(self.changed_files(base))
        result = self.runner.run(["git", "diff", "--numstat", base], cwd=self.cwd)
        return DiffStats(changed_files=changed_files, diff_lines=parse_numstat_lines(result.stdout))

    def has_changes(self) -> bool:
        return bool(self.runner.run(["git", "status", "--porcelain"], cwd=self.cwd).stdout.strip())

    def status_files(self) -> list[StatusFile]:
        result = self.runner.run(["git", "status", "--porcelain"], cwd=self.cwd)
        return parse_status(result.stdout)

    def stage_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        self.runner.run(["git", "add", "--", *paths], cwd=self.cwd)

    def add_all(self) -> None:
        self.runner.run(["git", "add", "--all"], cwd=self.cwd)

    def commit(self, message: str) -> bool:
        if not self.has_changes():
            return False
        self.add_all()
        self.runner.run(["git", "commit", "-m", message], cwd=self.cwd)
        return True

    def commit_staged(self, message: str) -> bool:
        staged = [item for item in self.status_files() if item.index_status != " "]
        if not staged:
            return False
        self.runner.run(["git", "commit", "-m", message], cwd=self.cwd)
        return True

    def push_branch(self, branch: str) -> None:
        self.runner.run(["git", "push", "-u", self.remote, branch], cwd=self.cwd)

    def repo_root(self) -> Path:
        return Path(self.runner.run(["git", "rev-parse", "--show-toplevel"], cwd=self.cwd).stdout.strip())

    def _verify_worktree_branch(self, worktree_path: Path, branch: str) -> None:
        self.runner.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=str(worktree_path))
        current = self.runner.run(["git", "branch", "--show-current"], cwd=str(worktree_path)).stdout.strip()
        if current != branch:
            raise RuntimeError(f"target worktree {worktree_path} is on {current!r}, expected {branch!r}")


def parse_name_status(output: str) -> list[DiffFile]:
    files: list[DiffFile] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        path = parts[-1]
        files.append(DiffFile(path=path, status=status))
    return files


def parse_status(output: str) -> list[StatusFile]:
    files: list[StatusFile] = []
    for line in output.splitlines():
        if not line:
            continue
        if len(line) < 4:
            continue
        index_status = line[0]
        worktree_status = line[1]
        raw_path = line[3:]
        path = raw_path.split(" -> ")[-1] if " -> " in raw_path else raw_path
        files.append(StatusFile(path=path, index_status=index_status, worktree_status=worktree_status))
    return files


def parse_numstat_lines(output: str) -> int:
    total = 0
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        total += _numstat_value(parts[0])
        total += _numstat_value(parts[1])
    return total


def _numstat_value(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0
