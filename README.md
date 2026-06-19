# Agentic Loop Helper

Python helper CLI for running a bounded GitHub issue-to-PR automation loop.

The project is meant to be integrated into other repositories. Given a GitHub
issue, it creates or reuses an issue branch, asks Codex to plan and implement the
change, opens or reuses one pull request, runs configured validation commands,
reviews and remediates within policy limits, then stops for human review. It
does not merge pull requests and does not enable auto-merge.

This repository also includes a small seeded demo. The demo can create a fresh
dummy issue and then run the same helper loop against that issue.

## Commands

The package exposes a CLI named `agentic-loop`. The module form is equivalent:

```powershell
python -m agentic_loop validate
python -m agentic_loop seed-demo
python -m agentic_loop run --issue <number>
```

After installation, this also works:

```powershell
agentic-loop validate
agentic-loop seed-demo
agentic-loop run --issue <number>
```

All commands read `agentic-loop.yaml` by default. Pass `--config` to use a
different config file:

```powershell
python -m agentic_loop validate --config C:\path\to\agentic-loop.yaml
python -m agentic_loop run --config C:\path\to\agentic-loop.yaml --issue 123
```

`run` also accepts `--force` to rerun a workflow that already reached a terminal
state such as `human-review` or `failed`.

## Requirements

- Python 3.11 or newer.
- Git available on `PATH`.
- GitHub CLI `gh` installed, authenticated, and authorized for the target repo.
- Codex CLI installed, authenticated locally, and available as the configured
  executable.
- A GitHub repository with issues enabled and a writable remote.

Check the external tools before a live run:

```powershell
gh auth status
git remote -v
codex --version
```

## Local Setup

