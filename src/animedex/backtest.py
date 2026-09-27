"""Retrodiction backtest (controls plan B1; statistics as gates, item 8; D-007, D-016): does the index make
the judge better at predicting how a new premise lands?

`animedex backtest [--list FILE]` / `make backtest LIST=FILE`, one command over existing stages:
1. **Titles.** `--list` resolves each line with the catalog resolver (the backfill rules: a version in
   parentheses is used as given, otherwise the most-watched adaptation) into `data/backtest/titles.yaml`.
   A title already in the corpus is refused: backtest titles are held out, and they never enter the
   corpus or the canonical data (AC-BT-1).
2. **GATHER + INTERPRET**, unchanged, against `BacktestPaths`: the same prompts, models, response cache
   and run logs, with the title list, candidates and quarantine under `data/backtest/`. The live title
   guard reads the backtest list, so every title still has a declared scope. Outputs:
   `data/backtest/gathered/<id>.json` and `data/backtest/interpret/<id>.json` (record + outcome). The
   outcome label is INTERPRET's reception-backed outcome (the label rule); a title without one is
   reported and not scored. Finished titles are not run again.
3. **Predictions.** The judge (slot `ideate_judge`, `prompts/backtest_predict.md`) predicts hit, mixed
   or flop from the premise abstraction and the power kit (the six structural enums) only, twice per
   title: with a blank brief, and with the index brief (the nearest corpus titles by structural
   Jaccard, anonymous, with their outcome labels, and the failure level, patterns and reason of the
   mixed and flop ones). No title name or id reaches the judge (AC-BT-2): the name-leak check (every
   held-out and corpus title, their character names and the proper nouns of their profiles) runs on
   the free text of every input, which is the premise abstractions and the neighbours' reasons; the
   kit and the shared values are vocabulary enums. A title whose premise leaks is not sent, a
   neighbour's reason that names anything is dropped, and a last check refuses any input that still
   holds a title id. Batches of `backtest.batch` (5) titles per call.
4. **Report** (`build/reports/backtest.md`, `build/stats/backtest.json`): per-title predictions, both
   accuracies and their difference (AC-BT-3), the exact one-sided McNemar p-value on the titles only
   one condition got right (D-016), and the sample size the observed split would need to reach
   p < 0.05. A rerun with the same titles is served from the response cache (AC-BT-4).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from animedex import stats
from animedex.analyze import structural_set
from animedex.budget import BudgetExceeded
from animedex.config import Settings
from animedex.guards import load_corpus
from animedex.ideate.context import PROFILE_PATHS, Context, build_context, jaccard
from animedex.integrity import name_list
from animedex.models import CorpusEntry
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import raise_problems
from animedex.pipeline.gather import load_gathered, run_gather
from animedex.pipeline.interpret import run_interpret
from animedex.prompts import read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.statgates import write_stage
from animedex.store.atomic import atomic_write_text
from animedex.textutil import sha256_text, stable_json, word_count

LABELS = ("hit", "mixed", "flop")
CONDITIONS = ("blank", "index")
_NAME_WORD = re.compile(r"[A-Za-z][A-Za-z'-]+")


class BacktestError(ValueError):
    pass


class _Stop(Exception):
    pass


class BacktestPaths(Paths):
    """The existing stages' paths, with the title list, candidates and quarantine under data/backtest/. Cache,
    run logs, prompts and ontology stay shared, so reruns are served from the same response cache."""

    @property
    def home(self) -> Path:
        return self.root / "data" / "backtest"

    @property
    def corpus_file(self) -> Path:
        return self.home / "titles.yaml"

    @property
    def candidates(self) -> Path:
        return self.home

    @property
    def quarantine(self) -> Path:
        return self.home / "quarantine"


def interpret_dir(paths: Paths) -> Path:
    return BacktestPaths(paths.root).home / "interpret"


def backtest_config(settings: Settings) -> dict[str, int]:
    cfg = (settings.model_extra or {}).get("backtest") or {}
    return {"batch": int(cfg.get("batch", 5)), "neighbors": int(cfg.get("neighbors", 5))}


# ---------------------------------------------------------------- 1. titles (held out; never the corpus)
def load_titles(paths: Paths) -> dict[str, CorpusEntry]:
    return load_corpus(BacktestPaths(paths.root))


def add_titles(paths: Paths, plan: Any) -> tuple[list[str], list[tuple[str, str]]]:
    """Write the plan's new titles to data/backtest/titles.yaml. `plan` is a backfill plan made against the
    corpus, so a title already in the corpus is in `plan.skipped` and is refused here. Returns (added, refused)."""
    bp = BacktestPaths(paths.root)
    have = load_corpus(bp)
    refused = [(line, f"held out titles cannot be in the corpus: {why}") for line, why in plan.skipped
               if "already in the corpus" in why]
    refused += [(line, why) for line, why in plan.skipped if "already in the corpus" not in why]
    entries, added = [e.model_dump(mode="json", exclude_none=True) for e in have.values()], []
    for r in plan.new:
        entry = {k: v for k, v in r.entry.items() if v not in (None, [], {}) or k == "role_tags"}
        entry.pop("partners", None)  # contrast partners are a corpus notion
        if entry["title_id"] in have:
            refused.append((r.line, "already in the backtest list"))
            continue
        CorpusEntry.model_validate(entry)
        entries.append(entry)
        added.append(entry["title_id"])
    if added:
        text = ("# Held-out titles for `make backtest` (controls plan B1): resolved by the catalog, never in the corpus.\n"
                + yaml.safe_dump({"titles": entries}, sort_keys=False, allow_unicode=True, width=120))
        atomic_write_text(bp.corpus_file, text)
        load_corpus(bp)  # refuse to leave a broken list
    return added, refused


# ---------------------------------------------------------------- 3. the judge's inputs
def premise_of(record: dict[str, Any]) -> str | None:
    value = ((record.get("core") or {}).get("premise_abstraction") or {}).get("value")
    return str(value).strip() if value else None


def kit_of(record: dict[str, Any]) -> str:
    """The power kit as the six structural enums (no phrases, so no names)."""
    parts = []
    for key, path in PROFILE_PATHS.items():
        block, name = path.split(".")
        value = ((record.get(block) or {}).get(name) or {}).get("value")
        if value and not str(value).startswith("other"):
            parts.append(f"{key}={value}")
    return ", ".join(parts) or "unknown"


def _held_names(entry: CorpusEntry, record: dict[str, Any], gathered: dict[str, Any] | None, vocab: Vocab
                ) -> tuple[set[str], set[str]]:
    """A held-out title's names: its title, the proper nouns of its profile phrases, and the names of the
    characters GATHER found."""
    titles, tokens = name_list({"title": [record]}, vocab)
    titles.add(entry.title.lower())
    for ch in (gathered or {}).get("characters") or []:
        tokens |= {w for w in _NAME_WORD.findall(str(ch.get("name") or "")) if w[0].isupper() and len(w) >= 3}
    return titles, tokens


def leaks(text: str, names: tuple[set[str], set[str]]) -> list[str]:
    """Names in a free text: a title as whole words (so a title that is also a common word only matches as a
    word), or a capitalized name token."""
    low = text.lower()
    hits = {t for t in names[0] if t and re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low)}
    hits |= set(_NAME_WORD.findall(text)) & names[1]
    return sorted(hits)


def neighbor_lines(ctx: Context, record: dict[str, Any], ref: str, k: int,
                   names: tuple[set[str], set[str]]) -> list[str]:
    """The index brief for one title: the `k` nearest corpus titles by structural Jaccard over their enum
    values (ties by id), anonymous, with outcome labels, and failure level, patterns and reason for the mixed
    and flop ones. A reason that names anything is left out."""
    mine = set(structural_set(record))
    scored = sorted(((jaccard(mine, set(structural_set(rec))), tid) for tid, rec in ctx.titles.items()),
                    key=lambda x: (-x[0], x[1]))
    near = [(s, tid) for s, tid in scored if s > 0][:k]
    lines = [f"{ref} neighbors: {len(near)}"]
    for i, (s, tid) in enumerate(near, start=1):
        shared = sorted(mine & set(structural_set(ctx.titles[tid])))
        label = ctx.label(tid) or "unknown"
        line = (f"{ref}.N{i}: outcome {label}; shares {', '.join(v.split('.', 1)[1] for v in shared)}; "
                f"overlap {s:.2f}")
        o = ctx.outcomes.get(tid) or {}
        if label in ("mixed", "flop"):
            patterns = sorted({p["pattern"] for p in o.get("failure_patterns") or []})
            line += f"; failure {o.get('failure_level') or 'unknown'}; patterns {', '.join(patterns) or 'none recorded'}"
            reason = str(o.get("failure_reason") or "").strip()
            if reason and not leaks(reason, names) and tid.lower() not in reason.lower():
                line += f"; reason {reason}"
        lines.append(line)
    return lines


def predict_schema(refs: list[str]) -> dict[str, Any]:
    item = {"type": "object", "additionalProperties": False, "required": ["ref", "label", "reason"],
            "properties": {"ref": {"type": "string", "enum": refs}, "label": {"type": "string", "enum": list(LABELS)},
                           "reason": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["predictions"],
            "properties": {"predictions": {"type": "array", "items": item}}}


def predict_problems(out: dict[str, Any], refs: list[str]) -> list[str]:
    got = [p.get("ref") for p in out.get("predictions") or []]
    problems = [] if sorted(got) == sorted(refs) else [f"give exactly one prediction for each of {refs}"]
    for p in out.get("predictions") or []:
        if p.get("label") not in LABELS:
            problems.append(f"{p.get('ref')}: label must be one of {list(LABELS)}")
        if not 1 <= word_count(str(p.get("reason") or "")) <= 25:
            problems.append(f"{p.get('ref')}: reason 1-25 words")
    return problems


# ---------------------------------------------------------------- the run
@dataclass
class BacktestResult:
    titles: int = 0
    gathered: int = 0
    interpreted: int = 0
    excluded: list[tuple[str, str]] = field(default_factory=list)   # (title, why it was not scored)
    predictions: dict[str, dict[str, Any]] = field(default_factory=dict)  # title -> label, blank, index
    judge_calls: dict[str, int] = field(default_factory=dict)
    stopped: str | None = None
    notes: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    report: str = ""


def score(predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Accuracy per condition, the difference, the discordant split, the exact McNemar p-value (the index
    beats the blank brief, one-sided) and the sample size that split would need (D-016)."""
    rows = [p for _, p in sorted(predictions.items()) if p.get("blank") and p.get("index")]
    n = len(rows)
    right_blank = sum(1 for p in rows if p["blank"] == p["label"])
    right_index = sum(1 for p in rows if p["index"] == p["label"])
    only_index = sum(1 for p in rows if p["index"] == p["label"] != p["blank"])
    only_blank = sum(1 for p in rows if p["blank"] == p["label"] != p["index"])
    acc_blank = round(right_blank / n, 4) if n else None
    acc_index = round(right_index / n, 4) if n else None
    return {"n": n, "accuracy_blank": acc_blank, "accuracy_index": acc_index,
            "difference": round(acc_index - acc_blank, 4) if n else None, "only_index": only_index,
            "only_blank": only_blank, "p_value": stats.mcnemar(only_index, only_blank),
            "sample_size_needed": stats.sample_size_needed(only_index, only_blank, n)}


