"""Tests for Fix 5: Callable return type annotations."""

from collections.abc import Callable

from agenteval.parser import ParsedSkill
from agenteval.result import Diagnostic
from agenteval.rules.compat import make_strict_vscode_rule
from agenteval.rules.description import make_min_score_rule


def test_make_min_score_rule_returns_callable():
    """make_min_score_rule returns a proper Callable, not a bare function."""
    rule = make_min_score_rule(50)
    assert callable(rule)
    assert isinstance(rule, Callable)


def test_make_strict_vscode_rule_returns_callable():
    """make_strict_vscode_rule returns a proper Callable, not a bare function."""
    rule = make_strict_vscode_rule()
    assert callable(rule)
    assert isinstance(rule, Callable)
