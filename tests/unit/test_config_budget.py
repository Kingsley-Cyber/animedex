"""Settings, .env parsing, live-readiness (G1a list), budget caps."""

from __future__ import annotations

import pytest

from animedex.budget import Budget, BudgetConfigError, BudgetExceeded, price_for
from animedex.config import is_placeholder, live_problems, load_settings, parse_env_file

pytestmark = pytest.mark.unit


def test_env_file_parsing(tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nA=1\nexport B="two words"\nC=has#hash\n\nD=\n')
    assert parse_env_file(env) == {"A": "1", "B": "two words", "C": "has#hash", "D": ""}


def test_placeholders():
    assert is_placeholder("<set>") and is_placeholder(" <cheap-model> ")
    assert not is_placeholder("claude-model") and not is_placeholder(3)


def test_template_blocks_live_runs_with_a_concrete_list(repo):
    problems = live_problems(load_settings(repo), {})
    joined = "\n".join(problems)
    for needle in ("models.p1.model", "ANTHROPIC_API_KEY", "budget.run_cap_usd", "search.backend"):
        assert needle in joined


def test_filled_settings_have_no_problems(repo):
    s = load_settings(repo)
    for spec in s.models.values():
        spec.model = "real-model"
    s.pricing = {f"{p}/real-model": {"input_per_mtok": 1, "output_per_mtok": 2} for p in s.providers}
    s.budget = {"run_cap_usd": 5, "per_title_cap_usd": 1, "per_episode_cap_usd": 0.2}
    s.search = {"backend": "brave"}
    env = {"OPENAI_COMPATIBLE_BASE_URL": "https://x", "OPENAI_COMPATIBLE_API_KEY": "k", "ANTHROPIC_API_KEY": "k"}
    assert live_problems(s, env) == []
    assert price_for(s, "anthropic", "real-model").cost(1_000_000, 500_000) == pytest.approx(2.0)


def test_budget_requires_numeric_caps_and_stops_after_cap(repo):
    with pytest.raises(BudgetConfigError):
        Budget.from_settings(load_settings(repo))
    b = Budget(run_cap=1.0, per_title_cap=0.5, per_episode_cap=0.1)
    b.check("t_2020")
    b.charge(0.6, "t_2020")
    with pytest.raises(BudgetExceeded, match="title cap"):
        b.check("t_2020")
    b.check("other_2021")
    b.charge(0.5, "other_2021")
    with pytest.raises(BudgetExceeded, match="run cap"):
        b.check("third_2022")