def run_backtest(paths: Paths, settings: Settings, vocab: Vocab, *, clients: dict[str, LLMClient], run_id: str,
                 reception: Any = None, created_at: str | None = None) -> BacktestResult:
    bp = BacktestPaths(paths.root)
    cfg = backtest_config(settings)
    res = BacktestResult()
    entries = load_titles(paths)
    res.titles = len(entries)
    if not entries:
        raise BacktestError("no backtest titles yet: run `make backtest LIST=<file>` with held-out titles")
    corpus = set(load_corpus(paths))
    clash = sorted(set(entries) & corpus)
    if clash:
        raise BacktestError(f"backtest titles must be held out, but these are in the corpus: {clash}")
    ordered = [entries[t] for t in sorted(entries)]
    todo = [e for e in ordered if load_gathered(bp, e.title_id) is None]
    if todo:
        g = run_gather(bp, todo, clients["gather"], vocab, settings, run_id=run_id, reception=reception,
                       created_at=created_at)
        res.notes += [f"not gathered {t}: {why[:160]}" for t, why in g.skipped + g.quarantined]
        res.stopped = g.stopped
    out = interpret_dir(paths)
    todo = [e for e in ordered if not (out / f"{e.title_id}.json").is_file() and load_gathered(bp, e.title_id)]
    if todo and not res.stopped:
        i = run_interpret(bp, todo, clients["interpret"], vocab, settings, run_id=run_id, out_dir=out,
                          created_at=created_at)
        res.notes += [f"not interpreted {t}: {why[:160]}" for t, why in i.skipped + i.quarantined + i.failed]
        res.stopped = i.stopped
    res.gathered = sum(1 for e in ordered if load_gathered(bp, e.title_id) is not None)
    done = {e.title_id: json.loads((out / f"{e.title_id}.json").read_text(encoding="utf-8"))
            for e in ordered if (out / f"{e.title_id}.json").is_file()}
    res.interpreted = len(done)
    if not res.stopped:
        _predict(paths, settings, vocab, clients["ideate_judge"], entries, done, cfg, res)
    for e in ordered:
        if e.title_id not in done and not any(t == e.title_id for t, _ in res.excluded):
            res.excluded.append((e.title_id, "no INTERPRET output yet"))
    res.summary = score(res.predictions)
    res.report = write_report(paths, res)
    return res


