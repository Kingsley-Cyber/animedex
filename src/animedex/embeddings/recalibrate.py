"""`animedex recalibrate` (v1.7 §2): score known premise pairs with the configured embedder and propose
clone thresholds for it. Each embedding model scores on its own scale, so the premise-cosine gate is
recalibrated whenever the model changes. This only proposes: config/settings.yaml is never changed, and
Kingsley approves the numbers.

- Pairs: eval/recalibration/pairs.yaml, abstract, original, name-free premises. `similar` pairs are two
  phrasings of one premise (a clone the gate must catch); `different` pairs are genuinely different
  premises, several sharing a setting or role (what the gate must let through).
- Calibrates on the primary backend (`models.embeddings`: Polymath's embedder). When the fallback (the
  Ollama copy) is also reachable, it scores the same pairs, and the report gives the largest per-pair
  difference, so Kingsley can see whether the thresholds transfer.
- Output: build/reports/recalibration.md and a short summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from animedex.embeddings.base import (
    Embedder,
    EmbedderUnavailable,
    cosine,
    embedding_backends,
    readiness,
)

KINDS = ("similar", "different")


@dataclass(frozen=True)
class Pair:
    id: str
    kind: str  # similar | different
    a: str
    b: str
    note: str = ""


def load_pairs(path: Path) -> list[Pair]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pairs = [Pair(id=str(item.get("id") or "").strip(), kind=kind, a=" ".join(str(item.get("a") or "").split()),
                  b=" ".join(str(item.get("b") or "").split()), note=str(item.get("note") or "").strip())
             for kind in KINDS for item in (data.get(kind) or [])]
    problems = [f"{kind}: give at least one pair" for kind in KINDS if not any(p.kind == kind for p in pairs)]
    ids = [p.id for p in pairs]
    problems += [f"pair id {i!r} is used twice" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for p in pairs:
        if not p.id or not p.a or not p.b:
            problems.append(f"pair {p.id or '?'}: needs an id and two texts (a, b)")
        elif p.a == p.b:
            problems.append(f"pair {p.id}: a and b are the same text")
    if problems:
        raise ValueError("; ".join(problems))
    return pairs


def score(embedder: Embedder, pairs: list[Pair]) -> list[float]:
    """Cosine of each pair's two texts, embedded in one batch."""
    vectors = embedder.embed([p.a for p in pairs] + [p.b for p in pairs])
    n = len(pairs)
    if len(vectors) != 2 * n:
        raise EmbedderUnavailable(f"{embedder.name} returned {len(vectors)} vectors for {2 * n} texts")
    return [round(cosine(vectors[i], vectors[n + i]), 4) for i in range(n)]


def misjudged(pairs: list[Pair], scores: list[float], threshold: float) -> list[str]:
    """Pairs the gate gets wrong at `threshold` (it rejects at cosine >= threshold): a similar pair
    below it slips through, a different pair at or above it is rejected."""
    return [p.id for p, s in zip(pairs, scores, strict=True) if (p.kind == "similar") != (s >= threshold)]


@dataclass(frozen=True)
class Proposal:
    lowest_similar: float
    lowest_similar_id: str
    highest_different: float
    highest_different_id: str
    recommended: float
    wrong: list[str]          # misjudged at the recommended value
    current: float
    current_wrong: list[str]  # misjudged at today's premise_cosine_reject

    @property
    def separated(self) -> bool:
        return self.lowest_similar > self.highest_different


def propose(pairs: list[Pair], scores: list[float], current: float) -> Proposal:
    """The recommended `premise_cosine_reject` is the midpoint between the lowest similar-pair score and
    the highest different-pair score (2 decimals, or 4 when the gap is too narrow to round)."""
    low = min((s, p.id) for p, s in zip(pairs, scores, strict=True) if p.kind == "similar")
    high = max((s, p.id) for p, s in zip(pairs, scores, strict=True) if p.kind == "different")
    middle = (low[0] + high[0]) / 2
    recommended = round(middle, 2)
    if low[0] > high[0] and misjudged(pairs, scores, recommended):
        recommended = round(middle, 4)
    return Proposal(low[0], low[1], high[0], high[1], recommended, misjudged(pairs, scores, recommended),
                    current, misjudged(pairs, scores, current))


