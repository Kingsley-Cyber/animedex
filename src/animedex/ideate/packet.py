"""Blind review #1 packet (09, v1.6 5c; fair baselines, controls A5 + decision 1, M5): three arms of
equal size, and the only difference between them is access to the index.

- `animedex`: the top champions by fitness (the archive);
- `baseline_loop` (baseline 1): the same ideation loop with an empty brief (`animedex ideate --arm
  baseline_loop`). Its best card per cell, ranked by the same fitness, as the archive would pick;
- `baseline_single` (baseline 2): one "write N premises" call.
Every arm uses the same model (the `ideate_generate` slot), the same taste standard
(`prompts/taste_standard.md`) and the same steering rules. No arm searches the web while generating;
every packet card then gets the same prior-art check (the `prior_art` slot), recorded in the answer
key only. Up to `eval.blind.per_arm` (15) cards per arm; with fewer, every arm shrinks to N (never
loosen a gate to fill the packet). Cards show logline + premise only, shuffled with a fixed seed. The
answer key (arm, source, prior-art verdict) goes to data/blind/ (gitignored), so the packet stays blind.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from animedex.ideate.context import build_context
from animedex.ideate.llm import prior_art_problems, prior_art_schema
from animedex.ideate.run import baseline_file, card_fitness
from animedex.ideate.standard import render_prompt
from animedex.ideate.steering import load_rules, rule_lines
from animedex.integrity import name_leaks
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import raise_problems, url_set
from animedex.prompts import read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.canonical import CanonicalStore
from animedex.store.jsonl import read_jsonl
from animedex.textutil import sha256_text, stable_json, word_count

ARMS = ("animedex", "baseline_loop", "baseline_single")
PRIOR_ART_LIMITS = {"max_searches": 4, "outcome_extra": 0, "max_fetches": 6, "max_turns": 12}


@dataclass
class PacketResult:
    per_arm: int
    packet: str
    ratings: str
    key: str
    prior_art: dict[str, int]


def _schema() -> dict[str, Any]:
    item = {"type": "object", "additionalProperties": False, "required": ["logline", "premise"],
            "properties": {"logline": {"type": "string"}, "premise": {"type": "string"}}}
    return {"type": "object", "additionalProperties": False, "required": ["premises"],
            "properties": {"premises": {"type": "array", "items": item}}}


def _problems(out: dict[str, Any], n: int, names: tuple[set[str], set[str]]) -> list[str]:
    items = out.get("premises") or []
    problems = [] if len(items) == n else [f"give exactly {n} premises (got {len(items)})"]
    for i, p in enumerate(items):
        if not 1 <= word_count(str(p.get("logline") or "")) <= 30:
            problems.append(f"premises[{i}].logline: 1-30 words")
        if not 1 <= word_count(str(p.get("premise") or "")) <= 120:
            problems.append(f"premises[{i}].premise: 1-120 words")
        if "http" in f"{p.get('logline')} {p.get('premise')}":
            problems.append(f"premises[{i}]: no links")
        leaks = name_leaks(f"{p.get('logline')} {p.get('premise')}", *names)
        if leaks:
            problems.append(f"premises[{i}]: reuses existing names {leaks[:3]}")
    return problems


def single_user(n: int, rules: list[str]) -> str:
    """Baseline 2's user message: the count and the same steering lines every arm gets."""
    return "\n".join([f"Write {n} premises.", *rules])


def baseline_single(paths: Paths, client: LLMClient, n: int, names: tuple[set[str], set[str]],
                    date: str) -> list[dict[str, str]]:
    """Baseline 2: one call, the same model, standard and rules as ANIMEDEX; no web while generating."""
    prompt = render_prompt(paths, "baseline_single.md", n=n)
    client.prompt_version = prompt.version
    user = single_user(n, rule_lines(load_rules(paths)))
    ctx = CallContext(pass_="IDEATE", record_id=f"baseline_single:{n}", title_id=None,
                      upstream=sha256_text(stable_json({"n": n, "input": user})))
    done = client.complete_ex(prompt.system, user, _schema(), None, ctx=ctx,
                              validate=lambda out: raise_problems(_problems(out, n, names)))
    return [{"logline": p["logline"], "premise": p["premise"], "source": f"baseline_single.{date}.{i:02d}"}
            for i, p in enumerate(done.data["premises"], start=1)]


def baseline_loop_cards(paths: Paths, n: int) -> list[dict[str, Any]]:
    """Baseline 1's best passing card per cell, ranked by fitness then id (what an archive would hold)."""
    best: dict[str, dict[str, Any]] = {}
    for card in read_jsonl(baseline_file(paths, "ideas")):
        if card["status"] == "rejected" or card.get("arm") != "baseline_loop":
            continue
        inc = best.get(card["grid_cell"])
        if inc is None or (card_fitness(card), inc["idea_id"]) > (card_fitness(inc), card["idea_id"]):
            best[card["grid_cell"]] = card
    ranked = sorted(best.values(), key=lambda c: ([-x for x in card_fitness(c)], c["idea_id"]))
    return ranked[:n]