def _predict(paths: Paths, settings: Settings, vocab: Vocab, client: LLMClient, entries: dict[str, CorpusEntry],
             done: dict[str, dict[str, Any]], cfg: dict[str, int], res: BacktestResult) -> None:
    bp = BacktestPaths(paths.root)
    ctx = build_context(paths, settings, vocab)
    held = {tid: _held_names(entries[tid], d["record"], load_gathered(bp, tid), vocab) for tid, d in done.items()}
    names = (set(ctx.names[0]) | {t for n in held.values() for t in n[0]},
             set(ctx.names[1]) | {t for n in held.values() for t in n[1]})
    ids = set(entries) | set(ctx.titles)
    ready: list[str] = []
    for tid in sorted(done):
        label = ((done[tid].get("outcome") or {}).get("label"))
        premise = premise_of(done[tid]["record"])
        if label not in LABELS:
            res.excluded.append((tid, "no reception-backed outcome label (INTERPRET left it for VERIFY)"))
        elif not premise:
            res.excluded.append((tid, "no premise abstraction"))
        elif found := sorted(set(leaks(premise, names)) | {i for i in ids if i in premise.lower()}):
            res.excluded.append((tid, f"name leak in the judge input: {found[:3]}"))
        else:
            ready.append(tid)
            res.predictions[tid] = {"label": label, "blank": None, "index": None}
    if not ready:
        return
    prompt = read_prompt(paths.prompts / "backtest_predict.md")
    client.prompt_version = prompt.version
    try:
        for condition in CONDITIONS:
            for start in range(0, len(ready), cfg["batch"]):
                batch = ready[start:start + cfg["batch"]]
                refs = [f"B{i}" for i in range(1, len(batch) + 1)]
                lines = [f"condition: {condition}", f"titles: {len(batch)}"]
                for ref, tid in zip(refs, batch, strict=True):
                    record = done[tid]["record"]
                    lines.append(f"{ref}: premise {premise_of(record)} | power kit {kit_of(record)}")
                    if condition == "index":
                        lines += neighbor_lines(ctx, record, ref, cfg["neighbors"], names)
                user = "\n".join(lines)
                named = sorted(i for i in ids if i in user.lower())
                if named:  # every free text was checked above; this is the last guard before a call
                    raise BacktestError(f"judge input would name {named[:3]}; nothing was sent")
                got = _call(paths, client, prompt.body, user, refs, condition, res)
                for ref, tid in zip(refs, batch, strict=True):
                    if ref in got:
                        res.predictions[tid][condition] = got[ref]
    except _Stop:
        pass
    for tid in ready:
        p = res.predictions[tid]
        missing = [c for c in CONDITIONS if p[c] is None]
        if missing:
            res.excluded.append((tid, f"no prediction ({', '.join(missing)})"))


