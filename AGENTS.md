# Agent Instructions

This repository is a standalone demo for a Python agentic issue-to-PR loop.

## Rules

- Do not commit directly to `main`.
- Keep changes small and demo-focused.
- Validate with `python -m pytest` and `python -m agentic_loop validate` before handoff.

## Scope

The package exposes a CLI named `agentic-loop` with three commands:

- `validate`: validate config, prompts, and JSON schemas without GitHub mutation or Codex calls.
- `seed-demo`: create a fresh dummy issue and apply demo labels.
- `run --issue <number>`: run the bounded issue-to-PR workflow.
