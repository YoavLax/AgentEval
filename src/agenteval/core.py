from __future__ import annotations

from pathlib import Path

from agenteval.parser import ParseError, parse
from agenteval.result import CheckRun, Diagnostic, FileType, Severity, ValidationResult
from agenteval.rules import get_rules
from agenteval.rules.agent import get_agent_rules


def _detect_file_type(path: Path) -> FileType:
    """Infer whether a file is a skill or an agent based on its path."""
    if path.name == "SKILL.md":
        return FileType.SKILL
    # Any .md file living inside an 'agents' directory is treated as an agent.
    if "agents" in path.parts:
        return FileType.AGENT
    return FileType.SKILL


def validate(
    path: Path,
    *,
    max_lines: int | None = None,
    max_tokens: int | None = None,
    ignore_prefixes: list[str] | None = None,
    skip_dirname_check: bool = False,
    skip_ref_check: bool = False,
    min_desc_score: int | None = None,
    strict_vscode: bool = False,
    target_agent: str = "all",
    file_type: FileType | None = None,
) -> ValidationResult:
    """Validate a single SKILL.md or agent .md file and return a ValidationResult.

    Args:
        path: Path to the file to validate.
        max_lines: Override the default line-count threshold.
        max_tokens: Override the default token-count threshold.
        ignore_prefixes: Suppress any diagnostic whose rule ID starts with one of these prefixes.
        skip_dirname_check: Skip the directory-name matching check (skill only).
        skip_ref_check: Skip file reference validation (skill only).
        min_desc_score: Minimum description quality score (0-100). Below this triggers a warning.
        strict_vscode: Promote VS Code compatibility issues to errors (skill only).
        target_agent: Scope compatibility checks ('claude', 'vscode', 'all') (skill only).
        file_type: Override auto-detection of file type (SKILL or AGENT).
    """
    detected_type = file_type if file_type is not None else _detect_file_type(path)

    try:
        skill = parse(path)
    except ParseError as exc:
        return ValidationResult(
            path=path,
            diagnostics=[Diagnostic(
                rule="parse.error",
                severity=Severity.ERROR,
                message=str(exc),
            )],
            file_type=detected_type,
        )

    if detected_type == FileType.AGENT:
        rules = get_agent_rules(
            max_lines=max_lines,
            max_tokens=max_tokens,
            min_desc_score=min_desc_score,
        )
    else:
        rules = get_rules(
            max_lines=max_lines,
            max_tokens=max_tokens,
            skip_dirname_check=skip_dirname_check,
            skip_ref_check=skip_ref_check,
            min_desc_score=min_desc_score,
            strict_vscode=strict_vscode,
            target_agent=target_agent,
        )

    check_runs: list[CheckRun] = []
    for rule in rules:
        run_diags = rule(skill)
        if ignore_prefixes:
            run_diags = [
                d for d in run_diags
                if not any(d.rule.startswith(prefix) for prefix in ignore_prefixes)
            ]
        check_runs.append(CheckRun(name=rule.__name__, diagnostics=run_diags))

    all_diagnostics: list[Diagnostic] = [
        d for run in check_runs for d in run.diagnostics
    ]

    return ValidationResult(
        path=path,
        diagnostics=all_diagnostics,
        check_runs=check_runs,
        file_type=detected_type,
    )
