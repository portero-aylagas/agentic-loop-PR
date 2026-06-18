from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from importlib import resources
import json

import yaml
from jsonschema import Draft202012Validator


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class LoopConfig:
    path: Path
    data: dict[str, Any]

    @property
    def base_branch(self) -> str:
        return str(self.data["repository"]["base_branch"])

    @property
    def repository_root(self) -> Path:
        return _resolve_from_config(self.path, str(self.data["repository"].get("root", ".")))

    @property
    def remote(self) -> str:
        return str(self.data["repository"].get("remote", "origin"))

    @property
    def branch_prefix(self) -> str:
        return str(self.data["repository"]["branch_prefix"])

    @property
    def protected_paths(self) -> list[str]:
        return list(self.data["repository"].get("protected_paths", []))

    @property
    def ready_label(self) -> str:
        return str(self.data["github"]["ready_label"])

    @property
    def demo_label(self) -> str:
        return str(self.data["github"]["demo_label"])

    @property
    def codex_executable(self) -> str:
        return str(self.data["codex"].get("executable", "codex"))

    @property
    def codex_model(self) -> str | None:
        model = self.data["codex"].get("model")
        return str(model) if model else None

    @property
    def codex_extra_args(self) -> list[str]:
        return [str(arg) for arg in self.data["codex"].get("extra_args", [])]

    @property
    def policy(self) -> dict[str, Any]:
        return {**DEFAULT_POLICY, **self.data["policy"]}

    @property
    def synthetic_review(self) -> dict[str, Any]:
        return dict(self.data.get("synthetic_review", {}))

    @property
    def validation_commands(self) -> list[str]:
        validation = self.data.get("validation", {})
        if not isinstance(validation, dict):
            return []
        return [str(command) for command in validation.get("commands", [])]

    @property
    def assets_dir(self) -> Path:
        configured = self.data.get("assets_dir")
        if configured:
            return _resolve_from_config(self.path, str(configured))
        local_assets = project_root_from_config(self.path) / "agentic_loop_assets"
        if local_assets.exists():
            return local_assets
        return Path(str(resources.files("agentic_loop_assets")))


REQUIRED_PROMPTS = {
    "planner": "planner.md",
    "implementer": "implementer.md",
    "reviewer": "reviewer.md",
    "remediator": "remediator.md",
}

REQUIRED_SCHEMAS = {
    "plan": "plan.schema.json",
    "implementation": "implementation.schema.json",
    "review": "review.schema.json",
    "remediation": "remediation.schema.json",
}

DEFAULT_POLICY = {
    "max_changed_files": 0,
    "max_diff_lines": 0,
}


def project_root_from_config(config_path: Path) -> Path:
    return config_path.resolve().parent


def assets_root(config_path: Path) -> Path:
    config = load_config(config_path)
    return config.assets_dir


def load_config(path: str | Path = "agentic-loop.yaml") -> LoopConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"config not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError("config must be a mapping")
    _validate_config_shape(raw)
    return LoopConfig(config_path, raw)


def validate_all(path: str | Path = "agentic-loop.yaml") -> LoopConfig:
    config = load_config(path)
    root = config.assets_dir
    _validate_prompts(root / "prompts")
    _validate_schemas(root / "schemas")
    return config


def schema_path(config: LoopConfig, name: str) -> Path:
    try:
        filename = REQUIRED_SCHEMAS[name]
    except KeyError as exc:
        raise ConfigError(f"unknown schema: {name}") from exc
    return config.assets_dir / "schemas" / filename


def prompt_path(config: LoopConfig, name: str) -> Path:
    try:
        filename = REQUIRED_PROMPTS[name]
    except KeyError as exc:
        raise ConfigError(f"unknown prompt: {name}") from exc
    return config.assets_dir / "prompts" / filename


def load_schema(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"schema not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"schema is invalid JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"schema must be an object: {path}")
    Draft202012Validator.check_schema(raw)
    return raw


def validate_role_output(schema_file: Path, output: dict[str, Any]) -> None:
    schema = load_schema(schema_file)
    Draft202012Validator(schema).validate(output)


def _validate_config_shape(raw: dict[str, Any]) -> None:
    for section in ("repository", "github", "codex", "policy"):
        if not isinstance(raw.get(section), dict):
            raise ConfigError(f"missing config section: {section}")
    repository = raw["repository"]
    github = raw["github"]
    policy = raw["policy"]
    _require_str(repository, "base_branch", "repository")
    _require_str(repository, "branch_prefix", "repository")
    if "root" in repository:
        _require_str(repository, "root", "repository")
    if "remote" in repository:
        _require_str(repository, "remote", "repository")
    if not isinstance(repository.get("protected_paths", []), list):
        raise ConfigError("repository.protected_paths must be a list")
    if "assets_dir" in raw and (not isinstance(raw["assets_dir"], str) or not raw["assets_dir"].strip()):
        raise ConfigError("assets_dir must be a non-empty string")
    if "validation" in raw:
        if not isinstance(raw["validation"], dict):
            raise ConfigError("validation must be a mapping")
        commands = raw["validation"].get("commands", [])
        if not isinstance(commands, list) or any(not isinstance(command, str) or not command.strip() for command in commands):
            raise ConfigError("validation.commands must be a list of non-empty strings")
    _require_str(github, "ready_label", "github")
    _require_str(github, "demo_label", "github")
    for key in ("max_review_cycles", "max_findings_per_cycle", "stagnant_cycles"):
        if not isinstance(policy.get(key), int) or policy[key] < 1:
            raise ConfigError(f"policy.{key} must be a positive integer")
    for key in ("max_changed_files", "max_diff_lines"):
        if key in policy and (not isinstance(policy[key], int) or policy[key] < 1):
            raise ConfigError(f"policy.{key} must be a positive integer")
    if not isinstance(raw["codex"].get("extra_args", []), list):
        raise ConfigError("codex.extra_args must be a list")
    if "model" in raw["codex"] and (not isinstance(raw["codex"]["model"], str) or not raw["codex"]["model"].strip()):
        raise ConfigError("codex.model must be a non-empty string")


def _require_str(section: dict[str, Any], key: str, section_name: str) -> None:
    if not isinstance(section.get(key), str) or not section[key].strip():
        raise ConfigError(f"{section_name}.{key} must be a non-empty string")


def _resolve_from_config(config_path: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (project_root_from_config(config_path) / path).resolve()


def _validate_prompts(prompt_dir: Path) -> None:
    for name, filename in REQUIRED_PROMPTS.items():
        path = prompt_dir / filename
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ConfigError(f"prompt not found: {name}: {path}") from exc
        if not text.strip():
            raise ConfigError(f"prompt is empty: {name}: {path}")


def _validate_schemas(schema_dir: Path) -> None:
    for name, filename in REQUIRED_SCHEMAS.items():
        load_schema(schema_dir / filename)
