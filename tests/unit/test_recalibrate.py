"""`animedex recalibrate` (v1.7 §2): scores premise pairs with the embedder, proposes clone thresholds,
compares the fallback, writes a report, and never changes config. Fake embedders with exact cosines;
no Polymath, no Ollama."""

from __future__ import annotations

import math
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from animedex.cli import app
from animedex.config import load_settings
from animedex.embeddings.base import EmbedderUnavailable, Readiness
from animedex.embeddings.recalibrate import load_pairs, misjudged, propose, run_recalibration

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
PAIRS = {  # pair id -> the cosine the fake primary gives it
    "s1": 0.93, "s2": 0.88, "s3": 0.81,
    "d1": 0.42, "d2": 0.67, "d3": 0.55,
}


def write_pairs(path: Path, ids=PAIRS) -> Path:
    shared = "A keeper sees what each sailor owes the sea and chooses who pays in every storm."
    data = {"version": 1, "similar": [], "different": []}
    for pid in ids:
        kind = "similar" if pid.startswith("s") else "different"
        a = shared if pid in ("s1", "d1") else f"First synthetic premise for pair {pid}."
        data[kind].append({"id": pid, "note": f"note {pid}", "a": a, "b": f"Second synthetic premise for pair {pid}."})
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


class Exact:
    """Vectors built so that each pair's cosine is exactly its target: every `a` text is a basis vector,
    every `b` text leans toward its `a` by the target (a shared `a` keeps one vector)."""

    def __init__(self, pairs_file: Path, targets: dict[str, float], name: str = "fake/primary", ready: bool = True):
        self.name, self.ready = name, ready
        pairs = load_pairs(pairs_file)
        texts = sorted({p.a for p in pairs} | {p.b for p in pairs})
        axis = {t: i for i, t in enumerate(texts)}
        self.table: dict[str, list[float]] = {}
        for p in pairs:
            self.table.setdefault(p.a, [1.0 if i == axis[p.a] else 0.0 for i in range(len(texts))])
        for p in pairs:
            t = targets[p.id]
            self.table[p.b] = [t * x for x in self.table[p.a]]
            self.table[p.b][axis[p.b]] += math.sqrt(1 - t * t)
        self.calls = 0

    def readiness(self):
        if self.ready:
            return Readiness(True)
        return Readiness(False, "Polymath's embedder at 127.0.0.1:8742 isn't ready", "start Polymath's embedder",
                         "Polymath's embedder at 127.0.0.1:8742 isn't ready. Start it, then run the same command again.")

    def embed(self, texts):
        self.calls += 1
        return [self.table[t] for t in texts]


def test_the_shipped_pairs_are_ten_and_ten_and_name_free():
    pairs = load_pairs(REPO / "eval" / "recalibration" / "pairs.yaml")
    assert sum(p.kind == "similar" for p in pairs) == 10 and sum(p.kind == "different" for p in pairs) == 10
    for p in pairs:
        for text in (p.a, p.b):
            words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
            assert not [w for w in words[1:] if w[0].isupper()], (p.id, text)  # no names: only the first word capitalized


def test_propose_sits_between_the_scores_and_flags_what_today_misjudges(tmp_path):
    pairs = load_pairs(write_pairs(tmp_path / "pairs.yaml"))
    scores = [PAIRS[p.id] for p in pairs]
    p = propose(pairs, scores, current=0.90)
    assert (p.lowest_similar, p.lowest_similar_id, p.highest_different, p.highest_different_id) == (0.81, "s3", 0.67, "d2")
    assert p.recommended == 0.74 and p.separated and p.wrong == []
    assert p.current_wrong == ["s2", "s3"]  # today's 0.90 lets two clones through on this scale


def test_propose_keeps_a_narrow_gap_and_reports_overlap(tmp_path):
    pairs = load_pairs(write_pairs(tmp_path / "pairs.yaml"))
    narrow = {**PAIRS, "s3": 0.8049, "d2": 0.8001}
    p = propose(pairs, [narrow[x.id] for x in pairs], current=0.90)
    assert p.recommended == 0.8025 and p.wrong == []  # rounding to 0.80 would reject d2
    overlap = {**PAIRS, "s3": 0.60, "d2": 0.70}
    q = propose(pairs, [overlap[x.id] for x in pairs], current=0.90)
    assert not q.separated and q.recommended == 0.65 and sorted(q.wrong) == ["d2", "s3"]
    assert misjudged(pairs, [overlap[x.id] for x in pairs], 0.65) == q.wrong


