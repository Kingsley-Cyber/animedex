"""IDEATE (05, v1.6 + the M5 rulings of 2026-09-27): MAP-Elites over the grid in `ideate.grid_dims`.

Per generation: plan candidates (seeded) -> generate one card per call from the M5 call brief
(`ideate/brief.py`) -> deterministic gates (clone, novelty, graveyard; one rework) -> judge in
batches (different family: H1 consequence test, failure conditions, coherence, runway, and on a
premise-level graveyard match whether `why_different` answers the flop's recorded failure; taste
with evidence; one rework) -> deterministic taste evidence -> prior-art web check for every T1/T4
claim -> fitness -> archive (<=1 idea per cell; a cell's fitness never decreases) -> canonicalize
before the next generation.

`index=False` is baseline 1 of the blind review (controls decision 1): the same loop (prompt,
operators, gates, judge, prior-art check) with an empty brief, so only index access differs. Its
cards carry `arm: baseline_loop` and live in data/blind/baseline_loop/, never in the canonical
ideas, the archive or the champions. The operators that need index evidence (a flop's recorded
failure, a census zero) do not run there.

Ideation runs share one call cap across generate, judge and prior art (`ideate.calls_per_run`, 60);
other runs keep `budget.calls_per_run` (40). At the cap the run stops cleanly and the next
`animedex ideate` continues from the archive. Never loosen a gate to fill cells.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

from animedex.budget import Budget, BudgetExceeded
from animedex.config import Settings, is_placeholder
from animedex.embeddings.base import Embedder
from animedex.ideate.brief import Brief, BriefOverCap, build_brief
from animedex.ideate.context import PROFILE_PATHS, Context, build_context, cell_key
from animedex.ideate.gates import GateResult, Similarity, run_gates
from animedex.ideate.llm import (
    PLACEHOLDER_TITLE,
    card_from,
    generate_problems,
    generate_schema,
    judge_card_text,
    judge_problems,
    judge_schema,
    prior_art_problems,
    prior_art_schema,
)
from animedex.ideate.standard import render_prompt
from animedex.ideate.steering import Rule, load_rules
from animedex.models import IdeaCard, PriorArtCheck
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.canonicalize import canonicalize
from animedex.pipeline.common import provenance, raise_problems, url_set, write_candidates
from animedex.prompts import PromptFile, RenderedPrompt, read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.cache import upstream_hash
from animedex.store.canonical import CanonicalStore
from animedex.store.jsonl import dumps_jsonl, read_jsonl
from animedex.store.quarantine import quarantine
from animedex.textutil import sha256_text, stable_json

BORROWABLE = ("game", "exam_or_school", "job_or_bureaucracy", "market_or_economy", "sport", "social_rating",
              "law_or_contract", "card_or_collection", "crafting_or_cooking", "military_rank", "ritual_or_religion")
# operators that run only on index evidence (a flop's recorded failure; a census zero): never in baseline 1
INDEX_ONLY_OPERATORS = ("revive_execution_flop", "borrow_system")
DEFAULT_THEME = "What does power cost the one who holds it?"


class _Stop(Exception):
    pass


@dataclass
class Plan:
    ref: str
    theme: str
    operator: str
    target: dict[str, str]
    atoms: list[dict[str, Any]]
    revival: dict[str, Any] | None = None
    borrowed: str | None = None
    parent_ids: list[str] = field(default_factory=list)


@dataclass
class Cand:
    plan: Plan
    idea_id: str
    card: dict[str, Any] | None = None
    gates: GateResult | None = None
    reworked: bool = False
    rejected: str | None = None
    judged: dict[str, Any] | None = None
    brief: Brief | None = None


@dataclass
class IdeateResult:
    arm: str = "animedex"
    generations: list[int] = field(default_factory=list)
    candidates: int = 0
    passed: int = 0          # cards that passed every gate (both arms)
    placed: int = 0          # cards placed in the archive (ANIMEDEX only)
    champions: int = 0
    rejected: Counter = field(default_factory=Counter)
    reworks: int = 0
    prior_art: Counter = field(default_factory=Counter)
    stopped: str | None = None
    diversity_alarm: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class _Run:
    paths: Paths
    settings: Settings
    vocab: Vocab
    clients: dict[str, LLMClient]
    ctx: Context
    sim: Similarity
    gen_prompt: RenderedPrompt
    judge_prompt: PromptFile
    art_prompt: PromptFile
    rules: list[Rule]
    run_id: str
    created_at: str | None
    dims: list[str]
    index: bool
    res: IdeateResult

    @property
    def arm(self) -> str:
        return "animedex" if self.index else "baseline_loop"


def grid_cells(vocab: Vocab, dims: list[str]) -> list[dict[str, str]]:
    values = [[v for v in vocab.enum(d) if v != "other"] for d in dims]
    return [{d.split(".")[-1]: v for d, v in zip(dims, combo, strict=True)} for combo in product(*values)]


def better(a: list[float], b: list[float]) -> bool:
    return list(a) > list(b)


def ideation_budget(settings: Settings) -> Budget:
    """One call cap for an ideation run's generate, judge and prior-art calls: `ideate.calls_per_run`
    (60, owner ruling 2026-09-27: one run covers three generations). Other runs keep 40."""
    budget = Budget.from_settings(settings)
    cap = settings.ideate.get("calls_per_run")
    if cap is not None and not is_placeholder(cap):
        budget.calls_per_run = int(cap)
    return budget


def baseline_file(paths: Paths, name: str) -> Path:
    """Baseline 1's own store (kept blind, backed up with data/blind): `ideas` or `prior_art`."""
    return paths.root / "data" / "blind" / "baseline_loop" / f"{name}.jsonl"


