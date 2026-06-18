# Agentic Loop Demo

Standalone Python CLI demo for a Windows-local agentic issue-to-PR loop using local `gh` auth and local `codex` auth.

The controller starts from a real GitHub issue, creates or reuses one branch, opens or reuses one PR, runs review/remediation cycles, posts hidden workflow-state comments, and stops at human handoff. It never merges PRs or enables auto-merge.

## What You Need

- Windows with PowerShell.
- Python 3.11 or newer.
- Git installed and available on `PATH`.
- GitHub CLI `gh` installed, authenticated, and authorized for the target repository.
- Codex CLI installed, authenticated locally, and available on `PATH`.
- A GitHub repository with a writable remote, a base branch, and issues enabled.

Check the external tools before running the live loop:

```powershell
gh auth status
codex --version
git remote -v
```

## Local Setup

Run these commands from this repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[test]
```

After activation, either command style works:

```powershell
python -m agentic_loop validate
agentic-loop validate
```

## Configuration

The workflow is configured with `agentic-loop.yaml`. Relative paths are resolved from the directory containing that config file.

```yaml
repository:
  root: .
  remote: origin
  base_branch: main
  branch_prefix: agentic/issue-
  protected_paths:
    - .github/**
    - agentic_loop_assets/schemas/**

github:
  ready_label: agentic:ready
  demo_label: agentic-demo

codex:
  executable: codex
  model: gpt-5
  extra_args: []

policy:
  max_review_cycles: 2
  max_findings_per_cycle: 25
  stagnant_cycles: 2
  max_changed_files: 20
  max_diff_lines: 1000

validation:
  commands:
    - python -m pytest
    - python -m agentic_loop validate

synthetic_review:
  enabled: false
  findings: []
```

Configuration fields:

- `repository.root`: target repo where Git and Codex run. Use `.` when the config is in the target repo root.
- `repository.remote`: Git remote used for fetch and push, usually `origin`.
- `repository.base_branch`: PR target branch, usually `main`.
- `repository.branch_prefix`: prefix for automation branches; the issue number is appended.
- `repository.protected_paths`: paths that force human handoff when review findings touch them.
- `github.ready_label`: label applied to seeded demo issues.
- `github.demo_label`: second demo label applied to seeded demo issues.
- `codex.executable`: Codex command name or path.
- `codex.model`: optional model passed to `codex exec --model`.
- `codex.extra_args`: additional arguments appended to `codex exec`.
- `policy.max_review_cycles`: maximum remediation cycles before handoff.
- `policy.max_findings_per_cycle`: finding count that forces handoff.
- `policy.stagnant_cycles`: repeated-finding threshold that forces handoff.
- `policy.max_changed_files`: optional changed-file limit against `origin/<base_branch>` before handoff. Omit to disable.
- `policy.max_diff_lines`: optional added-plus-deleted line limit against `origin/<base_branch>` before handoff. Omit to disable.
- `validation.commands`: optional project checks run after implementation and after each remediation. Commands are parsed into argv and run without a shell. Omit or leave empty to skip validation.
- `synthetic_review`: optional test/demo mode that returns configured findings instead of asking Codex to review.
- `assets_dir`: optional top-level path for custom prompts and schemas. Omit it to use local `agentic_loop_assets` when present, otherwise bundled defaults.

## Assets

In this project, assets are not images or web files. They are the Codex prompt and JSON schema files that define the automation contract:

- `agentic_loop_assets/prompts/*.md`: role prompts for planner, implementer, reviewer, and remediator.
- `agentic_loop_assets/schemas/*.json`: JSON Schemas that Codex role outputs must satisfy.

Use the bundled defaults for the first run. Copy and customize the assets only when you want to change workflow behavior, output shape, or role instructions. If you change schemas, keep them compatible with the controller code that reads fields such as review `status`, `findings`, and commit messages.

To use custom assets, add this to `agentic-loop.yaml`:

```yaml
assets_dir: path\to\agentic_loop_assets
```

The custom directory must contain:

```text
prompts\planner.md
prompts\implementer.md
prompts\reviewer.md
prompts\remediator.md
schemas\plan.schema.json
schemas\implementation.schema.json
schemas\review.schema.json
schemas\remediation.schema.json
```

## Validate Without GitHub Mutation

This is the safe preflight path. It validates config, prompts, schemas, and tests without creating issues, branches, commits, labels, or PRs.

```powershell
python -m pytest
python -m agentic_loop validate
```

Expected validation output:

```text
validation ok
```

## Run The Demo In This Repository

First push this repository to GitHub and confirm `repository.remote` points at that repository.

Seed a fresh dummy issue:

```powershell
python -m agentic_loop seed-demo
```

The command prints the created issue number. Use that number for the run:

```powershell
python -m agentic_loop run --issue <number>
```

During the run, the controller will create or reuse branch `agentic/issue-<number>`, open or reuse one PR to the configured base branch, post hidden state comments on the issue and PR, and stop with a human handoff comment.

## Use This Helper In Another Repository

Install this package, then create an `agentic-loop.yaml` for the target repository.

If the config lives in the target repo root, use:

```yaml
repository:
  root: .
  remote: origin
  base_branch: main
  branch_prefix: agentic/issue-
  protected_paths:
    - .github/**
```

If the config lives outside the target repo, point `repository.root` at the target repo:

```yaml
repository:
  root: C:\path\to\target-repo
  remote: origin
  base_branch: main
  branch_prefix: agentic/issue-
  protected_paths:
    - .github/**
```

Then validate before running anything that mutates GitHub:

```powershell
python -m agentic_loop validate --config path\to\agentic-loop.yaml
```

Run against an existing GitHub issue:

```powershell
python -m agentic_loop run --config path\to\agentic-loop.yaml --issue <number>
```

## Clean Demo Practice

Use `seed-demo` for each presentation instead of reusing an old issue. Hidden state comments are intentionally auditable, so a fresh issue keeps the story clean and avoids stale workflow state.

The controller does not merge. After the demo, close the PR or delete the generated branch manually if you do not want to keep it.
