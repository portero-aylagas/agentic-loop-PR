# Dummy PR Walkthrough

The default seeded issue asks the controller to create `tests/agentic_demo/sample.txt` containing exactly these lines:

```text
alpha
beta
gamma
```

It also asks for one minimal Python test. This is intentionally isolated from package behavior so the demo PR is easy to inspect and safe to discard.

Use a fresh seeded issue for each live demo. The controller writes hidden state comments to issues and PRs so stale state is auditable instead of invisible.
