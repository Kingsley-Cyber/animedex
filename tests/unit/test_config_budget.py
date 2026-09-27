"""Settings, .env parsing, live-readiness (G1a list), budget caps."""

from __future__ import annotations

import pytest

from animedex.budget import Budget, BudgetConfigError, BudgetExceeded
from animedex.config import load_settings, parse_env_file

pytestmark = pytest.mark.unit


def test_env_file_parsing(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nA=1\nexport B="two words"\nC=has#hash\n\nD=\n')
    assert parse_env_file(env) == {"A": "1", "B": "two words", "C": "has#hash", "D": ""}


TEMPLATE_PROVIDERS = {"check": "openai_compatible", "ideate_judge": "openai_compatible",
                      "eval_match": "openai_compatible", "embeddings": "local"}  # every other slot: anthropic




def test_budget_requires_a_call_cap_and_stops_at_it(repo):
    settings = load_settings(repo)
    settings.budget = {}
    with pytest.raises(BudgetConfigError):
        Budget.from_settings(settings)
    b = Budget(2)
    b.check_calls()
    b.count_call()
    b.count_call()
    with pytest.raises(BudgetExceeded, match="2/2 calls this run"):
        b.check_calls()
