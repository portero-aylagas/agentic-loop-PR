from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import tempfile

from jsonschema import Draft202012Validator

from .command import CommandRunner
from .config import load_schema


@dataclass(frozen=True)
class RoleResult:
    role: str
    data: dict[str, Any]


class CodexProvider:
    def __init__(
        self,
        *,
        executable: str = "codex",
        model: str | None = None,
        extra_args: list[str] | None = None,
        cwd: Path | None = None,
        runner: CommandRunner | None = None,
    ):
        self.executable = executable
        self.model = model
        self.extra_args = extra_args or []
        self.cwd = cwd
        self.runner = runner or CommandRunner()

    def run_role(
        self,
        *,
        role: str,
        prompt_path: Path,
        schema_path: Path,
        payload: dict[str, Any],
    ) -> RoleResult:
        prompt = prompt_path.read_text(encoding="utf-8")
        schema = load_schema(schema_path)
        input_text = _build_input(prompt, schema, payload)
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "last-message.json"
            args = [
                self.executable,
                "exec",
                "--cd",
                str(self.cwd or Path.cwd()),
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
            ]
            if self.model:
                args.extend(["--model", self.model])
            args.extend([*self.extra_args, "-"])
            self.runner.run(args, input_text=input_text)
            data = _parse_json_object(output_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(data)
        return RoleResult(role=role, data=data)


def _build_input(prompt: str, schema: dict[str, Any], payload: dict[str, Any]) -> str:
    return "\n\n".join([
        prompt.strip(),
        "Return one JSON object that validates against this schema:",
        json.dumps(schema, sort_keys=True),
        "Input:",
        json.dumps(payload, sort_keys=True),
    ])


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end < start:
            raise
        raw = json.loads(stripped[start : end + 1])
    if not isinstance(raw, dict):
        raise ValueError("codex output must be a JSON object")
    return raw