def _merge_jsonl(path: Path, records: list[dict[str, Any]], key: str) -> None:
    have = {r[key]: r for r in read_jsonl(path)}
    have.update({r[key]: r for r in records})
    atomic_write_text(path, dumps_jsonl([have[k] for k in sorted(have)]))


# ---------------------------------------------------------------- planning
def eligible_operators(ctx: Context, settings: Settings) -> list[str]:
    ops = list(settings.ideate.get("operators") or [])
    out = []
    engines_from_hits = [a for a in ctx.pool if a["atom_kind"] == "engine" and ctx.label(a["title_id"]) == "hit"]
    for op in ops:
        if op == "revive_execution_flop" and not (revival_sources(ctx) and engines_from_hits):
            continue
        if op == "borrow_system" and not open_borrowed(ctx):
            continue
        if op == "import_lane" and not any(a["medium"] != "anime" for a in ctx.pool):
            continue
        if op == "combine_mechanisms" and len({a["title_id"] for a in ctx.pool}) < 2:
            continue
        out.append(op)
    return out


def revival_sources(ctx: Context) -> list[dict[str, Any]]:
    """Execution-level flops with evidence (a web-sourced level or Kingsley's override)."""
    out = []
    for g in ctx.execution_flops():
        o = ctx.outcomes.get(g["title_id"]) or {}
        if o.get("failure_level_source") == "owner" or o.get("failure_evidence_ref"):
            out.append({**g, "failure_evidence_ref": o.get("failure_evidence_ref")})
    return out


def open_borrowed(ctx: Context) -> list[str]:
    """v1.6 5b: a borrowed system qualifies only with zero occurrences as a power system in the census. That zero
    is census-backed novelty, so it counts only over the 200 powered census rows of the M5 floor, which also
    clears the rule of three (3/n < 0.02, statistics as gates)."""
    if not ctx.census_size or not ctx.census_zeros_trusted:
        return []
    return [s for s in BORROWABLE if ctx.census_systems.get(s, 0) == 0]


def pick_atoms(rng: random.Random, pool: list[dict[str, Any]], n: int, first: list[dict[str, Any]] | None = None
               ) -> list[dict[str, Any]]:
    chosen = list(first or [])
    if not chosen:
        chosen.append(rng.choice(pool))
    while len(chosen) < n:
        taken = {c["title_id"] for c in chosen}
        options = [a for a in pool if a["title_id"] not in taken]
        if not options:
            break
        other_media = [a for a in options if a["medium"] not in {c["medium"] for c in chosen}]
        chosen.append(rng.choice(other_media or options))
    return chosen


