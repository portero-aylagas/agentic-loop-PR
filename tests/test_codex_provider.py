from pathlib import Path

from agentic_loop.codex_provider import CodexProvider
from agentic_loop.command import CommandResult
from agentic_loop.config import validate_all, prompt_path, schema_path

ROOT = Path(__file__).resolve().parents[1]


class FakeRunner:
    def __init__(self):
        self.args = None
        self.input_text = None

    def run(self, args, *, input_text=None, cwd=None, check=True):
        self.args = list(args)
        self.input_text = input_text
        output_file = Path(self.args[self.args.index("--output-last-message") + 1])
        output_file.write_text('{"summary":"ok","steps":[{"description":"do it","verify":"test it"}],"risks":[]}', encoding="utf-8")
        return CommandResult(tuple(args), 0, "", "")


def test_codex_provider_uses_stdin_schema_and_output_file():
    config = validate_all(ROOT / "agentic-loop.yaml")
    runner = FakeRunner()
    result = CodexProvider(runner=runner, cwd=ROOT, model=config.codex_model).run_role(
        role="planner",
        prompt_path=prompt_path(config, "planner"),
        schema_path=schema_path(config, "plan"),
        payload={"issue": {"body": "hello; not shell"}},
    )
    assert result.data["summary"] == "ok"
    assert runner.args[:6] == ["codex", "exec", "--cd", str(ROOT), "--output-schema", str(schema_path(config, "plan"))]
    assert runner.args[runner.args.index("--model") + 1] == "gpt-5"
    assert runner.args[-1] == "-"
    assert "hello; not shell" in runner.input_text
    assert "hello; not shell" not in runner.args
