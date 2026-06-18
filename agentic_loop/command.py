from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Sequence


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class CommandError(RuntimeError):
    def __init__(self, result: CommandResult):
        self.result = result
        super().__init__(f"command failed ({result.returncode}): {' '.join(result.args)}\n{result.stderr.strip()}")


class CommandRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        input_text: str | None = None,
        cwd: str | None = None,
        check: bool = True,
    ) -> CommandResult:
        if not args:
            raise ValueError("args must not be empty")
        completed = subprocess.run(
            list(args),
            input=input_text,
            cwd=cwd,
            text=True,
            shell=False,
            capture_output=True,
            check=False,
        )
        result = CommandResult(tuple(str(arg) for arg in args), completed.returncode, completed.stdout, completed.stderr)
        if check and result.returncode != 0:
            raise CommandError(result)
        return result