def plan_generation(ctx: Context, settings: Settings, vocab: Vocab, rng: random.Random, gen: int, archive: dict,
                    ideas: dict[str, dict[str, Any]]) -> list[Plan]:
    cfg = settings.ideate
    dims = list(cfg.get("grid_dims"))
    cells = grid_cells(vocab, dims)
    empty = [c for c in cells if cell_key(c, dims) not in archive]
    ops = eligible_operators(ctx, settings)
    if not ctx.pool or not ops:
        return []
    order = ops[:]
    rng.shuffle(order)
    plans = []
    champions = [ideas[r["idea_id"]] for r in archive.values() if r["idea_id"] in ideas]
    for k in range(int(cfg.get("candidates_per_generation", 12))):
        op = order[k % len(order)]
        target = rng.choice(empty or cells)
        theme = rng.choice(ctx.themes) if ctx.themes else DEFAULT_THEME
        parents: list[str] = []
        revival, borrowed = None, None
        if op == "revive_execution_flop":
            revival = rng.choice(revival_sources(ctx))
            hits = [a for a in ctx.pool if a["atom_kind"] == "engine" and ctx.label(a["title_id"]) == "hit"]
            atoms = pick_atoms(rng, hits, 1)
        elif op == "borrow_system":
            borrowed = rng.choice(open_borrowed(ctx))
            atoms = pick_atoms(rng, ctx.pool, 2)
        elif op == "import_lane":
            outside = [a for a in ctx.pool if a["medium"] != "anime"]
            atoms = pick_atoms(rng, ctx.pool, 2, first=[rng.choice(outside)])
        else:
            n = 2 if op == "combine_mechanisms" else rng.choice([1, 2, 2, 3])
            seed_atoms = None
            if champions and gen > 0 and rng.random() < 0.5:
                parent = rng.choice(champions)
                parents = [parent["idea_id"]]
                keep = [a for a in ctx.pool if a["transfer_id"] in parent["atoms_used"]][:2]
                seed_atoms = keep or None
            atoms = pick_atoms(rng, ctx.pool, max(n, len(seed_atoms or [])), first=seed_atoms)
        plans.append(Plan(ref=f"g{gen}c{k:02d}", theme=theme, operator=op, target=target, atoms=atoms,
                          revival=revival, borrowed=borrowed, parent_ids=parents))
    return plans


def plan_baseline(ctx: Context, settings: Settings, vocab: Vocab, rng: random.Random, gen: int,
                  occupied: set[str]) -> list[Plan]:
    """Baseline 1: the same operator rotation and cell targeting, with no atoms, parents, flops or systems.
    Its own passing cards mark the cells it has filled (it never touches the ANIMEDEX archive)."""
    cfg = settings.ideate
    dims = list(cfg.get("grid_dims"))
    cells = grid_cells(vocab, dims)
    empty = [c for c in cells if cell_key(c, dims) not in occupied]
    ops = [op for op in cfg.get("operators") or [] if op not in INDEX_ONLY_OPERATORS]
    if not ops:
        return []
    order = ops[:]
    rng.shuffle(order)
    plans = []
    for k in range(int(cfg.get("candidates_per_generation", 12))):
        theme = rng.choice(ctx.themes) if ctx.themes else DEFAULT_THEME
        plans.append(Plan(ref=f"bl.g{gen}c{k:02d}", theme=theme, operator=order[k % len(order)],
                          target=rng.choice(empty or cells), atoms=[]))
    return plans


# ---------------------------------------------------------------- the run
def _call(r: _Run, ref: str, client: LLMClient, system: str, user: str, schema: dict[str, Any], *, upstream: str,
          validate: Callable[..., Any], params: dict[str, Any] | None = None, pass_: str = "IDEATE",
          meta: dict[str, Any] | None = None) -> Any:
    ctx = CallContext(pass_=pass_, record_id=ref, title_id=None, upstream=upstream, meta=meta)
    try:
        return client.complete_ex(system, user, schema, params, ctx=ctx, validate=validate)
    except InvalidOutput as exc:
        quarantine(r.paths.quarantine, pass_, "idea", ref, exc.raw, exc.errors)
        r.res.rejected["format"] += 1
    except (BudgetExceeded, RateLimited, CliAuthError) as exc:
        r.res.stopped = str(exc)
        raise _Stop from exc
    except ProviderError as exc:
        r.res.notes.append(f"{ref}: {exc}")
        r.res.rejected["provider"] += 1
    return None