@dataclass(frozen=True)
class Comparison:
    name: str
    scores: list[float]
    largest_difference: float
    largest_difference_id: str
    wrong: list[str]  # the fallback's misjudged pairs at the recommended value


@dataclass
class RecalibrationResult:
    primary: str
    pairs: list[Pair]
    scores: list[float]
    proposal: Proposal
    comparison: Comparison | None
    fallback_note: str
    report: Path

    def pair_lines(self) -> list[str]:
        """One line per pair: id, kind, cosine (and the fallback's), and what the recommended value does."""
        p, c, out = self.proposal, self.comparison, []
        for i, pair in enumerate(self.pairs):
            s = self.scores[i]
            verdict = ("caught" if s >= p.recommended else "passes") + (" (misjudged)" if pair.id in p.wrong else "")
            fallback = f"  fallback {c.scores[i]:.4f}" if c is not None else ""
            out.append(f"  {pair.id}  {pair.kind:<9}  {s:.4f}{fallback}  {verdict}")
        return out

    def summary(self) -> list[str]:
        p = self.proposal
        sims = sum(x.kind == "similar" for x in self.pairs)
        lines = [f"recalibrate: {self.primary} on {sims} similar + {len(self.pairs) - sims} different pairs",
                 f"  lowest similar {p.lowest_similar:.4f} ({p.lowest_similar_id}); highest different "
                 f"{p.highest_different:.4f} ({p.highest_different_id})",
                 f"  recommended premise_cosine_reject {_t(p.recommended)}"
                 + ("" if p.separated else f" (no value separates them: {len(p.wrong)} pair(s) misjudged)"),
                 f"  today's {_t(p.current)} misjudges {len(p.current_wrong)} pair(s)"]
        c = self.comparison
        if c is not None:
            lines.append(f"  fallback {c.name}: largest per-pair difference {c.largest_difference:.4f} "
                         f"({c.largest_difference_id}); misjudges {len(c.wrong)} pair(s) at {_t(p.recommended)}")
        elif self.fallback_note:
            lines.append(f"  fallback: {self.fallback_note}")
        lines.append("  config/settings.yaml unchanged: these numbers are a proposal")
        return lines


def _ids(ids: list[str]) -> str:
    return ", ".join(ids) if ids else "none"


def _t(value: float) -> str:
    """A threshold as written in config: 2 decimals, or 4 when it needs them."""
    return f"{value:.2f}" if round(value, 2) == value else f"{value:.4f}"


