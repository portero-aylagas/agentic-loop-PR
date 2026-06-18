from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .command import CommandRunner


@dataclass(frozen=True)
class DiffFile:
    path: str
    status: str


class GitClient:
    def __init__(self, runner: CommandRunner | None = None, cwd: str | None = None, remote: str = "origin"):
        self.runner = runner or CommandRunner()
        self.cwd = cwd
        self.remote = remote

    def current_branch(self) -> str:
        return self.runner.run(["git", "branch", "--show-current"], cwd=self.cwd).stdout.strip()

    def checkout_or_create_branch(self, branch: str, base: str) -> None:
        exists = self.runner.run(["git", "rev-parse", "--verify", branch], cwd=self.cwd, check=False).returncode == 0
        if exists:
            self.runner.run(["git", "checkout", branch], cwd=self.cwd)
            return
        self.runner.run(["git", "fetch", self.remote, base], cwd=self.cwd, check=False)
        self.runner.run(["git", "checkout", "-B", branch, f"{self.remote}/{base}"], cwd=self.cwd)

    def changed_files(self, base: str = "HEAD") -> list[DiffFile]:
        result = self.runner.run(["git", "diff", "--name-status", base], cwd=self.cwd)
        return parse_name_status(result.stdout)

    def has_changes(self) -> bool:
        return bool(self.runner.run(["git", "status", "--porcelain"], cwd=self.cwd).stdout.strip())

    def add_all(self) -> None:
        self.runner.run(["git", "add", "--all"], cwd=self.cwd)

    def commit(self, message: str) -> bool:
        if not self.has_changes():
            return False
        self.add_all()
        self.runner.run(["git", "commit", "-m", message], cwd=self.cwd)
        return True

    def push_branch(self, branch: str) -> None:
        self.runner.run(["git", "push", "-u", self.remote, branch], cwd=self.cwd)

    def repo_root(self) -> Path:
        return Path(self.runner.run(["git", "rev-parse", "--show-toplevel"], cwd=self.cwd).stdout.strip())


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
