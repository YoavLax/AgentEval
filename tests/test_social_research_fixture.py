from agenteval.core import validate
from agenteval.result import Severity
from tests.conftest import FIXTURES_DIR


def test_social_research_fixture_validates_without_errors():
    result = validate(
        FIXTURES_DIR / "valid_social_research.md",
        skip_dirname_check=True,
    )

    assert result.valid is True
    assert all(diagnostic.severity != Severity.ERROR for diagnostic in result.diagnostics)