def test_recalibration_reports_both_backends_and_never_changes_config(repo, tmp_path):
    import re

    pairs_file = write_pairs(tmp_path / "pairs.yaml")
    # pin "today's" threshold in this test's own config, so the scenario doesn't follow production config
    repo.config_file.write_text(re.sub(r"premise_cosine_reject: [0-9.]+", "premise_cosine_reject: 0.90",
                                       repo.config_file.read_text()))
    config_before = repo.config_file.read_bytes()
    shifted = {**{k: v + 0.01 for k, v in PAIRS.items()}, "d3": 0.60}
    primary, fallback = Exact(pairs_file, PAIRS), Exact(pairs_file, shifted, name="fake/fallback")
    res = run_recalibration(repo, load_settings(repo), {}, pairs_file=pairs_file, backends=[primary, fallback])
    assert primary.calls == 1 and fallback.calls == 1  # one batch per backend
    assert res.primary == "fake/primary" and res.proposal.recommended == 0.74
    assert res.scores == [PAIRS[p.id] for p in res.pairs]
    c = res.comparison
    assert c.name == "fake/fallback" and (c.largest_difference, c.largest_difference_id) == (0.05, "d3") and c.wrong == []
    text = res.report.read_text(encoding="utf-8")
    assert res.report == repo.reports / "recalibration.md"
    for needle in ("**0.74**", "0.8100 (s3)", "0.6700 (d2)", "misjudges s2, s3", "premise_cosine_with_structural` (0.55)",
                   "Largest per-pair difference: 0.0500 (d3)", "| s3 | similar | 0.8100 | caught |", "note d1"):
        assert needle in text
    assert repo.config_file.read_bytes() == config_before
    summary = "\n".join(res.summary())
    assert "recommended premise_cosine_reject 0.74" in summary and "unchanged" in summary


def test_recalibration_needs_the_primary_and_skips_an_unready_fallback(repo, tmp_path):
    pairs_file = write_pairs(tmp_path / "pairs.yaml")
    with pytest.raises(EmbedderUnavailable, match=r"runs on the primary embedder \(fake/primary\)\. Polymath's"):
        run_recalibration(repo, load_settings(repo), {}, pairs_file=pairs_file,
                          backends=[Exact(pairs_file, PAIRS, ready=False), Exact(pairs_file, PAIRS)])
    res = run_recalibration(repo, load_settings(repo), {}, pairs_file=pairs_file,
                            backends=[Exact(pairs_file, PAIRS), Exact(pairs_file, PAIRS, name="fake/fb", ready=False)])
    assert res.comparison is None and res.fallback_note.startswith("`fake/fb` was not compared: Polymath's")
    assert "was not compared" in res.report.read_text(encoding="utf-8")


def test_bad_pairs_files_are_refused(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({"similar": [{"id": "s1", "a": "same text", "b": "same text"}],
                                   "different": [{"id": "s1", "a": "x", "b": ""}]}))
    with pytest.raises(ValueError) as exc:
        load_pairs(bad)
    for needle in ("used twice", "a and b are the same text", "needs an id and two texts"):
        assert needle in str(exc.value)


def test_make_recalibrate_prints_the_proposal(repo, tmp_path, monkeypatch):
    from animedex.embeddings import recalibrate

    pairs_file = write_pairs(tmp_path / "pairs.yaml")
    config_before = repo.config_file.read_bytes()
    monkeypatch.setattr(recalibrate, "embedding_backends", lambda settings, env, transport=None: [
        Exact(pairs_file, PAIRS)])
    result = CliRunner().invoke(app, ["recalibrate", "--pairs", str(pairs_file)])
    assert result.exit_code == 0, result.output
    assert "recommended premise_cosine_reject 0.74" in result.output and "No fallback is configured" in result.output
    assert "report -> build/reports/recalibration.md" in result.output
    assert "  s3  similar    0.8100  caught" in result.output and "  d2  different  0.6700  passes" in result.output
    assert repo.config_file.read_bytes() == config_before
    monkeypatch.setattr(recalibrate, "embedding_backends", lambda settings, env, transport=None: [
        Exact(pairs_file, PAIRS, ready=False)])
    down = CliRunner().invoke(app, ["recalibrate", "--pairs", str(pairs_file)])
    assert down.exit_code == 1 and "Start it, then run the same command again." in down.output
