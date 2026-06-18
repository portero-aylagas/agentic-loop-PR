from __future__ import annotations

from pathlib import Path
import argparse

from .codex_provider import CodexProvider
from .config import ConfigError, validate_all
from .controller import Controller
from .git_client import GitClient
from .github_cli import GitHubCli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentic-loop")
    parser.add_argument("--config", default="agentic-loop.yaml", help="Path to agentic-loop.yaml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate config, prompts, and schemas")
    validate.add_argument("--config", dest="command_config", help="Path to agentic-loop.yaml")

    run = subparsers.add_parser("run", help="Run the issue-to-PR loop")
    run.add_argument("--issue", type=int, required=True, help="GitHub issue number")
    run.add_argument("--config", dest="command_config", help="Path to agentic-loop.yaml")
    run.add_argument("--force", action="store_true", help="Ignore terminal workflow state and run again")

    seed = subparsers.add_parser("seed-demo", help="Create a fresh demo issue")
    seed.add_argument("--config", dest="command_config", help="Path to agentic-loop.yaml")
    seed.add_argument("--issue-file", default="demo/issues/isolated_text_fixture.md", help="Issue body file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = args.command_config or args.config
    try:
        if args.command == "validate":
            validate_all(config_path)
            print("validation ok")
            return 0
        if args.command == "seed-demo":
            config = validate_all(config_path)
            issue = seed_demo(config, _resolve_issue_file(config, Path(args.issue_file)))
            print(f"created issue #{issue.number}: {issue.url}")
            return 0
        if args.command == "run":
            config = validate_all(config_path)
            result = run_controller(config, args.issue, force=args.force)
            pr = f"PR #{result.pr}" if result.pr is not None else "no PR"
            print(f"handoff: issue #{result.issue}, {pr}, branch {result.branch}, reason: {result.decision.reason}")
            return 0
    except ConfigError as exc:
        parser.exit(2, f"configuration error: {exc}\n")
    return 1


def seed_demo(config, issue_file: Path, github=None):
    github = github or GitHubCli()
    labels = []
    failed_labels = []
    for label in (config.ready_label, config.demo_label):
        if github.ensure_label(label):
            labels.append(label)
        else:
            failed_labels.append(label)
    body = issue_file.read_text(encoding="utf-8")
    issue = github.create_issue("Agentic loop demo: isolated text fixture", body, labels)
    if failed_labels:
        github.comment_issue(issue.number, f"Label creation failed; apply manually if needed: {', '.join(failed_labels)}")
    return issue


def run_controller(config, issue_number: int, *, force: bool = False):
    controller = Controller(
        config=config,
        github=GitHubCli(),
        git=GitClient(cwd=str(config.repository_root), remote=config.remote),
        codex=CodexProvider(
            executable=config.codex_executable,
            model=config.codex_model,
            extra_args=config.codex_extra_args,
            cwd=config.repository_root,
        ),
    )
    return controller.run(issue_number, force=force)


def _resolve_issue_file(config, issue_file: Path) -> Path:
    if issue_file.is_absolute():
        return issue_file
    repo_relative = config.repository_root / issue_file
    if repo_relative.exists():
        return repo_relative
    return config.path.resolve().parent / issue_file

