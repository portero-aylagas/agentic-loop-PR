from __future__ import annotations

from dataclasses import dataclass
import shlex
import time
from pathlib import Path
from typing import Any

from .command import CommandRunner


@dataclass(frozen=True)
class ValidationRun:
    command: str
    args: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "args": list(self.args),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": round(self.duration_seconds, 3),
        }


def run_validation_commands(commands: list[str], *, cwd: Path, runner: CommandRunner | None = None) -> dict[str, Any]:
    if not commands:
        return {"skipped": True, "passed": True, "commands": []}

    command_runner = runner or CommandRunner()
    runs = []
    for command in commands:
        args = parse_command(command)
        started = time.perf_counter()
        result = command_runner.run(args, cwd=str(cwd), check=False)
        duration = time.perf_counter() - started
        runs.append(ValidationRun(command, result.args, result.returncode, result.stdout, result.stderr, duration).to_dict())
    return {
        "skipped": False,
        "passed": all(run["exit_code"] == 0 for run in runs),
        "commands": runs,
    }


def parse_command(command: str) -> list[str]:
    args = shlex.split(command, posix=False)
    cleaned = [_strip_matching_quotes(arg) for arg in args]
    if not cleaned:
        raise ValueError("validation command must not be empty")
    return cleaned


def validation_comment(results: dict[str, Any]) -> str:
    commands = list(results.get("commands") or [])
    if not commands:
        return "Validation skipped: no commands configured."
    status = "passed" if results.get("passed") else "failed"
    lines = [f"Validation {status}: {len(commands)} command(s)."]
    for item in commands:
        command = str(item.get("command", ""))
        exit_code = int(item.get("exit_code", 0))
        duration = float(item.get("duration_seconds", 0))
        command_status = "passed" if exit_code == 0 else f"failed with exit {exit_code}"
        lines.append(f"- `{command}` {command_status} in {duration:.2f}s")
    return "\n".join(lines)


def validation_failed(results: dict[str, Any] | None) -> bool:
    return bool(results) and not bool(results.get("skipped")) and not bool(results.get("passed"))


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