def run_ideate(paths: Paths, settings: Settings, vocab: Vocab, *, clients: dict[str, LLMClient], embedder: Embedder,
               run_id: str, generations: int | None = None, created_at: str | None = None,
               index: bool = True) -> IdeateResult:
    cfg = settings.ideate
    dims = list(cfg.get("grid_dims"))
    h1_min = int(cfg.get("h1_min_changed_dimensions", 2))
    res = IdeateResult(arm="animedex" if index else "baseline_loop")
    ctx = build_context(paths, settings, vocab)
    if index:
        existing = CanonicalStore(paths).state()
        archive = {a["cell_key"]: a for a in existing.get("archive", [])}
        ideas = {i["idea_id"]: i for i in existing.get("idea", [])}
        if not ctx.pool:
            res.notes.append("no load-bearing-eligible transfer atoms yet: finish M3 (P2-P4) first")
            return res
    else:
        archive = {}  # baseline 1 never enters the archive
        ideas = {i["idea_id"]: i for i in read_jsonl(baseline_file(paths, "ideas"))}
        if not ctx.titles:
            res.notes.append("no indexed titles yet: the gates and the judge need the corpus")
            return res
    start_gen = max((i["generation"] for i in ideas.values()), default=-1) + 1
    gen_prompt = render_prompt(paths, "ideate_generate.md")
    judge_prompt = read_prompt(paths.prompts / "ideate_judge.md")
    art_prompt = read_prompt(paths.prompts / "prior_art.md")
    clients["ideate_generate"].prompt_version = gen_prompt.version
    clients["ideate_judge"].prompt_version = judge_prompt.version
    if "prior_art" in clients:
        clients["prior_art"].prompt_version = art_prompt.version
    r = _Run(paths=paths, settings=settings, vocab=vocab, clients=clients, ctx=ctx, sim=Similarity(embedder, ctx),
             gen_prompt=gen_prompt, judge_prompt=judge_prompt, art_prompt=art_prompt, rules=load_rules(paths),
             run_id=run_id, created_at=created_at, dims=dims, index=index, res=res)
    seed = int(cfg.get("seed", 7))
    n_gen = generations if generations is not None else int(cfg.get("generations", 3))
    counter = len([i for i in ideas.values() if i["provenance"]["run_id"] == run_id])
    batch = int(cfg.get("judge_batch", 4))
    for gen in range(start_gen, start_gen + n_gen):
        if index:
            plans = plan_generation(ctx, settings, vocab, random.Random(f"{seed}:{gen}"), gen, archive, ideas)
        else:
            occupied = {i["grid_cell"] for i in ideas.values() if i["status"] != "rejected"}
            plans = plan_baseline(ctx, settings, vocab, random.Random(f"{seed}:baseline_loop:{gen}"), gen, occupied)
        if not plans:
            res.notes.append("no eligible operator or atom pool")
            break
        cands = []
        for plan in plans:
            counter += 1
            cands.append(Cand(plan, idea_id=f"idea.{run_id}{'' if index else '_bl'}.{counter:03d}"))
        try:
            _generate_all(r, cands, gen, rework_notes={})
            _gate_all(r, cands, gen)
            _judge_all(r, cands, batch, h1_min)
            redo = [c for c in cands if c.card and not c.rejected and c.judged and _post_judge_rework(c)]
            for c in redo:
                if c.reworked:
                    c.rejected = f"judge: {', '.join(_post_judge_rework(c))} (after one rework)"
            redo = [c for c in redo if not c.rejected]
            if redo:
                res.reworks += len(redo)
                notes = {c.plan.ref: _post_judge_rework(c) for c in redo}
                for c in redo:
                    c.reworked, c.judged = True, None
                _generate_all(r, redo, gen, rework_notes=notes)
                _gate_all(r, redo, gen, allow_rework=False)
                _judge_all(r, redo, batch, h1_min)
                for c in redo:
                    if c.card and not c.rejected and c.judged and _post_judge_rework(c):
                        c.rejected = f"judge: {', '.join(_post_judge_rework(c))} (after one rework)"
            _taste_evidence(ctx, cands)
            art_records = _prior_art(r, cands) if "prior_art" in clients else []
        except _Stop:
            _finish_generation(r, cands, archive, ideas, gen, [], stopped=True)
            break
        _finish_generation(r, cands, archive, ideas, gen, art_records)
        res.generations.append(gen)
    res.champions = len(archive) if index else 0
    res.diversity_alarm = diversity_alarm(archive, dims, settings) if index else None
    return res


