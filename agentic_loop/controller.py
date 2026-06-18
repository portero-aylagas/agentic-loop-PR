from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .codex_provider import CodexProvider
from .config import LoopConfig, prompt_path, schema_path
from .git_client import GitClient
from .github_cli import GitHubCli, Issue, PullRequest
from .policy import PolicyDecision, decide_review, protected_path_matches
from .state import WorkflowState, decode_states, encode_state, newest_state


PHASE_LABELS = (
    "agentic:planning",
    "agentic:implementing",
    "agentic:reviewing",
    "agentic:remediating",
    "agentic:human-review",
    "agentic:failed",
)


@dataclass(frozen=True)
class RunResult:
    issue: int
    branch: str
    pr: int | None
    decision: PolicyDecision


@dataclass(frozen=True)
class ResumeContext:
    branch: str
    pr: PullRequest | None
    state: dict[str, Any] | None
    states: list[dict[str, Any]]

    @property
    def phase(self) -> str:
        return str((self.state or {}).get("phase", ""))

    @property
    def is_terminal(self) -> bool:
        return self.phase in {"human-review", "failed"}

    @property
    def can_resume_review(self) -> bool:
        return self.phase in {"reviewing", "reviewed", "remediating", "remediated"}

    @property
    def next_cycle(self) -> int:
        cycle = _state_cycle(self.state)
        if self.phase == "remediated":
            return cycle
        return cycle

    @property
    def review_for_remediation(self) -> dict[str, Any] | None:
        if self.phase == "reviewed":
            state = self.state or {}
        elif self.phase == "remediating":
            state = _latest_continue_review_state(self.states) or {}
        else:
            state = {}
        if not state:
            return None
        if str(state.get("status", "")) != "continue":
            return None
        return {
            "status": "blocking",
            "summary": "resumed from previous review state",
            "findings": list(state.get("findings") or []),
        }

    @property
    def completed_review_decision(self) -> PolicyDecision | None:
        if self.phase != "reviewed":
            return None
        status = str((self.state or {}).get("status", ""))
        if status not in {"approved", "handoff"}:
            return None
        reason = str((self.state or {}).get("handoff_reason") or f"resumed reviewed state: {status}")
        if status == "approved":
            return PolicyDecision("approved", reason)
        return PolicyDecision("handoff", reason)


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

    def run(self, issue_number: int, *, force: bool = False) -> RunResult:
        resume = self._resume_context(issue_number)
        branch = resume.branch
        if resume.is_terminal and not force:
            return RunResult(
                issue_number,
                branch,
                resume.pr.number if resume.pr is not None else _state_pr(resume.state),
                PolicyDecision("handoff", f"workflow is already terminal: {resume.phase}"),
            )

        pr: PullRequest | None = resume.pr
        worktree = self.git.prepare_issue_worktree(
            issue=issue_number,
            branch=branch,
            base=self.config.base_branch,
            repo_root=self.config.repository_root,
        )
        self.git = self.git.with_cwd(worktree)
        self.codex = self.codex.with_cwd(worktree)
        issue = self.github.issue_view(issue_number)
        try:
            base_context = _base_context(self.config)
            if force or not resume.can_resume_review:
                pr = self._plan_implement_and_open_pr(issue, branch, base_context)
                resume = ResumeContext(branch=branch, pr=pr, state=None, states=[])
                self._post_pr_state(pr.number, issue.number, "reviewing", 0, branch, [])
            elif pr is None:
                raise RuntimeError(f"cannot resume {resume.phase} for issue #{issue.number}: no open PR for branch {branch!r}")

            completed = resume.completed_review_decision
            if completed is not None:
                self._enter_phase(issue.number, "human-review", pr.number)
                self.github.comment_pr(pr.number, f"Human handoff required. Reason: {completed.reason}")
                return RunResult(issue.number, branch, pr.number, completed)

            return self._review_loop(issue, pr, branch, resume)
        except Exception:
            self._enter_phase(issue.number, "failed", pr.number if pr is not None else None)
            raise

    def _plan_implement_and_open_pr(self, issue: Issue, branch: str, base_context: dict[str, str]) -> PullRequest:
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
        return self._ensure_pr(issue, branch, plan)

    def _review_loop(self, issue: Issue, pr: PullRequest, branch: str, resume: ResumeContext) -> RunResult:
        history = _review_history(resume.states)
        cycle = resume.next_cycle
        review = resume.review_for_remediation
        if review is not None and history:
            history = history[:-1]
        while True:
            if review is None:
                self._enter_phase(issue.number, "reviewing", pr.number)
                protected_findings = self._protected_path_findings()
                if protected_findings:
                    decision = PolicyDecision("handoff", "protected path changed before review")
                    self._post_pr_state(pr.number, issue.number, "reviewed", cycle, branch, protected_findings, decision.kind, decision.reason)
                    self._enter_phase(issue.number, "human-review", pr.number)
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
            self._post_pr_state(pr.number, issue.number, "reviewed", cycle, branch, findings, decision.kind, decision.reason)
            if decision.kind == "approved":
                self._enter_phase(issue.number, "human-review", pr.number)
                self.github.comment_pr(pr.number, f"Human handoff: review approved. Automation will not merge. Reason: {decision.reason}")
                return RunResult(issue.number, branch, pr.number, decision)
            if decision.kind == "handoff":
                self._enter_phase(issue.number, "human-review", pr.number)
                self.github.comment_pr(pr.number, f"Human handoff required. Reason: {decision.reason}")
                return RunResult(issue.number, branch, pr.number, decision)

            self._enter_phase(issue.number, "remediating", pr.number)
            remediation = self.codex.run_role(
                role="remediator",
                prompt_path=prompt_path(self.config, "remediator"),
                schema_path=schema_path(self.config, "remediation"),
                payload={"issue": _issue_payload(issue), "pr": _pr_payload(pr), "review": review, "branch": branch, **_base_context(self.config)},
            ).data
            self.git.commit(str(remediation.get("commit_message", f"Remediate issue {issue.number}")))
            self.git.push_branch(branch)
            history.append(findings)
            cycle += 1
            self._post_pr_state(pr.number, issue.number, "remediated", cycle, branch, findings)
            review = None

    def _resume_context(self, issue_number: int) -> ResumeContext:
        default_branch = f"{self.config.branch_prefix}{issue_number}"
        issue_comments = self.github.issue_comments(issue_number)
        issue_state = newest_state(issue_comments)
        branch = str(issue_state.get("branch") or default_branch) if issue_state else default_branch
        pr = self.github.find_open_pr_by_branch(branch)
        pr_comments = self.github.pr_comments(pr.number) if pr is not None else []
        states = _states_from_comments([*issue_comments, *pr_comments])
        state = newest_state([{"body": encode_state(item)} for item in states])
        if state is not None and state.get("branch"):
            branch = str(state["branch"])
            if pr is None or pr.head_ref != branch:
                pr = self.github.find_open_pr_by_branch(branch)
                if pr is not None:
                    states = _states_from_comments([*issue_comments, *self.github.pr_comments(pr.number)])
                    state = newest_state([{"body": encode_state(item)} for item in states])
        return ResumeContext(branch=branch, pr=pr, state=state, states=states)

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
        self._enter_phase(issue, phase, pr)
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
        handoff_reason: str = "",
    ) -> None:
        self._enter_phase(issue, phase, pr)
        state = WorkflowState(issue=issue, phase=phase, cycle=cycle, branch=branch, pr=pr, status=status, findings=findings, handoff_reason=handoff_reason)
        self.github.comment_pr(pr, _state_comment(f"Agentic workflow: {phase} cycle {cycle} on `{branch}` ({status}).", state))

    def _enter_phase(self, issue: int, phase: str, pr: int | None) -> None:
        label = _phase_label(phase)
        if label is None:
            return
        targets = [("issue", issue)]
        if pr is not None:
            targets.append(("pr", pr))
        for target, number in targets:
            self._apply_phase_label(target, number, label)

    def _apply_phase_label(self, target: str, number: int, current_label: str) -> None:
        if not self.github.ensure_label(current_label, description="Agentic workflow phase"):
            self._comment_label_failure(target, number, f"create label `{current_label}`")
        for label in PHASE_LABELS:
            if label == current_label:
                continue
            if not self._remove_label(target, number, label):
                self._comment_label_failure(target, number, f"remove label `{label}`")
        if not self._add_label(target, number, current_label):
            self._comment_label_failure(target, number, f"add label `{current_label}`")

    def _add_label(self, target: str, number: int, label: str) -> bool:
        if target == "issue":
            return self.github.add_issue_label(number, label)
        return self.github.add_pr_label(number, label)

    def _remove_label(self, target: str, number: int, label: str) -> bool:
        if target == "issue":
            return self.github.remove_issue_label(number, label)
        return self.github.remove_pr_label(number, label)

    def _comment_label_failure(self, target: str, number: int, action: str) -> None:
        body = f"Agentic workflow label update failed: could not {action}. Continuing without blocking automation."
        if target == "issue":
            self.github.comment_issue(number, body)
        else:
            self.github.comment_pr(number, body)


