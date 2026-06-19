# Demo Seed

`seed-demo` creates a fresh GitHub issue titled:

```text
Agentic loop demo: isolated text fixture
```

The default issue body is `demo/issues/isolated_text_fixture.md`. It asks the
workflow to create `tests/agentic_demo/sample.txt` containing exactly:

```text
alpha
beta
gamma
```

It also asks for one minimal Python test. The task is intentionally isolated from
package behavior so the generated PR is easy to inspect and safe to discard.

Use a fresh seeded issue for each live demo:

```powershell
python -m agentic_loop seed-demo
python -m agentic_loop run --issue <created-issue-number>
```

The workflow writes hidden state comments to issues and PRs. Fresh issues avoid
resuming stale demo state from an earlier run.