def render_report(res: RecalibrationResult, gates: dict[str, Any], pairs_file: str) -> str:
    p, c = res.proposal, res.comparison
    with_structural = gates.get("premise_cosine_with_structural", 0.55)
    structural = gates.get("structural_jaccard_reject", 0.70)
    sims = sum(x.kind == "similar" for x in res.pairs)
    lines = ["# Clone-threshold recalibration", "",
             f"Embedder: `{res.primary}` (the primary). Pairs: {sims} similar and {len(res.pairs) - sims} different, "
             f"from `{pairs_file}`. Each embedding model scores on its own scale, so these numbers replace nothing "
             "until Kingsley approves them: `config/settings.yaml` is unchanged.", "",
             "## Proposal", "",
             "| | Value |", "|---|---|",
             f"| Lowest similar-pair cosine | {p.lowest_similar:.4f} ({p.lowest_similar_id}) |",
             f"| Highest different-pair cosine | {p.highest_different:.4f} ({p.highest_different_id}) |",
             f"| Recommended `premise_cosine_reject` | **{_t(p.recommended)}** (midpoint) |",
             f"| Pairs misjudged at {_t(p.recommended)} | {_ids(p.wrong)} |",
             f"| Today's `premise_cosine_reject` | {_t(p.current)}; misjudges {_ids(p.current_wrong)} |", ""]
    if not p.separated:
        lines += ["No single value separates the pairs: some different pair scores at least as high as some "
                  "similar pair. Review the misjudged pairs before choosing a value.", ""]
    lines += ["**How `premise_cosine_with_structural` interacts (report only).** The clone gate rejects a card for "
              "premise wording only when both hold: its highest premise cosine against any title reaches "
              f"`premise_cosine_reject`, and its highest structural overlap with any title reaches "
              f"`premise_cosine_with_structural` ({_t(with_structural)}). Below that overlap, a card is never rejected "
              f"for wording alone, however close; at `structural_jaccard_reject` ({_t(structural)}) structure rejects "
              f"on its own. These pairs test wording only, so this run says nothing new about {_t(with_structural)}.", "",
             "## Every pair", "",
             "The gate rejects at cosine ≥ the threshold: a similar pair should be caught, a different pair should pass.",
             ""]
    head = "| Pair | Kind | Cosine | At " + f"{_t(p.recommended)}"
    if c is not None:
        head += f" | {c.name} | Difference"
    lines += [head + " | Note |", "|---" * (head.count("|")) + "|---|"]
    for i, pair in enumerate(res.pairs):
        s = res.scores[i]
        verdict = "caught" if s >= p.recommended else "passes"
        if pair.id in p.wrong:
            verdict += " (misjudged)"
        row = f"| {pair.id} | {pair.kind} | {s:.4f} | {verdict}"
        if c is not None:
            row += f" | {c.scores[i]:.4f} | {abs(s - c.scores[i]):.4f}"
        lines.append(row + f" | {pair.note} |")
    lines += ["", "## Fallback", ""]
    if c is not None:
        lines += [f"`{c.name}` scored the same pairs. Largest per-pair difference: {c.largest_difference:.4f} "
                  f"({c.largest_difference_id}). At {_t(p.recommended)} it misjudges: {_ids(c.wrong)}. "
                  + ("The recommended value holds on the fallback too." if not c.wrong else
                     "The recommended value does not hold on the fallback for the pairs listed."), ""]
    else:
        lines += [res.fallback_note or "No fallback is configured.", ""]
    return "\n".join(lines)


def run_recalibration(paths: Any, settings: Any, env: dict[str, str], *, pairs_file: Path | None = None,
                      backends: list[Embedder] | None = None, transport: Any = None) -> RecalibrationResult:
    """Score the pairs on the primary backend (and the fallback when it's reachable), propose, and
    write build/reports/recalibration.md. Raises EmbedderUnavailable when the primary isn't ready."""
    from animedex.store.atomic import atomic_write_text

    pairs_path = pairs_file or paths.root / "eval" / "recalibration" / "pairs.yaml"
    pairs = load_pairs(pairs_path)
    chain = backends if backends is not None else embedding_backends(settings, env, transport=transport)
    primary, fallback = chain[0], (chain[1] if len(chain) > 1 else None)
    state = readiness(primary)
    if not state.ok:
        raise EmbedderUnavailable(f"Recalibration runs on the primary embedder ({primary.name}). {state.alone}")
    scores = score(primary, pairs)
    proposal = propose(pairs, scores, float(settings.gates.get("premise_cosine_reject", 0.90)))
    comparison, note = None, ""
    if fallback is None:
        note = "No fallback is configured."
    elif not (fstate := readiness(fallback)).ok:
        note = f"`{fallback.name}` was not compared: {fstate.alone}"
    else:
        try:
            fscores = score(fallback, pairs)
        except EmbedderUnavailable as exc:
            note = f"`{fallback.name}` was not compared: {exc}"
        else:
            diffs = [abs(a - b) for a, b in zip(scores, fscores, strict=True)]
            worst = max(range(len(diffs)), key=diffs.__getitem__)
            comparison = Comparison(fallback.name, fscores, round(diffs[worst], 4), pairs[worst].id,
                                    misjudged(pairs, fscores, proposal.recommended))
    report = paths.reports / "recalibration.md"
    result = RecalibrationResult(primary.name, pairs, scores, proposal, comparison, note, report)
    try:
        shown = pairs_path.resolve().relative_to(paths.root.resolve()).as_posix()
    except ValueError:
        shown = str(pairs_path)
    atomic_write_text(report, render_report(result, dict(settings.gates), shown))
    return result