From this repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[test]
```

Validate the helper before running anything that mutates GitHub:

```powershell
python -m pytest
python -m agentic_loop validate
```

Expected validation output:

```text
validation ok
```

## Use In Another Repository

This is the main use case. Add an `agentic-loop.yaml` for the repository you want
the helper to work on.

If the config file lives in the target repository root, use `repository.root: .`:

```yaml
repository:
  root: .
  remote: origin
  base_branch: main
  branch_prefix: agentic/issue-
  protected_paths:
    - .github/**

github:
  ready_label: agentic:ready
  demo_label: agentic-demo

codex:
  executable: codex
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
```

If the config file lives outside the target repository, point `repository.root`
at that checkout:

```yaml
repository:
  root: C:\path\to\target-repo
  remote: origin
  base_branch: main
  branch_prefix: agentic/issue-
  protected_paths:
    - .github/**
```

Then validate the config, prompts, and schemas:

```powershell
python -m agentic_loop validate --config C:\path\to\agentic-loop.yaml
```

Run the helper against an existing GitHub issue:

```powershell
python -m agentic_loop run --config C:\path\to\agentic-loop.yaml --issue <number>
```

The issue should describe the requested change clearly enough for Codex to plan,
implement, review, and remediate it. The helper records progress in GitHub
comments and hands off to a human instead of merging.

## Demo In This Repository

The built-in demo seeds a fresh issue that asks for an isolated text fixture and
a minimal test. Use a fresh seeded issue for each demo so hidden workflow state
from previous runs does not affect the story.

First make sure this repository is pushed to GitHub and `repository.remote`
points at that repository. Then create the issue:

```powershell
python -m agentic_loop seed-demo
```

The command prints the created issue number and URL:

```text
created issue #123: https://github.com/OWNER/REPO/issues/123
```

Run the workflow against that issue:

```powershell
python -m agentic_loop run --issue 123
```

The controller creates or reuses branch `agentic/issue-123`, opens or reuses one
PR to the configured base branch, runs the issue-to-PR loop, and stops at human
handoff.

## Configuration Reference

Relative paths in `agentic-loop.yaml` are resolved from the directory containing
that config file.

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
  executable: codex.cmd
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

Fields:

- `repository.root`: target repository where Git and Codex run.
- `repository.remote`: Git remote used for fetch and push, usually `origin`.
- `repository.base_branch`: pull request target branch.
- `repository.branch_prefix`: branch prefix; the issue number is appended.
- `repository.protected_paths`: glob patterns that force human handoff when
  changed or reported in review findings.
- `github.ready_label`: label applied to seeded demo issues.
- `github.demo_label`: second label applied to seeded demo issues.
- `codex.executable`: Codex command name or path, for example `codex` or
  `codex.cmd`.
- `codex.model`: optional model passed to `codex exec --model`.
- `codex.extra_args`: extra arguments appended to `codex exec`.
- `policy.max_review_cycles`: maximum review/remediation cycles before handoff.
- `policy.max_findings_per_cycle`: finding count above which the helper hands
  off.
- `policy.stagnant_cycles`: repeated identical finding threshold before handoff.
- `policy.max_changed_files`: optional changed-file limit; omit to disable.
- `policy.max_diff_lines`: optional added-plus-deleted line limit; omit to
  disable.
- `validation.commands`: project checks run after implementation and after
  remediation. Commands are parsed into argv and run without a shell.
- `synthetic_review`: demo/test mode that returns configured findings instead of
  asking Codex to review.
- `assets_dir`: optional top-level path for custom prompts and schemas. Omit it
  to use local `agentic_loop_assets` when present, otherwise bundled defaults.

## Prompts And Schemas

The assets are prompt and JSON schema files that define the Codex role contract:

- `agentic_loop_assets/prompts/planner.md`
- `agentic_loop_assets/prompts/implementer.md`
- `agentic_loop_assets/prompts/reviewer.md`
- `agentic_loop_assets/prompts/remediator.md`
- `agentic_loop_assets/schemas/plan.schema.json`
- `agentic_loop_assets/schemas/implementation.schema.json`
- `agentic_loop_assets/schemas/review.schema.json`
- `agentic_loop_assets/schemas/remediation.schema.json`

The workflow uses stable emoji labels at the start of user-visible automated
comments so readers can tell which agent is speaking:

- 🧠 Orchestrator: controller-owned workflow, validation, labels, and handoff.
- 🧑‍💼📝 Planner: issue analysis and implementation planning.
- 🧑‍💻🛠️ Implementer: code and test changes from the plan.
- 🕵️🔎 Reviewer: review results and blocking findings.
- 🧑‍⚕️💊 Remediator: focused fixes for reviewer findings.

Use the bundled defaults first. Copy and customize assets only when you need to
change role instructions or output shape. If schemas are customized, keep them
compatible with the controller fields it reads, including review `status`,
review `findings`, `files_changed`, and `commit_message`.

To use custom assets:

```yaml
assets_dir: C:\path\to\agentic_loop_assets
```

## Runtime Behavior

For issue `123`, the default branch is `agentic/issue-123`. Work happens in a
Git worktree under the target repo:

```text
.worktrees/agentic-issue-123
```

The helper fetches the configured base branch, creates or reuses the issue
worktree, refuses to continue if that worktree has uncommitted changes, and uses
Codex inside the worktree. It stages only files reported by Codex role output.
Unexpected dirty files force human handoff.

The helper stores resumable workflow state in hidden GitHub comments using the
marker `agentic-workflow-state:v1`. It reads state from issue and PR comments to
resume review/remediation work or detect terminal runs.

It also applies phase labels to the issue and PR when possible:

- `agentic:planning`
- `agentic:implementing`
- `agentic:reviewing`
- `agentic:remediating`
- `agentic:human-review`
- `agentic:failed`

If label creation, add, or remove operations fail, the helper comments with the
manual action and continues.

The PR body includes an agentic status section with the issue, phase, branch,
plan summary, validation result, latest review summary, remediation count, and
handoff status.

## Handoff And Safety

The helper stops for human review instead of merging. Handoff happens when the
review is approved, when policy says automation should stop, or when the helper
cannot safely continue.

Common handoff reasons include:

- Protected paths changed before review.
- Review findings touch protected paths.
- Review findings are marked conflicting.
- Too many findings are returned.
- Findings repeat or stagnate across cycles.
- Maximum review cycles are reached.
- Validation still fails after policy limits.
- Diff size exceeds configured limits.
- Codex reports invalid or unsafe changed file paths.
- Codex reports files that are not dirty.
- Unexpected dirty files appear in the worktree.

Terminal workflow state prevents accidental reruns. Use `run --force` only when
you intentionally want to rerun after `human-review` or `failed`.

## Hosted Validation

The GitHub Actions workflow in `.github/workflows/validate.yml` is validation
only. It installs the package with test dependencies, runs
`python -m agentic_loop validate`, and runs `python -m pytest`.

Hosted validation should not run `agentic-loop run` or `seed-demo`, use Codex
credentials, create issues, create branches, add labels, post comments, or open
pull requests.