def _generate_all(r: _Run, cands: list[Cand], gen: int, *, rework_notes: dict[str, list[str]]) -> None:
    client = r.clients["ideate_generate"]
    title_ids = sorted(r.ctx.titles)
    for c in cands:
        p = c.plan
        notes = rework_notes.get(p.ref)
        try:
            brief = build_brief(r.ctx, r.settings, theme=p.theme, operator=p.operator, target=p.target, atoms=p.atoms,
                                revival=p.revival, borrowed=p.borrowed, rules=r.rules, rework=notes, index=r.index)
        except BriefOverCap as exc:  # refused before any call is made
            c.card, c.rejected, c.brief = None, str(exc), None
            continue
        c.brief = brief
        schema = generate_schema(r.vocab, list(brief.aliases), title_ids if r.index else None, brief.flop_ids)
        grid = cell_key(p.target, r.dims)
        prov0 = provenance("IDEATE", r.run_id, None, r.gen_prompt.version, r.vocab, r.created_at)

        def check(out: dict[str, Any], _p: Plan = p, _grid: str = grid, _prov: dict = prov0, _b: Brief = brief) -> None:
            raise_problems(generate_problems(out, r.ctx, _p.atoms, _p.operator, _grid, _prov, aliases=_b.aliases,
                                             flop_ids=_b.flop_ids, arm=r.arm))

        done = _call(r, f"{p.ref}.rework" if notes else p.ref, client, r.gen_prompt.system, brief.text, schema,
                     # the key covers the whole input (the brief, and the schema with every corpus id), not just
                     # the plan: a changed corpus never serves a stale cached card (owner fix, 2026-09-27)
                     upstream=upstream_hash([{"plan": {"theme": p.theme, "operator": p.operator, "target": p.target,
                                                       "atoms": [a["transfer_id"] for a in p.atoms],
                                                       "revival": (p.revival or {}).get("title_id"),
                                                       "borrowed": p.borrowed, "rework": notes or [], "arm": r.arm}},
                                             {"input": sha256_text(brief.text),
                                              "schema": sha256_text(stable_json(schema))}]),
                     validate=check, meta={"brief": brief.meta})
        if done is None:
            c.card, c.rejected = None, "format: generation failed validation twice"
            continue
        prov = provenance("IDEATE", r.run_id, done, r.gen_prompt.version, r.vocab, r.created_at)
        card = card_from(done.data, idea_id=c.idea_id, atoms=p.atoms, operator=p.operator, theme=p.theme,
                         grid_cell=cell_key(done.data["profile"], r.dims), generation=gen, prov=prov,
                         revival=p.revival, aliases=brief.aliases, arm=r.arm,
                         closest=None if r.index else PLACEHOLDER_TITLE)
        card["parent_ids"] = list(p.parent_ids)
        card["_atoms"] = p.atoms
        c.card, c.rejected = card, None


def _measure_gates(r: _Run, c: Cand) -> None:
    c.gates = run_gates(c.card, r.ctx, r.sim, r.settings.gates)
    if not r.index:  # baseline 1 saw no title ids: its closest title is the one the clone gate measures
        c.card["closest_existing"] = c.gates.nearest or c.gates.cosine_nearest or sorted(r.ctx.titles)[0]


def _gate_all(r: _Run, cands: list[Cand], gen: int, allow_rework: bool = True) -> None:
    for c in cands:
        if c.card is None or c.rejected:
            continue
        _measure_gates(r, c)
        if c.gates.fatal:
            c.rejected = c.gates.fatal[0]
    redo = [c for c in cands if c.card and not c.rejected and c.gates and c.gates.failures]
    if not redo:
        return
    if not allow_rework:
        for c in redo:
            c.rejected = c.gates.failures[0] + " (after one rework)"
        return
    r.res.reworks += len(redo)
    notes = {c.plan.ref: list(c.gates.failures) for c in redo}
    for c in redo:
        c.reworked = True
    _generate_all(r, redo, gen, rework_notes=notes)
    for c in redo:
        if c.card is None or c.rejected:
            continue
        _measure_gates(r, c)
        if c.gates.fatal or c.gates.failures:
            c.rejected = (c.gates.fatal or c.gates.failures)[0] + " (after one rework)"


def _facts(ctx: Context, c: Cand) -> list[str]:
    return judge_facts(ctx, c.gates, c.card)


def judge_facts(ctx: Context, g: GateResult, card: dict[str, Any]) -> list[str]:
    """The deterministic facts the judge may cite (the same for generated and diagnosed cards). A novel key
    pair never seen together is an untried combination (T1 evidence); one seen rarely is only rare."""
    key = g.pmi_key_pair or {}
    novelty = ("no untried combination" if not g.novel_combo else
               f"untried combination: {g.novelty_basis}" if key.get("together") == 0 else
               f"rare combination, seen before: {g.novelty_basis}")
    facts = [novelty,
             f"coverage {'adequate' if ctx.adequate else 'thin (zeros untrusted)'} (rule of three: 3/n = "
             f"{ctx.rule_of_three:.3f} over {ctx.adequacy_n} rows; open below 0.02)",
             f"graveyard matches: {', '.join(g.graveyard_hits) or 'none'}"]
    lanes = sorted(set(card["bridge"]) & (ctx.lanes["imported"] | ctx.lanes["export"]))
    facts.append(f"lane concepts used: {', '.join(lanes) or 'none'}")
    if card.get("revival_of"):
        facts.append(f"revives execution-level flop {card['revival_of']['title_id']}")
    return facts


