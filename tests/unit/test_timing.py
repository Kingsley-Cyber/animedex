"""Per-stage timing report from run logs (owner request 2026-09-27)."""

from __future__ import annotations

import json

import pytest

from animedex.timing import fmt, load_calls, report, summary

pytestmark = pytest.mark.unit


def row(ts, record, *, attempt=0, timing=None, cache_hit=False, pass_="VERIFY"):
    return {"ts": ts, "pass": pass_, "record_id": record, "attempt": attempt, "cache_hit": cache_hit,
            "provider": "claude_cli@2.1.251", "timing": timing}


def write(runs, run_id, rows):
    d = runs / run_id
    d.mkdir(parents=True)
    (d / "calls.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_timed_rows_break_down_and_older_rows_are_estimated(tmp_path):
    runs = tmp_path / "runs"
    write(runs, "run_20260927_020000_000001", [  # before per-stage timing: totals from timestamps
        row("2026-09-27T02:05:00+00:00", "iron_2020", pass_="P1"),
        row("2026-09-27T02:05:30+00:00", "iron_2020", pass_="P1", cache_hit=True),
        row("2026-09-27T02:07:00+00:00", "iron_2020.shorten", pass_="P1")])
    parts = {"startup_s": 2.0, "model_s": 100.0, "web_s": 190.0, "tools_s": 0.0, "other_s": 8.0}
    write(runs, "run_20260927_030000_000001", [
        row("2026-09-27T03:05:00+00:00", "iron_2020", timing={**parts, "call_s": 300.0, "pacing_s": 0.0}),
        row("2026-09-27T03:06:00+00:00", "iron_2020", attempt=1, timing={**parts, "call_s": 60.0, "pacing_s": 5.0})])
    calls = load_calls(runs)
    assert [(c.stage, c.seconds, c.estimated, c.retry) for c in calls] == [
        ("P1", 300.0, True, False), ("P1", 90.0, True, True),   # 02:00 -> 02:05, then 02:05:30 -> 02:07
        ("VERIFY", 300.0, False, False), ("VERIFY", 60.0, False, True)]
    s = summary(calls)
    assert s["VERIFY"]["web_s"] == 380.0 and s["VERIFY"]["retries"] == 1 and s["P1"]["estimated"] == 2
    md = report(calls)
    assert "| VERIFY | 2 | 6m 00s | 3m 00s | 4s | 3m 20s | 6m 20s |" in md
    assert "| P1 | 2 | 6m 30s | 3m 15s | — | — | — | — | — | 0s | 1 (1m 30s) |" in md
    assert "| iron_2020 | 6m 30s | 6m 00s | 2 (2m 30s) | 12m 30s |" in md


def test_durations_read_plainly():
    assert (fmt(4), fmt(75), fmt(3725)) == ("4s", "1m 15s", "1h 02m")


def test_rows_from_before_v2_move_the_final_answer_into_model_time(tmp_path):
    runs = tmp_path / "runs"
    old = {"startup_s": 1.0, "model_s": 30.0, "web_s": 0.0, "tools_s": 0.0, "other_s": 40.0, "api_s": 70.5,
           "call_s": 71.0, "pacing_s": 0.0}
    write(runs, "run_20260927_050000_000001", [row("2026-09-27T05:01:11+00:00", "iron_2020", pass_="P1", timing=old),
                                               row("2026-09-27T05:02:11+00:00", "iron_2020", pass_="P1",
                                                   timing={**old, "v": 2})])
    first, second = load_calls(runs)
    assert (first.parts["model_s"], first.parts["other_s"]) == (70.0, 0.0)
    assert (second.parts["model_s"], second.parts["other_s"]) == (30.0, 40.0)  # v2 rows are taken as logged



def test_input_tokens_per_stage_count_cache_reads_and_writes(tmp_path):
    runs = tmp_path / "runs"
    parts = {"startup_s": 1.0, "model_s": 50.0, "web_s": 0.0, "tools_s": 0.0, "other_s": 9.0, "v": 2}

    def logged(ts, stage, usage, **kw):
        return {**row(ts, "iron_2020", pass_=stage, timing={**parts, "call_s": 60.0, "pacing_s": 0.0}, **kw),
                "usage": usage}

    def usage(inp, read, write):
        return {"input_tokens": inp, "output_tokens": 50, "cache_read_tokens": read, "cache_write_tokens": write}

    write(runs, "run_20260927_060000_000001", [
        logged("2026-09-27T06:01:00+00:00", "P2", usage(1200, 30000, 800)),
        logged("2026-09-27T06:02:00+00:00", "P2", usage(1000, 30000, 0)),
        logged("2026-09-27T06:02:30+00:00", "P2", usage(0, 0, 0), cache_hit=True),     # cached: reads nothing
        logged("2026-09-27T06:03:00+00:00", "P3", {"input_tokens": 900, "output_tokens": 40}),  # before cache tokens
        logged("2026-09-27T06:04:00+00:00", "P3", usage(2000, 0, 5000)),
        logged("2026-09-27T06:05:00+00:00", "CHECK", usage(0, 0, 0))])                  # failed before any usage
    calls = load_calls(runs)
    assert [c.input_total for c in calls] == [32000, 31000, 0, 7000, 0]
    md = report(calls)
    assert "| Pacing | Retries | Input tokens |" in md
    p2_row = next(line for line in md.splitlines() if line.startswith("| P2 |"))
    p3_row = next(line for line in md.splitlines() if line.startswith("| P3 |"))
    check_row = next(line for line in md.splitlines() if line.startswith("| CHECK |"))
    assert p2_row.endswith("| 63,000 (31,500/call) |")
    assert p3_row.endswith("| 7,000 (7,000/call; 1 of 2 calls) |")
    assert check_row.endswith("| — |")
    s = summary(calls)
    assert (s["P2"]["input_tokens"], s["P2"]["cache_read_tokens"], s["P2"]["cache_write_tokens"]) == (2200, 60000, 800)
    assert (s["P2"]["input_total_tokens"], s["P2"]["token_calls"]) == (63000, 2)
    assert (s["P3"]["input_total_tokens"], s["P3"]["token_calls"], s["P3"]["calls"]) == (7000, 1, 2)
