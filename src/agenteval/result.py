from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class FileType(str, Enum):
    SKILL = "skill"
    AGENT = "agent"


@dataclass(frozen=True)
class Diagnostic:
    rule: str
    severity: Severity
    message: str
    line: int | None = None
    context: str | None = None


@dataclass(frozen=True)
class CheckRun:
    """Outcome of a single rule execution."""
    name: str               # rule function __name__
    diagnostics: list[Diagnostic]

    @property
    def passed(self) -> bool:
        return len(self.diagnostics) == 0

    @property
    def worst_severity(self) -> Severity | None:
        if not self.diagnostics:
            return None
        _order = {Severity.ERROR: 2, Severity.WARNING: 1, Severity.INFO: 0}
        return max(self.diagnostics, key=lambda d: _order[d.severity]).severity


@dataclass(frozen=True)
class ValidationResult:
    path: Path
    diagnostics: list[Diagnostic]
    check_runs: list[CheckRun] = field(default_factory=list)
    file_type: FileType = FileType.SKILL

    @property
    def valid(self) -> bool:
        return all(d.severity != Severity.ERROR for d in self.diagnostics)