def graveyard_matches(ctx: Context, gates: GateResult | None) -> list[dict[str, Any]]:
    hits = set(gates.graveyard_hits) if gates else set()
    return [g for g in ctx.graveyard if g["title_id"] in hits]


def _judge_all(r: _Run, cands: list[Cand], batch: int, h1_min: int) -> None:
    live = [c for c in cands if c.card and not c.rejected]
    for i in range(0, len(live), batch):
        chunk = live[i:i + batch]
        refs = [c.plan.ref for c in chunk]
        matched = [c.plan.ref for c in chunk if c.gates and c.gates.graveyard_hits]
        conditions = sorted({f for c in chunk for a in c.plan.atoms for f in a["failure_conditions"]})
        user = "\n\n".join(judge_card_text(c.plan.ref, c.card, r.ctx, c.plan.atoms, _facts(r.ctx, c),
                                           graveyard_matches(r.ctx, c.gates)) for c in chunk)
        done = _call(r, "judge:" + "+".join(refs), r.clients["ideate_judge"], r.judge_prompt.body, user,
                     judge_schema(refs, conditions),
                     upstream=sha256_text(stable_json([*({k: v for k, v in c.card.items() if k not in ("provenance",
                                                                                                    "_atoms", "idea_id")}
                                                         for c in chunk), {"input": sha256_text(user)}])),
                     validate=lambda out, _r=refs, _m=matched: raise_problems(judge_problems(out, _r, _m)))
        if done is None:
            for c in chunk:
                c.rejected = "judge: no valid verdict"
            continue
        by_ref = {j["ref"]: j for j in done.data["cards"]}
        for c in chunk:
            # a card can trigger only its own atoms' failure conditions (none for baseline 1, which has no atoms)
            own = {f for a in c.plan.atoms for f in a["failure_conditions"]}
            j = {**by_ref[c.plan.ref], "failure_conditions_triggered": [
                f for f in by_ref[c.plan.ref]["failure_conditions_triggered"] if f in own]}
            c.judged = j
            dims = {d: bool(j[f"{d}_differs"]) for d in ("choices", "relationships", "outcomes")}
            h1 = sum(dims.values()) >= h1_min
            g = c.card["gates"]
            g.update(structural_jaccard_max=c.gates.structural_max, procedural_jaccard_max=c.gates.procedural_max,
                     premise_cosine_max=c.gates.cosine_max, novel_combo=c.gates.novel_combo,
                     pmi_key_pair=c.gates.pmi_key_pair, graveyard_hits=list(c.gates.graveyard_hits),
                     failure_conditions_triggered=list(j["failure_conditions_triggered"]),
                     consequence_test={**dims, "h1_pass": h1}, coherence=j["coherence"])
            c.card["runway"] = {"hurts_by_arc5": bool(j["runway_hurts_by_arc5"]), "reason": j["runway_reason"]}
            c.card["taste"] = {"criteria_met": [], "evidence": {}, "hard_fail": not h1}
            if not h1:
                c.rejected = f"H1: surface change (fewer than {h1_min} consequence dimensions differ)"
            elif j["coherence"] == "fail":
                c.rejected = f"coherence: {j['coherence_reason']}"


def _post_judge_rework(c: Cand) -> list[str]:
    """Judge answers that earn one rework, then rejection: failure conditions, a runway "no", and (M5
    ruling) a why_different that does not answer a matched premise-level flop's recorded failure."""
    j, out = c.judged or {}, []
    if j.get("failure_conditions_triggered"):
        out.append("triggers failure conditions: " + "; ".join(j["failure_conditions_triggered"]))
    if j and not j.get("runway_hurts_by_arc5", True):
        out.append(f"runway: the cost stops hurting by arc 5 ({j.get('runway_reason')})")
    if j and c.gates and c.gates.graveyard_hits and j.get("why_different_verdict") == "fail":
        out.append("why_different: it does not answer the matched flop's recorded failure "
                   f"({j.get('why_different_reason')}); say what changes so that failure cannot repeat")
    return out


