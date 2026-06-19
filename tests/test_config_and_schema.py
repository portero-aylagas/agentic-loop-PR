from pathlib import Path

import pytest
from jsonschema import ValidationError

from agentic_loop.config import ConfigError, load_config, schema_path, validate_all, validate_role_output

ROOT = Path(__file__).resolve().parents[1]


def test_default_config_validates():
    config = validate_all(ROOT / "agentic-loop.yaml")
    assert config.base_branch == "main"
    assert config.remote == "origin"
    assert config.repository_root == ROOT
    assert config.branch_prefix == "agentic/issue-"
    assert config.codex_executable == "codex.cmd"
    assert config.codex_model is None
    assert config.assets_dir == ROOT / "agentic_loop_assets"
    assert config.policy["max_changed_files"] == 20
    assert config.policy["max_diff_lines"] == 1000
    assert config.validation_commands == ["python -m pytest", "python -m agentic_loop validate"]
    assert config.trace == {"mode": "committed", "artifact_dir": "agentic-loop-traces"}


def test_config_resolves_portable_paths(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    config_file = tmp_path / "agentic-loop.yaml"
    config_file.write_text(
        """
assets_dir: assets
repository:
  root: target-repo
  remote: upstream
  base_branch: trunk
  branch_prefix: agentic/issue-
  protected_paths: []
github:
  ready_label: ready
  demo_label: demo
codex:
  executable: codex
  model: gpt-5
  extra_args: []
policy:
  max_review_cycles: 1
  max_findings_per_cycle: 1
  stagnant_cycles: 1
""",
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.repository_root == tmp_path / "target-repo"
    assert config.remote == "upstream"
    assert config.assets_dir == assets


def test_config_uses_bundled_assets_when_local_assets_are_absent(tmp_path):
    config_file = tmp_path / "agentic-loop.yaml"
    config_file.write_text(
        """
repository:
  root: .
  remote: origin
  base_branch: main
  branch_prefix: agentic/issue-
  protected_paths: []
github:
  ready_label: ready
  demo_label: demo
codex:
  executable: codex
  extra_args: []
policy:
  max_review_cycles: 1
  max_findings_per_cycle: 1
  stagnant_cycles: 1
""",
        encoding="utf-8",
    )
    config = validate_all(config_file)
    assert config.assets_dir.name == "agentic_loop_assets"
    assert schema_path(config, "review").exists()
    assert config.policy["max_changed_files"] == 0
    assert config.policy["max_diff_lines"] == 0
    assert config.validation_commands == []


def test_config_validation_rejects_bad_policy(tmp_path):
    bad = tmp_path / "agentic-loop.yaml"
    bad.write_text(
        """
repository:
  root: .
  remote: origin
  base_branch: main
  branch_prefix: agentic/issue-
  protected_paths: []
github:
  ready_label: ready
  demo_label: demo
codex:
  extra_args: []
policy:
  max_review_cycles: 0
  max_findings_per_cycle: 1
  stagnant_cycles: 1
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(bad)


def test_config_validation_rejects_bad_diff_limits(tmp_path):
    bad = tmp_path / "agentic-loop.yaml"
    bad.write_text(
        """
repository:
  root: .
  remote: origin
  base_branch: main
  branch_prefix: agentic/issue-
  protected_paths: []
github:
  ready_label: ready
  demo_label: demo
codex:
  extra_args: []
policy:
  max_review_cycles: 1
  max_findings_per_cycle: 1
  stagnant_cycles: 1
  max_changed_files: 0
  max_diff_lines: many
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(bad)


def test_config_validation_rejects_bad_validation_commands(tmp_path):
    bad = tmp_path / "agentic-loop.yaml"
    bad.write_text(
        """
repository:
  root: .
  remote: origin
  base_branch: main
  branch_prefix: agentic/issue-
  protected_paths: []
github:
  ready_label: ready
  demo_label: demo
codex:
  extra_args: []
policy:
  max_review_cycles: 1
  max_findings_per_cycle: 1
  stagnant_cycles: 1
validation:
  commands:
    - ""
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(bad)


def test_config_validation_rejects_bad_trace(tmp_path):
    bad = tmp_path / "agentic-loop.yaml"
    bad.write_text(
        """
repository:
  root: .
  remote: origin
  base_branch: main
  branch_prefix: agentic/issue-
  protected_paths: []
github:
  ready_label: ready
  demo_label: demo
codex:
  extra_args: []
policy:
  max_review_cycles: 1
  max_findings_per_cycle: 1
  stagnant_cycles: 1
trace:
  mode: noisy
  artifact_dir: ../traces
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_config(bad)


def test_role_output_validation_accepts_valid_review():
    config = validate_all(ROOT / "agentic-loop.yaml")
    validate_role_output(
        schema_path(config, "review"),
        {"status": "approved", "summary": "ok", "findings": []},
    )
    validate_role_output(
        schema_path(config, "review"),
        {
            "status": "blocking",
            "summary": "needs work",
            "findings": [
                {
                    "title": "missing file",
                    "path": "tests/agentic_demo/sample.txt",
                    "message": "Create the expected fixture file.",
                    "severity": "medium",
                    "conflicting": False,
                }
            ],
        },
    )


def test_role_output_validation_rejects_invalid_review():
    config = validate_all(ROOT / "agentic-loop.yaml")
    with pytest.raises(ValidationError):
        validate_role_output(schema_path(config, "review"), {"status": "approved", "summary": "ok"})
    with pytest.raises(ValidationError):
        validate_role_output(
            schema_path(config, "review"),
            {
                "status": "blocking",
                "summary": "needs work",
                "findings": [
                    {
                        "title": "missing file",
                        "path": "tests/agentic_demo/sample.txt",
                        "message": "Create the expected fixture file.",
                        "severity": "medium",
                    }
                ],
            },
        )
