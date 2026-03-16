"""Validation rules specific to agent .md files (VS Code / Copilot agent mode).

Agent files share frontmatter with SKILL.md files but use a different schema:
  name        — display name (may contain spaces and capitals, not a slug)
  description — plain-text description of the agent's purpose
  model       — optional model identifier (e.g. "gpt-4")
  tools       — optional list of tool names the agent may use

Rules imported from other modules (description quality, sizing, body budget)
apply equally to agents.  Slug-oriented name rules, directory-match, unknown-
field warnings, and reference-file checks are intentionally excluded.
"""

from __future__ import annotations

from collections.abc import Callable

from agenteval import config
from agenteval.parser import ParsedSkill
from agenteval.result import Diagnostic, Severity
from agenteval.rules.description import check_description_quality, make_min_score_rule
from agenteval.rules.disclosure import check_body_bloat, check_body_budget
from agenteval.rules.frontmatter import (
    check_description_max_length,
    check_description_no_xml_tags,
    check_description_non_empty,
    check_description_person_voice,
    check_description_type,
    check_yaml_anchors,
)
from agenteval.rules.sizing import make_line_count_rule, make_token_estimate_rule

# Known frontmatter fields for an agent file.
_KNOWN_AGENT_FIELDS = {"name", "description", "model", "tools", "applyTo"}


def check_agent_name_required(skill: ParsedSkill) -> list[Diagnostic]:
    """Agent must have a 'name' field in frontmatter."""
    if not skill.frontmatter:
        return []  # no-frontmatter is caught elsewhere
    if skill.frontmatter.get("name") is None:
        return [Diagnostic(
            rule="agent.frontmatter.name.required",
            severity=Severity.ERROR,
            message="Required field 'name' is missing from agent frontmatter.",
        )]
    return []


def check_agent_name_non_empty(skill: ParsedSkill) -> list[Diagnostic]:
    """Agent 'name' must be a non-empty string."""
    name = skill.frontmatter.get("name")
    if name is None:
        return []  # handled by check_agent_name_required
    if not isinstance(name, str) or not name.strip():
        return [Diagnostic(
            rule="agent.frontmatter.name.empty",
            severity=Severity.ERROR,
            message="Agent 'name' must be a non-empty string.",
        )]
    return []


def check_agent_description_required(skill: ParsedSkill) -> list[Diagnostic]:
    """Agent must have a 'description' field in frontmatter."""
    if not skill.frontmatter:
        return []
    if skill.frontmatter.get("description") is None:
        return [Diagnostic(
            rule="agent.frontmatter.description.required",
            severity=Severity.ERROR,
            message="Required field 'description' is missing from agent frontmatter.",
        )]
    return []


def check_agent_no_frontmatter(skill: ParsedSkill) -> list[Diagnostic]:
    """Agent file should have a YAML frontmatter block."""
    if not skill.frontmatter:
        return [Diagnostic(
            rule="agent.frontmatter.missing",
            severity=Severity.ERROR,
            message="Agent file has no YAML frontmatter (expected --- block with name and description).",
        )]
    return []


def check_agent_unknown_fields(skill: ParsedSkill) -> list[Diagnostic]:
    """Warn on frontmatter fields outside the known agent schema."""
    diagnostics = []
    for field_name in skill.frontmatter:
        if field_name not in _KNOWN_AGENT_FIELDS:
            diagnostics.append(Diagnostic(
                rule="agent.frontmatter.field.unknown",
                severity=Severity.WARNING,
                message=(
                    f"Unexpected agent frontmatter field '{field_name}'. "
                    f"Known fields: {', '.join(sorted(_KNOWN_AGENT_FIELDS))}."
                ),
                context=f"{field_name}: ...",
            ))
    return diagnostics


def get_agent_rules(
    max_lines: int | None = None,
    max_tokens: int | None = None,
    min_desc_score: int | None = None,
) -> list[Callable[[ParsedSkill], list[Diagnostic]]]:
    """Build the validation rule list for an agent .md file."""
    rules: list[Callable[[ParsedSkill], list[Diagnostic]]] = [
        # Structural
        check_agent_no_frontmatter,
        check_agent_name_required,
        check_agent_name_non_empty,
        check_agent_description_required,
        # Description quality (reused from skill rules)
        check_description_type,
        check_description_non_empty,
        check_description_max_length,
        check_description_no_xml_tags,
        check_description_person_voice,
        check_yaml_anchors,
        # Unknown fields
        check_agent_unknown_fields,
        # Sizing
        make_line_count_rule(max_lines if max_lines is not None else config.MAX_BODY_LINES),
        make_token_estimate_rule(max_tokens if max_tokens is not None else config.MAX_TOKENS),
        # Description quality score
        check_description_quality,
    ]
    if min_desc_score is not None and min_desc_score > 0:
        rules.append(make_min_score_rule(min_desc_score))
    # Body content checks
    rules.extend([check_body_budget, check_body_bloat])
    return rules
