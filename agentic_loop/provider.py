from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class RoleResult:
    role: str
    data: dict[str, Any]


class RoleProvider(Protocol):
    def with_cwd(self, cwd: Path) -> RoleProvider:
        ...

    def run_role(
        self,
        *,
        role: str,
        prompt_path: Path,
        schema_path: Path,
        payload: dict[str, Any],
    ) -> RoleResult:
        ...
