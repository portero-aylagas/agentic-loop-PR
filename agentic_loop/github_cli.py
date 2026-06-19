from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import re

from .command import CommandRunner, CommandError


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    url: str = ""


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    head_ref: str
    base_ref: str


class GitHubCli:
    def __init__(self, runner: CommandRunner | None = None):
        self.runner = runner or CommandRunner()

    def issue_view(self, number: int) -> Issue:
        raw = self._json(["gh", "issue", "view", str(number), "--json", "number,title,body,url"])
        return Issue(int(raw["number"]), str(raw["title"]), str(raw.get("body") or ""), str(raw.get("url") or ""))

    def issue_comments(self, number: int) -> list[dict[str, Any]]:
        raw = self._json(["gh", "issue", "view", str(number), "--json", "comments"])
        comments = raw.get("comments", [])
        return comments if isinstance(comments, list) else []

    def pr_comments(self, number: int) -> list[dict[str, Any]]:
        raw = self._json(["gh", "pr", "view", str(number), "--json", "comments"])
        comments = raw.get("comments", [])
        return comments if isinstance(comments, list) else []

    def comment_issue(self, number: int, body: str) -> None:
        self.runner.run(["gh", "issue", "comment", str(number), "--body", body])

    def comment_pr(self, number: int, body: str) -> None:
        self.runner.run(["gh", "pr", "comment", str(number), "--body", body])

    def create_issue(self, title: str, body: str, labels: list[str]) -> Issue:
        args = ["gh", "issue", "create", "--title", title, "--body", body]
        for label in labels:
            args.extend(["--label", label])
        result = self.runner.run(args)
        number = _number_from_url(result.stdout)
        return self.issue_view(number)

    def ensure_label(self, name: str, color: str = "6f42c1", description: str = "Agentic loop demo label") -> bool:
        result = self.runner.run(
            ["gh", "label", "create", name, "--color", color, "--description", description],
            check=False,
        )
        return result.returncode == 0 or "already exists" in result.stderr.lower()

    def add_issue_label(self, number: int, label: str) -> bool:
        return self._edit_label(["gh", "issue", "edit", str(number), "--add-label", label])

    def remove_issue_label(self, number: int, label: str) -> bool:
        return self._edit_label(["gh", "issue", "edit", str(number), "--remove-label", label], absent_ok=True)

    def add_pr_label(self, number: int, label: str) -> bool:
        return self._edit_label(["gh", "pr", "edit", str(number), "--add-label", label])

    def remove_pr_label(self, number: int, label: str) -> bool:
        return self._edit_label(["gh", "pr", "edit", str(number), "--remove-label", label], absent_ok=True)

    def find_open_pr_by_branch(self, branch: str) -> PullRequest | None:
        raw = self._json([
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number,url,headRefName,baseRefName",
            "--limit",
            "20",
        ])
        if not isinstance(raw, list) or not raw:
            return None
        item = raw[0]
        return PullRequest(int(item["number"]), str(item["url"]), str(item["headRefName"]), str(item["baseRefName"]))

    def pr_view(self, number: int) -> PullRequest:
        raw = self._json(["gh", "pr", "view", str(number), "--json", "number,url,headRefName,baseRefName"])
        return PullRequest(int(raw["number"]), str(raw["url"]), str(raw["headRefName"]), str(raw["baseRefName"]))

    def pr_body(self, number: int) -> str:
        raw = self._json(["gh", "pr", "view", str(number), "--json", "body"])
        return str(raw.get("body") or "")

    def edit_pr_body(self, number: int, body: str) -> None:
        self.runner.run(["gh", "pr", "edit", str(number), "--body", body])

    def create_pr(self, *, title: str, body: str, head: str, base: str) -> PullRequest:
        result = self.runner.run([
            "gh",
            "pr",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--head",
            head,
            "--base",
            base,
        ])
        number = _number_from_url(result.stdout)
        return self.pr_view(number)

    def _json(self, args: list[str]) -> Any:
        result = self.runner.run(args)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise CommandError(result) from exc

    def _edit_label(self, args: list[str], *, absent_ok: bool = False) -> bool:
        result = self.runner.run(args, check=False)
        if result.returncode == 0:
            return True
        stderr = result.stderr.lower()
        return absent_ok and any(fragment in stderr for fragment in ("not found", "does not exist", "not labeled"))


def _number_from_url(text: str) -> int:
    match = re.search(r"/(?:issues|pull)/(\d+)", text)
    if not match:
        raise ValueError(f"could not parse GitHub number from output: {text.strip()}")
    return int(match.group(1))