def _taste_evidence(ctx: Context, cands: list[Cand]) -> None:
    """Keep a claimed criterion only when its required evidence exists (05 taste table)."""
    for c in cands:
        if not c.card or c.rejected or not c.judged:
            continue
        g, card = c.gates, c.card
        media = {a["medium"] for a in c.plan.atoms}
        kept: dict[str, str] = {}
        for t in c.judged.get("taste") or []:
            crit, ev = t["criterion"], t["evidence"]
            if crit == "T1" and not (g.novel_combo and (g.pmi_key_pair or {}).get("together") == 0 and ctx.adequate
                                     and not g.graveyard_hits):
                continue  # never done: the key pair has zero co-occurrence on an adequate sample
            if crit == "T3" and not ((len(set(card["bridge"])) >= 2 or len(media) >= 2) and card["gates"]["coherence"] == "pass"):
                continue
            if crit == "T4" and not (set(card["bridge"]) & (ctx.lanes["imported"] | ctx.lanes["export"])
                                     or (g.novel_combo and ctx.adequate)):
                continue
            if crit == "T5" and not card.get("revival_of"):
                continue
            kept.setdefault(crit, ev)
        card["taste"] = {"criteria_met": sorted(kept), "evidence": kept, "hard_fail": False}


def _prior_art(r: _Run, cands: list[Cand]) -> list[dict[str, Any]]:
    """v1.6: every T1/T4 absence claim gets a native web check; a counterexample or an unclear result
    removes the claim."""
    claims = []
    for c in cands:
        if not c.card or c.rejected:
            continue
        for crit in ("T1", "T4"):
            if crit in c.card["taste"]["criteria_met"]:
                claims.append((c, crit))
    if not claims:
        return []
    client = r.clients["prior_art"]
    limits = {"max_searches": 4, "outcome_extra": 0, "max_fetches": 6, "max_turns": 12}
    records = []
    for i in range(0, len(claims), 4):
        chunk = claims[i:i + 4]
        refs = [f"{c.plan.ref}:{crit}" for c, crit in chunk]
        texts = []
        for (c, crit), ref in zip(chunk, refs, strict=True):
            what = (f"an original story where {c.card['transformation']['what_changed']}; engine cost: "
                    f"{c.card['engine']['cost']}; dilemma: {c.card['engine']['dilemma']}")
            texts.append(f"- {ref} ({'never done' if crit == 'T1' else 'absent in anime'}): {what}. "
                         f"Premise: {c.card['logline']}")
        user = "CLAIMS\n" + "\n".join(texts) + f"\n\nLimits: at most {limits['max_searches']} searches and " \
               f"{limits['max_fetches']} page fetches in total."

        def check(out: dict[str, Any], meta: dict[str, Any], _refs: list[str] = refs) -> None:
            raise_problems(prior_art_problems(out, _refs, url_set(((meta or {}).get("web") or {}).get("urls"))))

        done = _call(r, "prior_art:" + "+".join(refs), client, r.art_prompt.body, user, prior_art_schema(refs),
                     upstream=sha256_text(stable_json(texts)), validate=check, params={"web": limits}, pass_="IDEATE")
        verdicts = {v["ref"]: v for v in (done.data["checks"] if done else [])}
        web = (done.meta.get("web") or {}) if done else {}
        for (c, crit), ref in zip(chunk, refs, strict=True):
            v = verdicts.get(ref) or {"verdict": "inconclusive", "counterexamples": []}
            r.res.prior_art[v["verdict"]] += 1
            taste = c.card["taste"]
            if v["verdict"] == "clear":
                taste["evidence"][crit] = (taste["evidence"][crit] + "; prior-art clear")[:300]
            else:
                taste["criteria_met"] = [x for x in taste["criteria_met"] if x != crit]
                taste["evidence"].pop(crit, None)
            prov = provenance("IDEATE", r.run_id, done, r.art_prompt.version, r.vocab, r.created_at)
            records.append({"check_id": f"pa.{c.idea_id}.{crit}", "claim_kind": crit, "subject_id": c.idea_id,
                            "claim": texts[refs.index(ref)][:600], "queries": list(web.get("queries") or [])[:8],
                            "verdict": v["verdict"], "counterexamples": v.get("counterexamples") or [],
                            "provenance": prov})
    return records


def card_fitness(card: dict[str, Any], backed: int = 0) -> list[float]:
    """Lexicographic fitness (05): rating first when Kingsley gave one, then gates passed, evidenced
    taste criteria, episode-backed atoms used, lower max structural overlap."""
    passed = 1.0 if card["status"] != "rejected" else 0.0
    out = [passed, float(len(card["taste"]["criteria_met"])), float(backed),
           -float(card["gates"]["structural_jaccard_max"])]
    rating = (card.get("human_rating") or {}).get("rating")
    return [float(rating), *out] if rating else [0.0, *out]


def _fitness(card: dict[str, Any], ctx: Context) -> list[float]:
    return card_fitness(card, sum(1 for a in card.get("_atoms", []) if a.get("support") == "episode_backed"))