def _call(paths: Paths, client: LLMClient, system: str, user: str, refs: list[str], condition: str,
          res: BacktestResult) -> dict[str, str]:
    ctx = CallContext(pass_="BACKTEST", record_id=f"backtest:{condition}:{sha256_text(user)[7:19]}", title_id=None,
                      upstream=sha256_text(stable_json({"condition": condition, "input": user})))
    res.judge_calls[condition] = res.judge_calls.get(condition, 0) + 1
    try:
        done = client.complete_ex(system, user, predict_schema(refs), None, ctx=ctx,
                                  validate=lambda out: raise_problems(predict_problems(out, refs)))
    except (BudgetExceeded, RateLimited, CliAuthError) as exc:
        res.stopped = str(exc)
        raise _Stop from exc
    except (InvalidOutput, ProviderError) as exc:
        res.notes.append(f"judge ({condition}) gave no usable answer: {str(exc)[:160]}")
        return {}
    return {p["ref"]: p["label"] for p in done.data["predictions"]}


# ---------------------------------------------------------------- 4. the report
def write_report(paths: Paths, res: BacktestResult) -> str:
    s = res.summary
    lines = ["# Retrodiction backtest", "",
             "Does the index make the judge better at predicting how a premise lands? The judge sees each held-out "
             "title's premise abstraction and power kit only (no names), once with a blank brief and once with the "
             "index brief: the nearest indexed titles, anonymous, with their outcomes and failure patterns.", "",
             f"Titles: {res.titles} held out; {res.gathered} gathered, {res.interpreted} interpreted, {s['n']} scored.",
             ""]
    if s["n"]:
        lines += ["| | Blank brief | Index brief |", "|---|---|---|",
                  f"| Accuracy | {s['accuracy_blank']:.2f} | {s['accuracy_index']:.2f} |", "",
                  f"Difference (index minus blank): {s['difference']:+.2f}.", "",
                  f"Only one condition was right on {s['only_index'] + s['only_blank']} title(s): the index brief on "
                  f"{s['only_index']}, the blank brief on {s['only_blank']}. Exact one-sided McNemar p-value (the index "
                  f"beats the blank brief): {s['p_value']:.4f}.",
                  "Sample size needed for p < 0.05 at this split: "
                  + (f"{s['sample_size_needed']} titles." if s["sample_size_needed"] else
                     "none (the index brief does not lead)." if s["only_index"] <= s["only_blank"] else
                     "more than 2000 titles."), "",
                  "## Per title", "", "| Title | Outcome | Blank brief | Index brief |", "|---|---|---|---|"]
        for tid, p in sorted(res.predictions.items()):
            if p.get("blank") and p.get("index"):
                lines.append(f"| {tid} | {p['label']} | {_mark(p['blank'], p['label'])} | {_mark(p['index'], p['label'])} |")
    else:
        lines += ["No title could be scored yet."]
    if res.excluded:
        lines += ["", "## Not scored", "", *[f"- {tid}: {why}" for tid, why in sorted(res.excluded)]]
    if res.stopped:
        lines += ["", f"Paused: {res.stopped}. Run `make backtest` again later; finished work is kept and cached."]
    if res.notes:
        lines += ["", "## Notes", "", *[f"- {n}" for n in res.notes]]
    out = paths.reports / "backtest.md"
    atomic_write_text(out, "\n".join(lines) + "\n")
    write_stage(paths, "backtest", {**s, "titles": res.titles, "gathered": res.gathered, "interpreted": res.interpreted,
                                    "excluded": [list(x) for x in sorted(res.excluded)],
                                    "predictions": {t: p for t, p in sorted(res.predictions.items())},
                                    "judge_calls": res.judge_calls, "stopped": res.stopped})
    return str(out.relative_to(paths.root))


def _mark(pred: str, label: str) -> str:
    return f"{pred} ({'right' if pred == label else 'wrong'})"
