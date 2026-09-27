"""Blind review #1 packet (09, v1.6 5c): three arms of equal size.

- ANIMEDEX: the top champions by fitness;
- plain baseline: the same generator model, a plain prompt that includes the taste standard;
- web baseline: the same model with its own web search, asked to find gaps first.
Up to `eval.blind.per_arm` (15) cards per arm. With fewer champions, every arm shrinks to N (never
loosen a gate to fill the packet). Cards are logline + premise only, shuffled with a fixed seed.
The answer key goes to data/blind/ (gitignored), so the packet stays blind.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from animedex.ideate.context import build_context
from animedex.integrity import name_leaks
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import raise_problems
from animedex.prompts import read_prompt
from animedex.providers.client import CallContext, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.canonical import CanonicalStore
from animedex.textutil import word_count


@dataclass
class PacketResult:
    per_arm: int
    packet: str
    ratings: str
    key: str


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


def _baseline(paths: Paths, client: LLMClient, file: str, n: int, names: tuple[set[str], set[str]],
              params: dict[str, Any] | None) -> list[dict[str, str]]:
    prompt = read_prompt(paths.prompts / file)
    client.prompt_version = prompt.version
    body = prompt.body.replace("{n}", str(n))
    user = f"Write {n} premises." + (" Limits: at most 6 web searches and 8 page fetches." if params else "")
    ctx = CallContext(pass_="IDEATE", record_id=f"baseline:{file}:{n}", title_id=None, upstream=f"n={n}")
    done = client.complete_ex(body, user, _schema(), params, ctx=ctx,
                              validate=lambda out: raise_problems(_problems(out, n, names)))
    return [{"logline": p["logline"], "premise": p["premise"]} for p in done.data["premises"]]


def build_packet(paths: Paths, settings: Any, vocab: Vocab, *, plain: LLMClient, web: LLMClient,
                 date: str | None = None) -> PacketResult:
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")
    per_arm = int((settings.eval.get("blind") or {}).get("per_arm", 15))
    state = CanonicalStore(paths).state()
    archive = {a["cell_key"]: a for a in state.get("archive", [])}
    ideas = {i["idea_id"]: i for i in state.get("idea", [])}
    ranked = sorted(archive.values(), key=lambda a: [-x for x in a["fitness"]])
    champions = [ideas[a["idea_id"]] for a in ranked if a["idea_id"] in ideas][:per_arm]
    n = len(champions)
    if n == 0:
        raise ValueError("no champions yet: run `make ideas` first")
    names = build_context(paths, settings, vocab).names
    arms = {"animedex": [{"logline": c["logline"], "premise": c["premise"], "source": c["idea_id"]} for c in champions],
            "plain": _baseline(paths, plain, "baseline_plain.md", n, names, None),
            "web": _baseline(paths, web, "baseline_web.md", n, names,
                             {"web": {"max_searches": 6, "outcome_extra": 0, "max_fetches": 8, "max_turns": 16}})}
    cards = [(arm, c) for arm, items in arms.items() for c in items]
    random.Random(f"blind:{date}").shuffle(cards)
    lines = [f"# Blind review packet, {date}", "",
             f"{len(cards)} premises from three sources, shuffled. For each one, give a rating from 1 to 5, say whether "
             "you would greenlight it, and note any taste criteria it meets (T1 never done; T2 done, never this way; "
             "T3 two ideas that work together; T4 should have existed years ago; T5 a known story retold better).",
             "Record your answers in the matching ratings file.", ""]
    key, ratings = {}, [f"# Ratings for packet_{date}.md. Fill every card: rating 1-5, greenlight yes/no, criteria.",
                        "cards:"]
    for i, (arm, c) in enumerate(cards, start=1):
        cid = f"C{i:02d}"
        lines += [f"## {cid}", "", f"**Logline.** {c['logline']}", "", f"**Premise.** {c['premise']}", ""]
        key[cid] = {"arm": arm, "source": c.get("source")}
        ratings += [f"  {cid}: {{rating: null, greenlight: null, criteria: []}}"]
    packet_path = paths.root / "eval" / "blind" / f"packet_{date}.md"
    ratings_path = paths.root / "eval" / "blind" / f"ratings_{date}.yaml"
    key_path = paths.root / "data" / "blind" / f"key_{date}.json"
    atomic_write_text(packet_path, "\n".join(lines) + "\n")
    atomic_write_text(ratings_path, "\n".join(ratings) + "\n")
    atomic_write_text(key_path, json.dumps(key, indent=2, sort_keys=True) + "\n")
    return PacketResult(n, str(packet_path.relative_to(paths.root)), str(ratings_path.relative_to(paths.root)),
                        str(key_path.relative_to(paths.root)))