def _prior_art(paths: Paths, client: LLMClient, cards: list[tuple[str, dict[str, Any]]], date: str
               ) -> dict[str, dict[str, Any]]:
    """The same web check for every arm's final cards: is this premise already done?"""
    prompt = read_prompt(paths.prompts / "prior_art.md")
    client.prompt_version = prompt.version
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(cards), 4):
        chunk = cards[i:i + 4]
        refs = [cid for cid, _ in chunk]
        texts = [f"- {cid} (never done): an original story. Logline: {c['logline']} Premise: {c['premise']}"
                 for cid, c in chunk]
        user = "CLAIMS\n" + "\n".join(texts) + (f"\n\nLimits: at most {PRIOR_ART_LIMITS['max_searches']} searches "
                                                f"and {PRIOR_ART_LIMITS['max_fetches']} page fetches in total.")

        def check(data: dict[str, Any], meta: dict[str, Any], _refs: list[str] = refs) -> None:
            raise_problems(prior_art_problems(data, _refs, url_set(((meta or {}).get("web") or {}).get("urls"))))

        ctx = CallContext(pass_="IDEATE", record_id=f"packet_prior_art:{date}:{'+'.join(refs)}", title_id=None,
                          upstream=sha256_text(stable_json(texts)))
        try:
            done = client.complete_ex(prompt.body, user, prior_art_schema(refs), {"web": PRIOR_ART_LIMITS}, ctx=ctx,
                                      validate=check)
            verdicts = {v["ref"]: v for v in done.data["checks"]}
        except (RateLimited, CliAuthError):
            raise  # a plan limit or login problem pauses the packet; finished calls stay cached
        except (InvalidOutput, ProviderError):
            verdicts = {}  # unreadable twice or a failed call: the cards stay inconclusive, as in the loop
        for cid in refs:
            v = verdicts.get(cid) or {"verdict": "inconclusive", "counterexamples": []}
            out[cid] = {"verdict": v["verdict"], "counterexamples": v.get("counterexamples") or []}
    return out


def build_packet(paths: Paths, settings: Any, vocab: Vocab, *, single: LLMClient, prior_art: LLMClient | None = None,
                 date: str | None = None) -> PacketResult:
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")
    per_arm = int((settings.eval.get("blind") or {}).get("per_arm", 15))
    state = CanonicalStore(paths).state()
    archive = {a["cell_key"]: a for a in state.get("archive", [])}
    ideas = {i["idea_id"]: i for i in state.get("idea", [])}
    ranked = sorted(archive.values(), key=lambda a: ([-x for x in a["fitness"]], a["idea_id"]))
    champions = [ideas[a["idea_id"]] for a in ranked if a["idea_id"] in ideas][:per_arm]
    if not champions:
        raise ValueError("no champions yet: run `make ideas` first")
    loop = baseline_loop_cards(paths, per_arm)
    if not loop:
        raise ValueError("no baseline-loop cards yet: run `make ideas ARM=baseline_loop` first (baseline 1 is "
                         "the same loop with an empty brief)")
    n = min(len(champions), len(loop))
    names = build_context(paths, settings, vocab).names
    arms = {"animedex": [{"logline": c["logline"], "premise": c["premise"], "source": c["idea_id"]}
                         for c in champions[:n]],
            "baseline_loop": [{"logline": c["logline"], "premise": c["premise"], "source": c["idea_id"]}
                              for c in loop[:n]],
            "baseline_single": baseline_single(paths, single, n, names, date)}
    cards = [(arm, c) for arm in ARMS for c in arms[arm]]
    random.Random(f"blind:{date}").shuffle(cards)
    ids = [f"C{i:02d}" for i in range(1, len(cards) + 1)]
    checked = _prior_art(paths, prior_art, [(cid, c) for cid, (_, c) in zip(ids, cards, strict=True)], date) \
        if prior_art is not None else {}
    lines = [f"# Blind review packet, {date}", "",
             f"{len(cards)} premises from three sources, shuffled. For each one, give a rating from 1 to 5, say whether "
             "you would greenlight it, and note any taste criteria it meets (T1 never done; T2 done, never this way; "
             "T3 two ideas that work together; T4 should have existed years ago; T5 a known story retold better).",
             "Record your answers in the matching ratings file.", ""]
    key, ratings = {}, [f"# Ratings for packet_{date}.md. Fill every card: rating 1-5, greenlight yes/no, criteria.",
                        "cards:"]
    for cid, (arm, c) in zip(ids, cards, strict=True):
        lines += [f"## {cid}", "", f"**Logline.** {c['logline']}", "", f"**Premise.** {c['premise']}", ""]
        pa = checked.get(cid)
        key[cid] = {"arm": arm, "source": c.get("source"), "prior_art": pa["verdict"] if pa else None,
                    "counterexamples": pa["counterexamples"] if pa else []}
        ratings += [f"  {cid}: {{rating: null, greenlight: null, criteria: []}}"]
    cards_json = [{"id": cid, "logline": c["logline"], "premise": c["premise"]}
                  for cid, (_, c) in zip(ids, cards, strict=True)]  # no arm, no source: the page stays blind
    atomic_write_text(paths.root / "eval" / "blind" / f"packet_{date}.json",
                      json.dumps({"date": date, "cards": cards_json}, indent=2, ensure_ascii=False) + "\n")
    packet_path = paths.root / "eval" / "blind" / f"packet_{date}.md"
    ratings_path = paths.root / "eval" / "blind" / f"ratings_{date}.yaml"
    key_path = paths.root / "data" / "blind" / f"key_{date}.json"
    atomic_write_text(packet_path, "\n".join(lines) + "\n")
    atomic_write_text(ratings_path, "\n".join(ratings) + "\n")
    atomic_write_text(key_path, json.dumps(key, indent=2, sort_keys=True) + "\n")
    tally: dict[str, int] = {}
    for v in checked.values():
        tally[v["verdict"]] = tally.get(v["verdict"], 0) + 1
    return PacketResult(n, str(packet_path.relative_to(paths.root)), str(ratings_path.relative_to(paths.root)),
                        str(key_path.relative_to(paths.root)), tally)