def _finish_generation(r: _Run, cands: list[Cand], archive: dict, ideas: dict[str, dict[str, Any]], gen: int,
                       art_records: list[dict[str, Any]], stopped: bool = False) -> None:
    res, ctx, dims = r.res, r.ctx, r.dims
    new_ideas, new_archive, demoted = [], [], []
    for c in cands:
        if not c.card:
            if c.rejected:
                res.rejected[c.rejected.split(":")[0]] += 1
            continue
        if stopped and not c.judged and not c.rejected:
            continue  # unfinished when the run stopped: generated again next time (cached)
        card = c.card
        res.candidates += 1
        if c.rejected:
            card["status"] = "rejected"
            if not c.judged:  # never reached the judge: record the gate result honestly
                card["gates"].update(structural_jaccard_max=c.gates.structural_max if c.gates else 0.0,
                                     procedural_jaccard_max=c.gates.procedural_max if c.gates else 0.0,
                                     premise_cosine_max=c.gates.cosine_max if c.gates else 0.0,
                                     novel_combo=bool(c.gates and c.gates.novel_combo),
                                     pmi_key_pair=c.gates.pmi_key_pair if c.gates else None,
                                     graveyard_hits=list(c.gates.graveyard_hits) if c.gates else [])
            res.rejected[c.rejected.split(":")[0]] += 1
        else:
            card["status"] = "candidate"
            key = cell_key(card["profile"], dims)
            card["grid_cell"] = key
            res.passed += 1
            if r.index:
                fit = _fitness(card, ctx)
                inc = archive.get(key)
                if inc is None or better(fit, inc["fitness"]):
                    if inc is not None and inc["idea_id"] in ideas:
                        old = dict(ideas[inc["idea_id"]])
                        old["status"] = "candidate"
                        demoted.append(old)
                    rec = {"cell_key": key, "idea_id": card["idea_id"], "fitness": fit,
                           "replaced_idea_id": inc["idea_id"] if inc else None, "generation": gen,
                           "provenance": card["provenance"]}
                    archive[key] = rec
                    new_archive.append(rec)
                    card["status"] = "champion"
                    res.placed += 1
        clean = {k: v for k, v in card.items() if not k.startswith("_")}
        IdeaCard.model_validate(clean)
        new_ideas.append(clean)
        ideas[clean["idea_id"]] = clean
    if not r.index:  # baseline 1: its own blind store, never canonical, never the archive
        if new_ideas:
            _merge_jsonl(baseline_file(r.paths, "ideas"), new_ideas, "idea_id")
        if art_records:
            for rec in art_records:
                PriorArtCheck.model_validate(rec)
            _merge_jsonl(baseline_file(r.paths, "prior_art"), art_records, "check_id")
        return
    for old in demoted:
        ideas[old["idea_id"]] = old
    if new_ideas or demoted:
        write_candidates(r.paths, "idea", f"{r.run_id}_g{gen}", [*new_ideas, *demoted])
    if new_archive:
        write_candidates(r.paths, "archive", f"{r.run_id}_g{gen}", new_archive)
    if art_records:
        write_candidates(r.paths, "prior_art", f"{r.run_id}_g{gen}", art_records)
    canonicalize(r.paths, f"{r.run_id}_g{gen}")


def diversity_alarm(archive: dict, dims: list[str], settings: Settings) -> str | None:
    """06: champions crowding a few values of one grid dimension (per-dimension reading of '40% of
    champions in 10% of cells', since MAP-Elites keeps one champion per cell)."""
    alarm = settings.ideate.get("diversity_alarm") or {}
    share, cell_share = float(alarm.get("champion_share", 0.40)), float(alarm.get("cell_share", 0.10))
    champions = list(archive.values())
    if len(champions) < 5:
        return None
    from animedex.ontology import get_vocab

    vocab = get_vocab()
    for d in dims:
        values = [v for v in vocab.enum(d) if v != "other"]
        top_n = max(1, round(len(values) * cell_share))
        counts = Counter(dict(part.split("=") for part in c["cell_key"].split("|"))[d.split(".")[-1]] for c in champions)
        top = sum(n for _, n in counts.most_common(top_n))
        if top / len(champions) > share:
            return f"{top} of {len(champions)} champions share {top_n} {d.split('.')[-1]} value(s): target empty cells"
    return None


__all__ = ["IdeateResult", "PROFILE_PATHS", "baseline_file", "card_fitness", "cell_key", "grid_cells",
           "ideation_budget", "run_ideate", "build_context"]
