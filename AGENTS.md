# Agent Instructions

This repository is a standalone demo for a Python agentic issue-to-PR loop.

## Rules

- Do not commit directly to `main`.
- Keep changes small and demo-focused.
- Validate with `python -m pytest` and `python -m agentic_loop validate` before handoff.
- Treat `.worktrees/agentic-issue-*` as controller-created run worktrees, often
  from seeded demo issues. Identify seeded demo runs by the `agentic-demo`
  GitHub issue label, the `agentic/issue-<number>` branch, and the
  `.worktrees/agentic-issue-<number>` path. Do not delete or stage those
  worktrees unless explicitly asked.

## Scope

The package exposes a CLI named `agentic-loop` with three commands:

- `validate`: validate config, prompts, and JSON schemas without GitHub mutation or Codex calls.
- `seed-demo`: create a fresh dummy issue and apply demo labels.
- `run --issue <number>`: run the bounded issue-to-PR workflow.