def _issue_payload(issue: Issue) -> dict[str, Any]:
    return {"number": issue.number, "title": issue.title, "body": issue.body, "url": issue.url}


def _pr_payload(pr: PullRequest) -> dict[str, Any]:
    return {"number": pr.number, "url": pr.url, "head_ref": pr.head_ref, "base_ref": pr.base_ref}


def _base_context(config: LoopConfig) -> dict[str, str]:
    return {"base_ref": config.base_branch, "remote_base_ref": f"{config.remote}/{config.base_branch}"}


def _state_comment(message: str, state: WorkflowState) -> str:
    return f"{message}\n\n{encode_state(state)}"


def _states_from_comments(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for comment in comments:
        states.extend(decode_states(str(comment.get("body", ""))))
    return states


def _review_history(states: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    reviewed = [
        state for state in states
        if state.get("phase") == "reviewed" and str(state.get("status", "")) == "continue"
    ]
    reviewed.sort(key=lambda item: (_state_cycle(item), str(item.get("updated_at", ""))))
    return [list(state.get("findings") or []) for state in reviewed]


def _latest_continue_review_state(states: list[dict[str, Any]]) -> dict[str, Any] | None:
    reviewed = [
        state for state in states
        if state.get("phase") == "reviewed" and str(state.get("status", "")) == "continue"
    ]
    if not reviewed:
        return None
    return max(reviewed, key=lambda item: (_state_cycle(item), str(item.get("updated_at", ""))))


def _state_cycle(state: dict[str, Any] | None) -> int:
    try:
        return int((state or {}).get("cycle", 0))
    except (TypeError, ValueError):
        return 0


def _state_pr(state: dict[str, Any] | None) -> int | None:
    value = (state or {}).get("pr")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _phase_label(phase: str) -> str | None:
    if phase in {"planning", "implementing", "reviewing"}:
        return f"agentic:{phase}"
    if phase == "remediating":
        return "agentic:remediating"
    if phase in {"human-review", "failed"}:
        return f"agentic:{phase}"
    return None
