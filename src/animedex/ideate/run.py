"""IDEATE (05, v1.6): MAP-Elites over the grid in `ideate.grid_dims`.

Per generation: plan candidates (seeded) -> generate one card per call -> deterministic gates
(clone, novelty, graveyard; one rework) -> judge in batches (different family: H1 consequence
test, failure conditions, coherence, runway, taste with evidence; one rework) -> deterministic
taste evidence -> prior-art web check for every T1/T4 claim -> fitness -> archive (<=1 idea per
cell; a cell's fitness never decreases) -> canonicalize before the next generation.

The run respects the per-run call cap: when it is reached the run stops cleanly and the next
`animedex ideate` continues from the archive. Never loosen a gate to fill cells.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import product
from typing import Any

from animedex.budget import BudgetExceeded
from animedex.config import Settings
from animedex.embeddings.base import Embedder
from animedex.ideate.context import PROFILE_PATHS, Context, build_context
from animedex.ideate.gates import GateResult, Similarity, run_gates
from animedex.ideate.llm import (
    card_from,
    generate_problems,
    generate_schema,
    generate_user,
    judge_card_text,
    judge_problems,
    judge_schema,
    prior_art_problems,
    prior_art_schema,
)
from animedex.models import IdeaCard
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.canonicalize import canonicalize
from animedex.pipeline.common import provenance, raise_problems, url_set, write_candidates
from animedex.prompts import read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.store.cache import upstream_hash
from animedex.store.canonical import CanonicalStore
from animedex.store.quarantine import quarantine
from animedex.textutil import sha256_text, stable_json

BORROWABLE = ("game", "exam_or_school", "job_or_bureaucracy", "market_or_economy", "sport", "social_rating",
              "law_or_contract", "card_or_collection", "crafting_or_cooking", "military_rank", "ritual_or_religion")


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


@dataclass
class IdeateResult:
    generations: list[int] = field(default_factory=list)
    candidates: int = 0
    placed: int = 0
    champions: int = 0
    rejected: Counter = field(default_factory=Counter)
    reworks: int = 0
    prior_art: Counter = field(default_factory=Counter)
    stopped: str | None = None
    diversity_alarm: str | None = None
    notes: list[str] = field(default_factory=list)


def cell_key(profile: dict[str, str], dims: list[str]) -> str:
    return "|".join(f"{d.split('.')[-1]}={profile.get(d.split('.')[-1])}" for d in dims)


def grid_cells(vocab: Vocab, dims: list[str]) -> list[dict[str, str]]:
    values = [[v for v in vocab.enum(d) if v != "other"] for d in dims]
    return [{d.split(".")[-1]: v for d, v in zip(dims, combo, strict=True)} for combo in product(*values)]


def better(a: list[float], b: list[float]) -> bool:
    return list(a) > list(b)


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
    """v1.6 5b: a borrowed system qualifies only with zero occurrences as a power system in the census."""
    if not ctx.census_size:
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
        theme = rng.choice(ctx.themes) if ctx.themes else "What does power cost the one who holds it?"
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


# ---------------------------------------------------------------- the run
def _call(res: IdeateResult, paths: Paths, ref: str, client: LLMClient, system: str, user: str,
          schema: dict[str, Any], *, upstream: str, validate: Callable[..., Any], params: dict[str, Any] | None = None,
          pass_: str = "IDEATE") -> Any:
    ctx = CallContext(pass_=pass_, record_id=ref, title_id=None, upstream=upstream)
    try:
        return client.complete_ex(system, user, schema, params, ctx=ctx, validate=validate)
    except InvalidOutput as exc:
        quarantine(paths.quarantine, pass_, "idea", ref, exc.raw, exc.errors)
        res.rejected["format"] += 1
    except (BudgetExceeded, RateLimited, CliAuthError) as exc:
        res.stopped = str(exc)
        raise _Stop from exc
    except ProviderError as exc:
        res.notes.append(f"{ref}: {exc}")
        res.rejected["provider"] += 1
    return None


def run_ideate(paths: Paths, settings: Settings, vocab: Vocab, *, clients: dict[str, LLMClient], embedder: Embedder,
               run_id: str, generations: int | None = None, created_at: str | None = None) -> IdeateResult:
    cfg, gates_cfg = settings.ideate, settings.gates
    dims = list(cfg.get("grid_dims"))
    h1_min = int(cfg.get("h1_min_changed_dimensions", 2))
    res = IdeateResult()
    store = CanonicalStore(paths)
    existing = store.state()
    archive = {a["cell_key"]: a for a in existing.get("archive", [])}
    ideas = {i["idea_id"]: i for i in existing.get("idea", [])}
    start_gen = max((i["generation"] for i in ideas.values()), default=-1) + 1
    ctx = build_context(paths, settings, vocab)
    if not ctx.pool:
        res.notes.append("no load-bearing-eligible transfer atoms yet: finish M3 (P2-P4) first")
        return res
    sim = Similarity(embedder, ctx)
    gen_prompt = read_prompt(paths.prompts / "ideate_generate.md")
    judge_prompt = read_prompt(paths.prompts / "ideate_judge.md")
    art_prompt = read_prompt(paths.prompts / "prior_art.md")
    clients["ideate_generate"].prompt_version = gen_prompt.version
    clients["ideate_judge"].prompt_version = judge_prompt.version
    if "prior_art" in clients:
        clients["prior_art"].prompt_version = art_prompt.version
    title_ids = sorted(ctx.titles)
    flop_ids = [g["title_id"] for g in ctx.graveyard]
    seed = int(cfg.get("seed", 7))
    n_gen = generations if generations is not None else int(cfg.get("generations", 3))
    counter = len([i for i in ideas.values() if i["provenance"]["run_id"] == run_id])
    for gen in range(start_gen, start_gen + n_gen):
        rng = random.Random(f"{seed}:{gen}")
        plans = plan_generation(ctx, settings, vocab, rng, gen, archive, ideas)
        if not plans:
            res.notes.append("no eligible operator or atom pool")
            break
        cands = []
        for plan in plans:
            counter += 1
            cands.append(Cand(plan, idea_id=f"idea.{run_id}.{counter:03d}"))
        try:
            _generate_all(res, paths, clients, ctx, cands, vocab, gen_prompt, title_ids, flop_ids, dims, gen, run_id,
                          created_at, rework_notes={})
            _gate_all(res, paths, clients, ctx, sim, cands, vocab, gen_prompt, title_ids, flop_ids, dims, gen, run_id,
                      created_at, gates_cfg)
            _judge_all(res, paths, clients, ctx, cands, judge_prompt, int(cfg.get("judge_batch", 4)), h1_min)
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
                _generate_all(res, paths, clients, ctx, redo, vocab, gen_prompt, title_ids, flop_ids, dims, gen,
                              run_id, created_at, rework_notes=notes)
                _gate_all(res, paths, clients, ctx, sim, redo, vocab, gen_prompt, title_ids, flop_ids, dims, gen,
                          run_id, created_at, gates_cfg, allow_rework=False)
                _judge_all(res, paths, clients, ctx, redo, judge_prompt, int(cfg.get("judge_batch", 4)), h1_min)
                for c in redo:
                    if c.card and not c.rejected and c.judged and _post_judge_rework(c):
                        c.rejected = f"judge: {', '.join(_post_judge_rework(c))} (after one rework)"
            _taste_evidence(ctx, cands)
            art_records = (_prior_art(res, paths, clients, ctx, cands, run_id, created_at, vocab)
                           if "prior_art" in clients else [])
        except _Stop:
            _finish_generation(paths, res, ctx, cands, archive, ideas, dims, gen, run_id, created_at, [], stopped=True)
            break
        _finish_generation(paths, res, ctx, cands, archive, ideas, dims, gen, run_id, created_at, art_records)
        res.generations.append(gen)
    res.champions = len(archive)
    res.diversity_alarm = diversity_alarm(archive, dims, settings)
    return res


def _generate_all(res: IdeateResult, paths: Paths, clients: dict[str, LLMClient], ctx: Context, cands: list[Cand],
                  vocab: Vocab, prompt: Any, title_ids: list[str], flop_ids: list[str], dims: list[str], gen: int,
                  run_id: str, created_at: str | None, *, rework_notes: dict[str, list[str]]) -> None:
    client = clients["ideate_generate"]
    for c in cands:
        p = c.plan
        notes = rework_notes.get(p.ref)
        schema = generate_schema(vocab, [a["transfer_id"] for a in p.atoms], title_ids, flop_ids)
        user = generate_user(ctx, theme=p.theme, operator=p.operator, target=p.target, atoms=p.atoms,
                             revival=p.revival, borrowed=p.borrowed, rework=notes)
        grid = cell_key(p.target, dims)
        prov0 = provenance("IDEATE", run_id, None, prompt.version, vocab, created_at)

        def check(out: dict[str, Any], _p: Plan = p, _grid: str = grid, _prov: dict = prov0) -> None:
            raise_problems(generate_problems(out, ctx, _p.atoms, _p.operator, _grid, _prov))

        done = _call(res, paths, f"{p.ref}.rework" if notes else p.ref, client, prompt.body, user, schema,
                     upstream=upstream_hash([{"plan": {"theme": p.theme, "operator": p.operator, "target": p.target,
                                                       "atoms": [a["transfer_id"] for a in p.atoms],
                                                       "revival": (p.revival or {}).get("title_id"),
                                                       "borrowed": p.borrowed, "rework": notes or []}}]),
                     validate=check)
        if done is None:
            c.card, c.rejected = None, "format: generation failed validation twice"
            continue
        prov = provenance("IDEATE", run_id, done, prompt.version, vocab, created_at)
        card = card_from(done.data, idea_id=c.idea_id, atoms=p.atoms, operator=p.operator, theme=p.theme,
                         grid_cell=cell_key(done.data["profile"], dims), generation=gen, prov=prov, revival=p.revival)
        card["parent_ids"] = list(p.parent_ids)
        card["_atoms"] = p.atoms
        c.card, c.rejected = card, None


def _gate_all(res: IdeateResult, paths: Paths, clients: dict[str, LLMClient], ctx: Context, sim: Similarity,
              cands: list[Cand], vocab: Vocab, prompt: Any, title_ids: list[str], flop_ids: list[str],
              dims: list[str], gen: int, run_id: str, created_at: str | None, gates_cfg: dict[str, Any],
              allow_rework: bool = True) -> None:
    for c in cands:
        if c.card is None or c.rejected:
            continue
        c.gates = run_gates(c.card, ctx, sim, gates_cfg)
        if c.gates.fatal:
            c.rejected = c.gates.fatal[0]
    redo = [c for c in cands if c.card and not c.rejected and c.gates and c.gates.failures]
    if not redo:
        return
    if not allow_rework:
        for c in redo:
            c.rejected = c.gates.failures[0] + " (after one rework)"
        return
    res.reworks += len(redo)
    notes = {c.plan.ref: list(c.gates.failures) for c in redo}
    for c in redo:
        c.reworked = True
    _generate_all(res, paths, clients, ctx, redo, vocab, prompt, title_ids, flop_ids, dims, gen, run_id, created_at,
                  rework_notes=notes)
    for c in redo:
        if c.card is None or c.rejected:
            continue
        c.gates = run_gates(c.card, ctx, sim, gates_cfg)
        if c.gates.fatal or c.gates.failures:
            c.rejected = (c.gates.fatal or c.gates.failures)[0] + " (after one rework)"


def _facts(ctx: Context, c: Cand) -> list[str]:
    g, card = c.gates, c.card
    facts = [f"untried combination: {g.novelty_basis}" if g.novel_combo else "no untried combination",
             f"coverage {'adequate' if ctx.adequate else 'thin (zeros untrusted)'}",
             f"graveyard matches: {', '.join(g.graveyard_hits) or 'none'}"]
    lanes = sorted(set(card["bridge"]) & (ctx.lanes["imported"] | ctx.lanes["export"]))
    facts.append(f"lane concepts used: {', '.join(lanes) or 'none'}")
    if card.get("revival_of"):
        facts.append(f"revives execution-level flop {card['revival_of']['title_id']}")
    return facts


def _judge_all(res: IdeateResult, paths: Paths, clients: dict[str, LLMClient], ctx: Context, cands: list[Cand],
               prompt: Any, batch: int, h1_min: int) -> None:
    live = [c for c in cands if c.card and not c.rejected]
    for i in range(0, len(live), batch):
        chunk = live[i:i + batch]
        refs = [c.plan.ref for c in chunk]
        conditions = sorted({f for c in chunk for a in c.plan.atoms for f in a["failure_conditions"]})
        user = "\n\n".join(judge_card_text(c.plan.ref, c.card, ctx, c.plan.atoms, _facts(ctx, c)) for c in chunk)
        done = _call(res, paths, "judge:" + "+".join(refs), clients["ideate_judge"], prompt.body, user,
                     judge_schema(refs, conditions),
                     upstream=sha256_text(stable_json([{k: v for k, v in c.card.items() if k not in ("provenance", "_atoms",
                                                                                                  "idea_id")}
                                                       for c in chunk])),
                     validate=lambda out, _r=refs: raise_problems(judge_problems(out, _r)))
        if done is None:
            for c in chunk:
                c.rejected = "judge: no valid verdict"
            continue
        by_ref = {j["ref"]: j for j in done.data["cards"]}
        for c in chunk:
            j = by_ref[c.plan.ref]
            c.judged = j
            dims = {d: bool(j[f"{d}_differs"]) for d in ("choices", "relationships", "outcomes")}
            h1 = sum(dims.values()) >= h1_min
            g = c.card["gates"]
            g.update(structural_jaccard_max=c.gates.structural_max, procedural_jaccard_max=c.gates.procedural_max,
                     premise_cosine_max=c.gates.cosine_max, novel_combo=c.gates.novel_combo,
                     graveyard_hits=list(c.gates.graveyard_hits),
                     failure_conditions_triggered=list(j["failure_conditions_triggered"]),
                     consequence_test={**dims, "h1_pass": h1}, coherence=j["coherence"])
            c.card["runway"] = {"hurts_by_arc5": bool(j["runway_hurts_by_arc5"]), "reason": j["runway_reason"]}
            c.card["taste"] = {"criteria_met": [], "evidence": {}, "hard_fail": not h1}
            if not h1:
                c.rejected = f"H1: surface change (fewer than {h1_min} consequence dimensions differ)"
            elif j["coherence"] == "fail":
                c.rejected = f"coherence: {j['coherence_reason']}"


def _post_judge_rework(c: Cand) -> list[str]:
    j, out = c.judged or {}, []
    if j.get("failure_conditions_triggered"):
        out.append("triggers failure conditions: " + "; ".join(j["failure_conditions_triggered"]))
    if j and not j.get("runway_hurts_by_arc5", True):
        out.append(f"runway: the cost stops hurting by arc 5 ({j.get('runway_reason')})")
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
            if crit == "T1" and not (g.novel_combo and ctx.adequate and not g.graveyard_hits):
                continue
            if crit == "T3" and not ((len(set(card["bridge"])) >= 2 or len(media) >= 2) and card["gates"]["coherence"] == "pass"):
                continue
            if crit == "T4" and not (set(card["bridge"]) & (ctx.lanes["imported"] | ctx.lanes["export"])
                                     or (g.novel_combo and ctx.adequate)):
                continue
            if crit == "T5" and not card.get("revival_of"):
                continue
            kept.setdefault(crit, ev)
        card["taste"] = {"criteria_met": sorted(kept), "evidence": kept, "hard_fail": False}


def _prior_art(res: IdeateResult, paths: Paths, clients: dict[str, LLMClient], ctx: Context, cands: list[Cand],
               run_id: str, created_at: str | None, vocab: Vocab) -> list[dict[str, Any]]:
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
    client = clients["prior_art"]
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

        done = _call(res, paths, "prior_art:" + "+".join(refs), client, read_prompt(paths.prompts / "prior_art.md").body,
                     user, prior_art_schema(refs), upstream=sha256_text(stable_json(texts)), validate=check,
                     params={"web": limits}, pass_="IDEATE")
        verdicts = {v["ref"]: v for v in (done.data["checks"] if done else [])}
        web = (done.meta.get("web") or {}) if done else {}
        for (c, crit), ref in zip(chunk, refs, strict=True):
            v = verdicts.get(ref) or {"verdict": "inconclusive", "counterexamples": []}
            res.prior_art[v["verdict"]] += 1
            taste = c.card["taste"]
            if v["verdict"] == "clear":
                taste["evidence"][crit] = (taste["evidence"][crit] + "; prior-art clear")[:300]
            else:
                taste["criteria_met"] = [x for x in taste["criteria_met"] if x != crit]
                taste["evidence"].pop(crit, None)
            prov = provenance("IDEATE", run_id, done, read_prompt(paths.prompts / "prior_art.md").version, vocab,
                              created_at)
            records.append({"check_id": f"pa.{c.idea_id}.{crit}", "claim_kind": crit, "subject_id": c.idea_id,
                            "claim": texts[refs.index(ref)][:600], "queries": list(web.get("queries") or [])[:8],
                            "verdict": v["verdict"], "counterexamples": v.get("counterexamples") or [],
                            "provenance": prov})
    return records


def _fitness(card: dict[str, Any], ctx: Context) -> list[float]:
    passed = 1.0 if card["status"] != "rejected" else 0.0
    backed = sum(1 for a in card.get("_atoms", []) if a.get("support") == "episode_backed")
    out = [passed, float(len(card["taste"]["criteria_met"])), float(backed),
           -float(card["gates"]["structural_jaccard_max"])]
    rating = (card.get("human_rating") or {}).get("rating")
    return [float(rating), *out] if rating else [0.0, *out]


def _finish_generation(paths: Paths, res: IdeateResult, ctx: Context, cands: list[Cand], archive: dict,
                       ideas: dict[str, dict[str, Any]], dims: list[str], gen: int, run_id: str,
                       created_at: str | None, art_records: list[dict[str, Any]], stopped: bool = False) -> None:
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
                                     graveyard_hits=list(c.gates.graveyard_hits) if c.gates else [])
            res.rejected[c.rejected.split(":")[0]] += 1
        else:
            card["status"] = "candidate"
            key = cell_key(card["profile"], dims)
            card["grid_cell"] = key
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
    for old in demoted:
        ideas[old["idea_id"]] = old
    if new_ideas or demoted:
        write_candidates(paths, "idea", f"{run_id}_g{gen}", [*new_ideas, *demoted])
    if new_archive:
        write_candidates(paths, "archive", f"{run_id}_g{gen}", new_archive)
    if art_records:
        write_candidates(paths, "prior_art", f"{run_id}_g{gen}", art_records)
    canonicalize(paths, f"{run_id}_g{gen}")


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


__all__ = ["IdeateResult", "PROFILE_PATHS", "cell_key", "grid_cells", "run_ideate", "build_context"]
