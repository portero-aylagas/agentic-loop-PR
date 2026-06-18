from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .codex_provider import CodexProvider
from .config import LoopConfig, prompt_path, schema_path
from .git_client import GitClient
from .github_cli import GitHubCli, Issue, PullRequest
from .policy import PolicyDecision, decide_review, protected_path_matches
from .state import WorkflowState, encode_state


@dataclass(frozen=True)
class RunResult:
    issue: int
    branch: str
    pr: int
    decision: PolicyDecision


class Controller:
    def __init__(
        self,
        *,
        config: LoopConfig,
        github: GitHubCli,
        git: GitClient,
        codex: CodexProvider,
    ):
        self.config = config
        self.github = github
        self.git = git
        self.codex = codex

    def run(self, issue_number: int) -> RunResult:
        if self.git.has_changes():
            raise RuntimeError("working tree has uncommitted changes; commit or stash before running automation")
        issue = self.github.issue_view(issue_number)
        branch = f"{self.config.branch_prefix}{issue_number}"
        self.git.sync_base(self.config.base_branch)
        self.git.checkout_or_create_branch(branch, self.config.base_branch)
        base_context = _base_context(self.config)
        self._post_issue_state(issue.number, "planning", 0, branch, None)

        plan = self.codex.run_role(
            role="planner",
            prompt_path=prompt_path(self.config, "planner"),
            schema_path=schema_path(self.config, "plan"),
            payload={"issue": _issue_payload(issue), "branch": branch, **base_context},
        ).data
        self._post_issue_state(issue.number, "implementing", 0, branch, None)

        implementation = self.codex.run_role(
            role="implementer",
            prompt_path=prompt_path(self.config, "implementer"),
            schema_path=schema_path(self.config, "implementation"),
            payload={"issue": _issue_payload(issue), "plan": plan, "branch": branch, **base_context},
        ).data
        self.git.commit(str(implementation.get("commit_message", f"Implement issue {issue.number}")))
        self.git.push_branch(branch)

        pr = self._ensure_pr(issue, branch, plan)
        self._post_pr_state(pr.number, issue.number, "reviewing", 0, branch, [])

        history: list[list[dict[str, Any]]] = []
        cycle = 0
        while True:
            protected_findings = self._protected_path_findings()
            if protected_findings:
                decision = PolicyDecision("handoff", "protected path changed before review")
                self._post_pr_state(pr.number, issue.number, "reviewed", cycle, branch, protected_findings, decision.kind)
                self.github.comment_pr(pr.number, f"Human handoff required. Reason: {decision.reason}")
                return RunResult(issue.number, branch, pr.number, decision)
            review = self._review(issue, pr, branch, cycle, history)
            findings = list(review.get("findings", []))
            decision = decide_review(
                review=review,
                cycle=cycle,
                previous_findings=history,
                max_review_cycles=int(self.config.policy["max_review_cycles"]),
                max_findings_per_cycle=int(self.config.policy["max_findings_per_cycle"]),
                stagnant_cycles=int(self.config.policy["stagnant_cycles"]),
                protected_paths=self.config.protected_paths,
            )
            self._post_pr_state(pr.number, issue.number, "reviewed", cycle, branch, findings, decision.kind)
            if decision.kind == "approved":
                self.github.comment_pr(pr.number, f"Human handoff: review approved. Automation will not merge. Reason: {decision.reason}")
                return RunResult(issue.number, branch, pr.number, decision)
            if decision.kind == "handoff":
                self.github.comment_pr(pr.number, f"Human handoff required. Reason: {decision.reason}")
                return RunResult(issue.number, branch, pr.number, decision)

            remediation = self.codex.run_role(
                role="remediator",
                prompt_path=prompt_path(self.config, "remediator"),
                schema_path=schema_path(self.config, "remediation"),
                payload={"issue": _issue_payload(issue), "pr": _pr_payload(pr), "review": review, "branch": branch, **base_context},
            ).data
            self.git.commit(str(remediation.get("commit_message", f"Remediate issue {issue.number}")))
            self.git.push_branch(branch)
            history.append(findings)
            cycle += 1
            self._post_pr_state(pr.number, issue.number, "remediated", cycle, branch, findings)

    def _ensure_pr(self, issue: Issue, branch: str, plan: dict[str, Any]) -> PullRequest:
        existing = self.github.find_open_pr_by_branch(branch)
        if existing is not None:
            return existing
        title = f"Agentic demo: issue #{issue.number}"
        summary = str(plan.get("summary", issue.title))
        body = f"Closes #{issue.number}\n\n{summary}\n\nAutomation stops at human handoff and will not merge this PR."
        return self.github.create_pr(title=title, body=body, head=branch, base=self.config.base_branch)

    def _review(
        self,
        issue: Issue,
        pr: PullRequest,
        branch: str,
        cycle: int,
        history: list[list[dict[str, Any]]],
    ) -> dict[str, Any]:
        synthetic = self.config.synthetic_review
        if synthetic.get("enabled"):
            findings = list(synthetic.get("findings", []))
            return {"status": "blocking" if findings else "approved", "summary": "synthetic review", "findings": findings}
        return self.codex.run_role(
            role="reviewer",
            prompt_path=prompt_path(self.config, "reviewer"),
            schema_path=schema_path(self.config, "review"),
            payload={
                "issue": _issue_payload(issue),
                "pr": _pr_payload(pr),
                "branch": branch,
                "cycle": cycle,
                "history": history,
                **_base_context(self.config),
            },
        ).data

    def _protected_path_findings(self) -> list[dict[str, Any]]:
        base = self.git.remote_ref(self.config.base_branch)
        findings = []
        for file in self.git.changed_files(base):
            if protected_path_matches(file.path, self.config.protected_paths):
                findings.append({
                    "title": "Protected path changed",
                    "path": file.path,
                    "message": f"`{file.path}` matches repository.protected_paths and requires human review before the automated reviewer runs.",
                    "severity": "conflict",
                    "conflicting": True,
                })
        return findings

    def _post_issue_state(self, issue: int, phase: str, cycle: int, branch: str, pr: int | None) -> None:
        state = WorkflowState(issue=issue, phase=phase, cycle=cycle, branch=branch, pr=pr)
        self.github.comment_issue(issue, _state_comment(f"Agentic workflow: {phase} on `{branch}`.", state))

    def _post_pr_state(
        self,
        pr: int,
        issue: int,
        phase: str,
        cycle: int,
        branch: str,
        findings: list[dict[str, Any]],
        status: str = "running",
    ) -> None:
        state = WorkflowState(issue=issue, phase=phase, cycle=cycle, branch=branch, pr=pr, status=status, findings=findings)
        self.github.comment_pr(pr, _state_comment(f"Agentic workflow: {phase} cycle {cycle} on `{branch}` ({status}).", state))


def _issue_payload(issue: Issue) -> dict[str, Any]:
    return {"number": issue.number, "title": issue.title, "body": issue.body, "url": issue.url}


def _pr_payload(pr: PullRequest) -> dict[str, Any]:
    return {"number": pr.number, "url": pr.url, "head_ref": pr.head_ref, "base_ref": pr.base_ref}


def _base_context(config: LoopConfig) -> dict[str, str]:
    return {"base_ref": config.base_branch, "remote_base_ref": f"{config.remote}/{config.base_branch}"}


def _state_comment(message: str, state: WorkflowState) -> str:
    return f"{message}\n\n{encode_state(state)}"
