"""G0 D1: fetched web text never reaches disk; logs keep url + sha256 + length."""

from __future__ import annotations

import pytest

from animedex.store import runlog as runlog_mod
from animedex.store.runlog import RedactionError, RunLog, TransientText, redact

pytestmark = pytest.mark.unit

PAGE = "Synthetic fetched page text that stands in for an episode summary and must never be stored anywhere. " * 3


def test_redact_replaces_text_with_url_hash_length():
    t = TransientText("https://example.org/page", PAGE)
    out = redact(f"Check this: {PAGE} end", [t])
    assert PAGE not in out
    assert "url=https://example.org/page" in out and "sha256:" in out and f"chars={len(PAGE)}" in out


def test_run_log_files_never_contain_fetched_text(tmp_path):
    t = TransientText("https://example.org/page", PAGE)
    log = RunLog(tmp_path, "run_x")
    log.log_call(pass_="VERIFY", record_id="ironvale_circuit_2021", provider="mock", model="mock/m",
                 cache_key="sha256:" + "a" * 64, cache_hit=False, attempt=0, input_tokens=10, output_tokens=5,
                 cost_usd=0.001, system="system prompt", user=f"Verify against: {PAGE}",
                 response=f'{{"note": "{PAGE[:50]}... echoed {PAGE}"}}', transients=[t])
    log.write_ledger()
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert PAGE not in path.read_text(encoding="utf-8"), path


def test_redaction_refuses_when_text_survives(monkeypatch):
    monkeypatch.setattr(runlog_mod.TransientText, "placeholder", property(lambda self: self.text + "!"))
    with pytest.raises(RedactionError):
        redact(PAGE, [TransientText("https://example.org/page", PAGE)])


def test_ledger_totals(tmp_path):
    log = RunLog(tmp_path, "run_y")
    for cost in (0.5, 0.25):
        log.log_call(pass_="P1", record_id="t_2020", provider="p", model="m", cache_key="sha256:" + "b" * 64,
                     cache_hit=False, attempt=0, input_tokens=100, output_tokens=50, cost_usd=cost,
                     system="s", user="u", response="{}")
    import json

    ledger = json.loads(log.write_ledger().read_text())
    assert ledger["total_cost_usd"] == 0.75
    assert ledger["by_pass_record"]["P1:t_2020"] == {"input": 200, "output": 100, "calls": 2, "cost_usd": 0.75}
