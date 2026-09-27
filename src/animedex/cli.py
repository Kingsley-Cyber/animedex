"""`animedex` CLI (05). Stages not yet built exit 2 and name the milestone that builds them."""

from __future__ import annotations

import json
from typing import Any

import typer

from animedex import SCHEMA_VERSION
from animedex.config import environment, live_problems, load_settings
from animedex.pipeline import StageNotImplemented

app = typer.Typer(no_args_is_help=True, add_completion=False, help="ANIMEDEX pipeline and tooling.")
gold_app = typer.Typer(no_args_is_help=True, help="Gold-set annotation files (G1c/G2).")
app.add_typer(gold_app, name="gold")


def _paths():
    from animedex.paths import Paths

    return Paths.discover()


def _stub(stage: str) -> None:
    typer.echo(str(StageNotImplemented(stage)), err=True)
    raise typer.Exit(2)


TitleOpt = typer.Option(None, "--title", help="Title id (slug + year).")
AllOpt = typer.Option(False, "--all", help="Every title in the corpus.")
DryOpt = typer.Option(False, "--dry-run", help="Print prompts and cache status; no model calls.")


def _entries(paths: Any, title: str | None, all_: bool) -> list:
    from animedex.guards import load_corpus

    corpus = load_corpus(paths)
    if all_:
        entries = [corpus[k] for k in sorted(corpus)]
    elif title:
        if title not in corpus:
            typer.echo(f"{title} is not in corpus/titles.yaml", err=True)
            raise typer.Exit(1)
        entries = [corpus[title]]
    else:
        typer.echo("pass --title <id> or --all", err=True)
        raise typer.Exit(1)
    if not entries:
        typer.echo("corpus/titles.yaml has no titles yet", err=True)
        raise typer.Exit(1)
    return entries


@app.command()
def p1(title: str = TitleOpt, all_: bool = AllOpt, dry_run: bool = DryOpt,
       agreement: bool = typer.Option(False, "--agreement", help="Second run for AC-12 -> eval/agreement/p1/<run>/")) -> None:
    """P1 WHAT: title profile + moments -> candidates (then `animedex canonicalize`)."""
    from animedex import SCHEMA_VERSION as schema_version
    from animedex.ontology import get_vocab
    from animedex.pipeline.p1 import render_prompt, render_user, run_p1
    from animedex.providers.factory import build_client
    from animedex.store.cache import ResponseCache, cache_key, upstream_hash
    from animedex.store.runlog import RunLog, new_run_id

    paths = _paths()
    settings, vocab = load_settings(paths), get_vocab(paths)
    entries = _entries(paths, title, all_)
    prompt = render_prompt(paths, vocab, settings)
    if dry_run:
        from animedex.providers.factory import build_provider

        spec = settings.models["p1"]
        cache = ResponseCache(paths.cache)
        from animedex.providers.base import ProviderError

        try:  # the cache key carries the CLI identity (name + version)
            identity = getattr(build_provider(spec.provider, settings, environment(paths)), "identity", spec.provider)
        except ProviderError as exc:
            identity = spec.provider
            typer.echo(f"note: {exc}; cache status below may be wrong", err=True)
        typer.echo(f"P1 prompt {prompt.version} ({len(prompt.system)} chars); model {identity}/{spec.model}")
        for e in entries:
            key = cache_key(record_id=e.title_id, pass_="P1", prompt_version=prompt.version,
                            schema_version=schema_version, vocab_version=vocab.version,
                            model=f"{identity}/{spec.model}", params=spec.params,
                            upstream=upstream_hash([e.model_dump(mode="json")]))
            status = "cached" if cache.get("P1", key) else "would call"
            typer.echo(f"--- {e.title_id} [{status}]\n{render_user(e)}")
        return
    run_id = new_run_id()
    runlog = RunLog(paths.raw_runs, run_id)
    client = build_client("p1", paths=paths, settings=settings, env=environment(paths), runlog=runlog,
                          prompt_version=prompt.version)
    agreement_dir = paths.root / "eval" / "agreement" / "p1" / run_id if agreement else None
    result = run_p1(paths, entries, client, vocab, settings, run_id=run_id, agreement_dir=agreement_dir,
                    params={"rerun": 2} if agreement else None)
    runlog.write_ledger()
    if agreement_dir is not None:
        typer.echo(f"agreement run written to {agreement_dir.relative_to(paths.root)}; next: make eval")
    typer.echo(f"P1 {run_id}: {len(result.titles)} profile(s), {len(result.moments)} moment(s) -> data/candidates/")
    for tid, why in result.quarantined + result.failed:
        typer.echo(f"  not written {tid}: {why[:200]}", err=True)
    for tid, why in result.refused:
        typer.echo(f"  refused {tid}: {why[:200]}", err=True)
    for tid, served in result.substituted:
        typer.echo(f"  fallback served {tid}: {served} (recorded in provenance; not cached)", err=True)
    if result.stopped:
        typer.echo(f"  stopped: {result.stopped}", err=True)
    if result.titles:
        typer.echo("next: animedex canonicalize")


@app.command()
def verify(title: str = TitleOpt, all_: bool = AllOpt, dry_run: bool = DryOpt,
           outcome_only: bool = typer.Option(False, "--outcome-only",
                                             help="v1.3: re-check only canonical mixed/flop outcomes for failure_level")
           ) -> None:
    """VERIFY: web-check flagged fields, moment locators, and the outcome (capped searches)."""
    from animedex.ontology import get_vocab
    from animedex.pipeline.verify import load_pending, run_verify
    from animedex.providers.factory import build_client
    from animedex.search.web import build_search
    from animedex.store.runlog import RunLog, new_run_id

    paths = _paths()
    settings, vocab = load_settings(paths), get_vocab(paths)
    entries = _entries(paths, title, all_)
    if dry_run:
        for e in entries:
            pending = load_pending(paths, e.title_id)
            if pending is None:
                typer.echo(f"{e.title_id}: no P1 candidate yet")
                continue
            typer.echo(f"{e.title_id}: {len(pending.verify)} item(s) to verify: {', '.join(pending.verify)}")
        return
    env = environment(paths)
    run_id = new_run_id()
    runlog = RunLog(paths.raw_runs, run_id)
    client = build_client("verify", paths=paths, settings=settings, env=env, runlog=runlog, prompt_version="unset")
    if outcome_only:
        from animedex.store.jsonl import read_jsonl

        non_hits = {o["title_id"] for o in read_jsonl(paths.canonical / "outcomes.jsonl") if o.get("label") != "hit"}
        entries = [e for e in entries if e.title_id in non_hits]
        typer.echo(f"outcome-only re-verify: {len(entries)} mixed/flop title(s)")
    result = run_verify(paths, entries, client, build_search(settings, env), vocab, settings, run_id=run_id,
                        outcome_only=outcome_only)
    runlog.write_ledger()
    for r in result.titles:
        counts: dict[str, int] = {}
        for status in r.statuses.values():
            counts[status] = counts.get(status, 0) + 1
        typer.echo(f"{r.title_id}: {counts}; outcome {'recorded' if r.outcome else 'unresolved'}; "
                   f"{len(r.conflicts)} correction(s); dropped moments {r.dropped_moments or 'none'}")
    for tid, why in result.skipped + result.quarantined:
        typer.echo(f"  not verified {tid}: {why[:200]}", err=True)
    if result.stopped:
        typer.echo(f"  stopped: {result.stopped}", err=True)


def _masked(paths: Any) -> set[str]:
    """Gold titles whose outputs stay counts-only (owner ruling 2026-09-27)."""
    from animedex.gold import masked_titles
    from animedex.guards import load_corpus

    return masked_titles(paths, {t for t, e in load_corpus(paths).items() if "gold" in e.role_tags})


def _say_issues(paths: Any, result: Any) -> None:
    hidden = _masked(paths)
    for label in ("quarantined", "failed", "refused", "skipped", "flags"):
        for tid, why in getattr(result, label, []):
            detail = "(details hidden: gold title, blind pending)" if tid in hidden else why[:200]
            typer.echo(f"  {label} {tid}: {detail}", err=True)
    if getattr(result, "stopped", None):
        typer.echo(f"  stopped: {result.stopped}", err=True)


def _analysis_stage(name: str, model_key: str, title: str | None, all_: bool) -> None:
    from animedex.ontology import get_vocab
    from animedex.pipeline.check import run_check
    from animedex.pipeline.p2 import run_p2
    from animedex.pipeline.p3 import run_p3
    from animedex.pipeline.p4 import run_p4
    from animedex.providers.factory import build_client
    from animedex.store.runlog import RunLog, new_run_id

    fn = {"P2": run_p2, "P3": run_p3, "CHECK": run_check, "P4": run_p4}[name]
    paths = _paths()
    settings, vocab = load_settings(paths), get_vocab(paths)
    ids = [e.title_id for e in _entries(paths, title, all_)]
    run_id = new_run_id()
    runlog = RunLog(paths.raw_runs, run_id)
    client = build_client(model_key, paths=paths, settings=settings, env=environment(paths), runlog=runlog,
                          prompt_version="unset")
    result = fn(paths, ids, client, vocab, settings, run_id=run_id)
    runlog.write_ledger()
    counts = ", ".join(f"{k} {v}" for k, v in sorted(result.counts.items())) or "no output"
    typer.echo(f"{name} {run_id}: {len(result.done)} title(s) done; {counts}")
    _say_issues(paths, result)
    if name == "CHECK" and result.done:
        typer.echo("next: animedex canonicalize (atoms and proofs land with their checks)")
    if name == "P4" and result.done:
        typer.echo("next: animedex canonicalize")


@app.command()
def p2(title: str = TitleOpt, all_: bool = AllOpt) -> None:
    """P2 WHY: effect + engine atoms from canonical, verified profiles."""
    _analysis_stage("P2", "p2", title, all_)


@app.command()
def p3(title: str = TitleOpt, all_: bool = AllOpt) -> None:
    """P3 PROOF: partner contrast, explanation test, ablation (one call per title)."""
    _analysis_stage("P3", "p3", title, all_)


@app.command()
def check(title: str = TitleOpt, all_: bool = AllOpt) -> None:
    """CHECK: a falsifying critic from a different model family; REVISE is re-checked once."""
    _analysis_stage("CHECK", "check", title, all_)


@app.command()
def p4(title: str = TitleOpt, all_: bool = AllOpt) -> None:
    """P4 TRANSFER: domain-neutral patterns with essential, variable, failure conditions."""
    _analysis_stage("P4", "p4", title, all_)


@app.command()
def run(title: str = TitleOpt, all_: bool = AllOpt) -> None:
    """Full pipeline for the given titles, skipping finished work: P1 -> VERIFY -> P2 -> P3 -> CHECK -> P4."""
    from animedex.ontology import get_vocab
    from animedex.pipeline.orchestrate import run_batch

    paths = _paths()
    settings, vocab = load_settings(paths), get_vocab(paths)
    ids = [e.title_id for e in _entries(paths, title, all_)]
    report = run_batch(paths, ids, settings, environment(paths), vocab, echo=typer.echo)
    for line in report.lines():
        typer.echo(line)
    if report.stopped:
        typer.echo("Paused. Rerun the same command later; finished calls are cached.", err=True)
        raise typer.Exit(3)


@app.command()
def ep(title: str = TitleOpt, episodes: str = typer.Option("key", "--episodes"), dry_run: bool = DryOpt) -> None:
    """EP: key-episode evidence (M6)."""
    _stub("ep")


@app.command()
def rollup(title: str = TitleOpt, dry_run: bool = DryOpt) -> None:
    """ROLLUP: compound episode evidence (M6)."""
    _stub("rollup")


@app.command()
def analyze() -> None:
    """ANALYZE: coverage, gap cells with adequacy flags, lanes, graveyard, CQ answers -> build/."""
    from animedex.analyze import run_analyze

    paths = _paths()
    r = run_analyze(paths, load_settings(paths))
    typer.echo(f"analyzed: {r.answered} CQ answers -> build/cq_answers/; {r.empty_cells} empty gate x cost cells "
               f"(zeros are {r.zeros_are}); graveyard {r.graveyard} title(s); lanes imported {r.lanes['imported']}, "
               f"export {r.lanes['export']}; summary -> build/reports/analysis.md")


@app.command()
def patterns() -> None:
    """Pattern cards (M7)."""
    _stub("patterns")


def _ideate_clients(paths: Any, settings: Any, keys: tuple[str, ...]) -> tuple[dict, Any]:
    from animedex.budget import Budget
    from animedex.providers.factory import build_client
    from animedex.store.runlog import RunLog, new_run_id

    runlog = RunLog(paths.raw_runs, new_run_id())
    budget = Budget.from_settings(settings)  # one cap for the whole run, across every model it uses
    env = environment(paths)
    clients = {k: build_client(k, paths=paths, settings=settings, env=env, runlog=runlog, prompt_version="unset",
                               budget=budget) for k in keys}
    return clients, runlog


@app.command()
def ideate(generations: int = typer.Option(None, "--generations", help="Default: ideate.generations")) -> None:
    """IDEATE: MAP-Elites idea cards -> data/canonical/ideas.jsonl and build/reports/ideas.md."""
    from animedex.embeddings.base import build_embedder
    from animedex.ideate.report import write_report
    from animedex.ideate.run import run_ideate
    from animedex.ontology import get_vocab
    from animedex.store.runlog import new_run_id

    paths = _paths()
    settings, vocab = load_settings(paths), get_vocab(paths)
    clients, runlog = _ideate_clients(paths, settings, ("ideate_generate", "ideate_judge", "prior_art"))
    result = run_ideate(paths, settings, vocab, clients=clients, embedder=build_embedder(settings, environment(paths)),
                        run_id=new_run_id(), generations=generations)
    runlog.write_ledger()
    write_report(paths)
    rejected = ", ".join(f"{k} {v}" for k, v in sorted(result.rejected.items())) or "none"
    typer.echo(f"ideate: generations {result.generations or 'none'}; {result.candidates} cards, {result.placed} placed; "
               f"{result.champions} champions in the archive; reworks {result.reworks}; rejected: {rejected}; "
               f"prior-art {dict(result.prior_art) or 'none'}")
    for note in result.notes:
        typer.echo(f"  note: {note}", err=True)
    if result.diversity_alarm:
        typer.echo(f"  diversity alarm: {result.diversity_alarm}", err=True)
    typer.echo("cards -> build/reports/ideas.md")
    if result.stopped:
        typer.echo(f"Paused: {result.stopped}. Run `make ideas` again later; it continues from the archive.", err=True)
        raise typer.Exit(3)


@app.command()
def packet() -> None:
    """Blind review packet: champions + plain baseline + web baseline, shuffled, logline and premise only."""
    from animedex.ideate.packet import build_packet
    from animedex.ontology import get_vocab

    paths = _paths()
    settings, vocab = load_settings(paths), get_vocab(paths)
    clients, runlog = _ideate_clients(paths, settings, ("ideate_generate",))
    web, _ = _ideate_clients(paths, settings, ("ideate_generate",))
    result = build_packet(paths, settings, vocab, plain=clients["ideate_generate"], web=web["ideate_generate"])
    runlog.write_ledger()
    typer.echo(f"blind packet: {result.per_arm} cards per arm x 3 -> {result.packet}; ratings -> {result.ratings}; "
               f"answer key kept out of view in {result.key}")


@app.command()
def migrate(to: str = typer.Option(..., "--to", help="Spec version to migrate canonical data to, e.g. 1.3.0")) -> None:
    """Mechanical data migration between spec versions (no hand edits, no re-extraction)."""
    from animedex.migrations import MIGRATIONS
    from animedex.store.runlog import new_run_id

    if to not in MIGRATIONS:
        typer.echo(f"no migration to {to}; known: {sorted(MIGRATIONS)}", err=True)
        raise typer.Exit(2)
    changed = MIGRATIONS[to](_paths(), new_run_id())
    typer.echo(f"migrated to {to}: {len(changed)} record(s) updated")


@app.command()
def backfill(list_file: str = typer.Option(..., "--list", help="One title per line; a version in parentheses is used as given."),
             batch: int = typer.Option(8, "--batch", help="Titles deep-indexed per run (paced for the plan limits)."),
             census_only: bool = typer.Option(False, "--census-only", help="Only add the titles to the census."),
             no_run: bool = typer.Option(False, "--no-run", help="Resolve and add to the corpus; run nothing.")) -> None:
    """Resolve a plain title list to scoped corpus entries, then run the full pipeline (counts only)."""
    from pathlib import Path as _P

    from animedex.catalog.anilist import AniList
    from animedex.catalog.backfill import (
        add_to_corpus,
        census_items,
        list_title_ids,
        pending_titles,
        plan_backfill,
        read_list,
        report,
    )
    from animedex.catalog.resolve import TvMaze
    from animedex.guards import load_corpus
    from animedex.ontology import get_vocab
    from animedex.pipeline.orchestrate import run_batch
    from animedex.store.atomic import atomic_write_text

    paths = _paths()
    settings, vocab = load_settings(paths), get_vocab(paths)
    src = _P(list_file)
    lines = read_list(src)
    typer.echo(f"backfill: {len(lines)} line(s) from {src.name}; resolving with the catalog...")
    plan = plan_backfill(AniList(), lines, load_corpus(paths), tvmaze=TvMaze())
    batch_lines: list[str] = []
    if census_only:
        from animedex.pipeline.census import run_census
        from animedex.providers.factory import build_client
        from animedex.store.runlog import RunLog, new_run_id

        run_id = new_run_id()
        runlog = RunLog(paths.raw_runs, run_id)
        client = build_client("census", paths=paths, settings=settings, env=environment(paths), runlog=runlog,
                              prompt_version="unset")
        result = run_census(paths, census_items(plan), client, vocab, settings, run_id=run_id)
        runlog.write_ledger()
        from animedex.pipeline.canonicalize import canonicalize as _canon

        _canon(paths, new_run_id())
        batch_lines = [f"census: {', '.join(f'{k} {v}' for k, v in sorted(result.counts.items())) or 'nothing new'}"]
        if result.stopped:
            batch_lines.append(f"STOPPED: {result.stopped}")
        waiting = 0
    else:
        added = add_to_corpus(paths, plan, src.name)
        typer.echo(f"  added {len(added)} title(s) to corpus/titles.yaml; skipped {len(plan.skipped)}; "
                   f"not found {len(plan.unresolved)}")
        todo = pending_titles(paths, list_title_ids(plan, lines))
        if not no_run and todo:
            now = todo[:batch]
            typer.echo(f"  running the full pipeline on {len(now)} title(s) (of {len(todo)} waiting)")
            rep = run_batch(paths, now, settings, environment(paths), vocab, echo=typer.echo)
            batch_lines = rep.lines()
            if rep.stopped:
                batch_lines.append("Paused cleanly: finished calls are cached; run the same command later.")
        waiting = len(pending_titles(paths, list_title_ids(plan, lines)))
    text = report(plan, src.name, batch_lines, waiting, list_file)
    atomic_write_text(paths.reports / "backfill.md", text)
    for w in plan.warnings:
        typer.echo(f"  note: {w}", err=True)
    for line in batch_lines:
        typer.echo(f"  {line}")
    typer.echo(f"report -> build/reports/backfill.md ({waiting} title(s) still waiting)")


@app.command()
def census(top: int = typer.Option(0, "--top", help="Count the N most popular franchise roots (anime + donghua)."),
           list_file: str = typer.Option(None, "--list", help="Count the titles in this list.")) -> None:
    """v1.6 census: which power-system combinations already exist (counts only, never ideation input)."""
    from pathlib import Path as _P

    from animedex.catalog.anilist import AniList
    from animedex.catalog.backfill import census_items, plan_backfill, read_list
    from animedex.ontology import get_vocab
    from animedex.pipeline.canonicalize import canonicalize as _canon
    from animedex.pipeline.census import run_census, top_roots
    from animedex.providers.factory import build_client
    from animedex.store.runlog import RunLog, new_run_id

    paths = _paths()
    settings, vocab = load_settings(paths), get_vocab(paths)
    cfg = (settings.model_extra or {}).get("census", {})
    cat = AniList()
    items = []
    if top:
        items += top_roots(cat, size=top, donghua=int(cfg.get("donghua", max(1, top // 10))),
                           since=int(cfg.get("since", 1995)))
    if list_file:
        plan = plan_backfill(cat, read_list(_P(list_file)), {}, suggest=False)  # census counts every listed title
        items += census_items(plan)
    run_id = new_run_id()
    runlog = RunLog(paths.raw_runs, run_id)
    client = build_client("census", paths=paths, settings=settings, env=environment(paths), runlog=runlog,
                          prompt_version="unset")
    result = run_census(paths, items, client, vocab, settings, run_id=run_id)
    runlog.write_ledger()
    _canon(paths, new_run_id())
    typer.echo(f"census: {len(items)} catalog title(s); " + (", ".join(f"{k} {v}" for k, v in
               sorted(result.counts.items())) or "nothing new"))
    if result.stopped:
        typer.echo(f"Paused: {result.stopped}. Run the same command later; counted titles are kept.", err=True)
        raise typer.Exit(3)


@app.command()
def canonicalize() -> None:
    """CANONICALIZE: data/candidates -> data/canonical (validate, normalize, quarantine, atomic write)."""
    from animedex.pipeline.canonicalize import canonicalize as run_canonicalize
    from animedex.store.runlog import new_run_id

    result = run_canonicalize(_paths(), new_run_id())
    for record_type, ids in sorted(result.written.items()):
        typer.echo(f"wrote {len(ids)} {record_type} record(s)")
    for record_type, rid, reason in result.quarantined:
        typer.echo(f"quarantined {record_type} {rid}: {reason[:160]}", err=True)
    if result.proposals:
        typer.echo(f"{len(result.proposals)} ontology proposal(s) written to ontology/proposals/")
    if not result.written and not result.quarantined:
        typer.echo("no candidates to canonicalize")


@app.command()
def validate() -> None:
    """Ontology coverage, schemas, config, corpus, canonical invariants (make validate)."""
    from animedex.validate import validate_repo

    report = validate_repo(_paths())
    for line in report.notes:
        typer.echo(f"note: {line}")
    for line in report.warnings:
        typer.echo(f"warning: {line}")
    for line in report.errors:
        typer.echo(f"ERROR: {line}", err=True)
    typer.echo("validate: OK" if report.ok else f"validate: {len(report.errors)} error(s)")
    raise typer.Exit(0 if report.ok else 1)


@app.command()
def build(verify_determinism: bool = typer.Option(False, "--verify-determinism")) -> None:
    """DuckDB build + exports + hashes (make build / make clean-build)."""
    from animedex.analyze import run_analyze, verify_cq_determinism
    from animedex.build.duckdb_build import build as run_build
    from animedex.build.duckdb_build import verify_determinism as run_verify

    paths = _paths()
    if verify_determinism:
        ok, diffs = run_verify(paths)
        cq_ok, cq_diffs = verify_cq_determinism(paths, load_settings(paths))
        for name, (a, b) in {**diffs, **cq_diffs}.items():
            typer.echo(f"MISMATCH {name}: {a} != {b}", err=True)
        typer.echo("clean rebuild: identical hashes and CQ answers" if ok and cq_ok else "clean rebuild: HASH MISMATCH")
        raise typer.Exit(0 if ok and cq_ok else 1)
    hashes = run_build(paths)
    r = run_analyze(paths, load_settings(paths))  # make build = BUILD + ANALYZE's deterministic CQ step (M4)
    typer.echo(f"built {len(hashes)} tables/views -> {paths.build_db.relative_to(paths.root)}; "
               f"{r.answered} CQ answers -> build/cq_answers/")


@app.command()
def schemas() -> None:
    """Regenerate schemas/*.schema.json from the pydantic models."""
    from animedex.schemas import write_schemas

    written = write_schemas(_paths())
    typer.echo(f"wrote {len(written)} schema file(s) (schema_version {SCHEMA_VERSION})")


@app.command(name="eval")
def eval_() -> None:
    """Gold-set readiness now; agreement and recall metrics arrive with M2/M3."""
    from animedex.gold import gold_status
    from animedex.guards import load_corpus
    from animedex.ontology import get_vocab

    paths = _paths()
    settings = load_settings(paths)
    vocab = get_vocab(paths)
    key_fields = list(settings.eval.get("gold_key_fields", []))
    gold = [e for e in load_corpus(paths).values() if "gold" in e.role_tags]
    ids = sorted({e.title_id for e in gold} | {p.name for p in paths.gold.glob("*_*") if p.is_dir()})
    if not ids:
        typer.echo("no gold titles in corpus/titles.yaml yet (G1b)")
    for title_id in ids:
        st = gold_status(paths, title_id, key_fields, vocab)
        state = "READY" if st.ready else "blocked"
        typer.echo(f"{title_id}: {state}" + ("" if st.ready else " - " + "; ".join(st.problems)))
    _eval_agreement(paths, settings, vocab, {e.title_id for e in gold})
    _eval_verify_rates(paths, vocab)


def _eval_agreement(paths: Any, settings: Any, vocab: Any, gold_ids: set[str]) -> None:
    import json

    from animedex.evaluation import p1_agreement
    from animedex.store.atomic import atomic_write_text
    from animedex.store.jsonl import read_jsonl

    runs = sorted((paths.root / "eval" / "agreement" / "p1").glob("*/titles.jsonl"))
    canonical = [t for t in read_jsonl(paths.canonical / "titles.jsonl") if t["title_id"] in gold_ids]
    if not runs or not canonical:
        typer.echo("P1 agreement (AC-12): needs canonical gold profiles and one `animedex p1 --agreement` run")
        return
    second = [t for t in read_jsonl(runs[-1]) if t["title_id"] in gold_ids]
    report = p1_agreement(canonical, second, vocab)
    bar = float(settings.eval.get("bars", {}).get("p1_enum_agreement", 0.80))
    report.update({"bar": bar, "second_run": runs[-1].parent.name,
                   "pass": report["overall"] is not None and report["overall"] >= bar})
    atomic_write_text(paths.root / "eval" / "agreement" / "p1_agreement.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
    typer.echo(f"P1 enum agreement (AC-12): {report['overall']} over {report['comparisons']} comparisons "
               f"({'PASS' if report['pass'] else 'BELOW BAR'} vs {bar})")


def _eval_verify_rates(paths: Any, vocab: Any) -> None:
    from animedex.evaluation import verify_rates, verify_rates_markdown
    from animedex.store.atomic import atomic_write_text
    from animedex.store.jsonl import read_jsonl

    titles = read_jsonl(paths.canonical / "titles.jsonl")
    if not titles:
        typer.echo("web correction rate (AC-13): no canonical titles yet")
        return
    rows = verify_rates(titles, vocab)
    atomic_write_text(paths.reports / "verify_rates.md", verify_rates_markdown(rows))
    top = sorted((r for r in rows if r.correction_rate is not None), key=lambda r: -(r.correction_rate or 0))[:5]
    typer.echo("web correction rate (AC-13) -> build/reports/verify_rates.md; top: "
               + (", ".join(f"{r.path} {r.correction_rate:.2f}" for r in top) or "no verified fields yet"))


@app.command()
def smoke(title: str = typer.Option(None, "--title"),
          stage: str = typer.Option("m2", "--stage", help="Milestone whose model slots must be live: m2|m3|m5|m6"),
          providers: bool = typer.Option(False, "--providers",
                                         help="One tiny call per subscription CLI provider, then stop (G1a)."),
          only: str = typer.Option(None, "--only", help="With --providers: just this provider profile.")) -> None:
    """Live readiness for a milestone: what blocks it; model ids resolve; one tiny call per model."""
    from animedex.config import STAGE_SLOTS

    if stage not in STAGE_SLOTS:
        typer.echo(f"unknown stage {stage!r}; use one of {sorted(STAGE_SLOTS)}", err=True)
        raise typer.Exit(2)
    slots = STAGE_SLOTS[stage]
    paths = _paths()
    settings = load_settings(paths)
    env = environment(paths)
    if providers:
        if not _ping_cli_providers(paths, settings, env, only):
            raise typer.Exit(1)
        return
    problems = live_problems(settings, env, slots)
    if title:
        from animedex.guards import LiveRunRefused, check_live_title
        from animedex.ontology import get_vocab

        try:
            check_live_title(paths, settings, get_vocab(paths), title)
            typer.echo(f"{title}: live runs allowed (scope declared; blind guard clear)")
        except LiveRunRefused as exc:
            problems.append(str(exc))
    if problems:
        typer.echo(f"Live runs for {stage} are blocked until these are filled (G1a):")
        for p in problems:
            typer.echo(f"  - {p}")
        raise typer.Exit(1)
    if not _resolve_models(settings, env, slots):
        raise typer.Exit(1)
    _ping_models(paths, settings, env, slots)


def _resolve_models(settings: Any, env: dict[str, str], slots: list[str]) -> bool:
    """G1a: every configured model id must resolve at its provider before the first live run."""
    from animedex.providers.base import ProviderError
    from animedex.providers.factory import build_provider

    ok = True
    for key in slots:
        spec = settings.models[key]
        if key == "embeddings":
            continue
        try:
            name = build_provider(spec.provider, settings, env).resolve_model(spec.model)
            typer.echo(f"model ok: {key} -> {spec.provider}/{spec.model} ({name})")
        except ProviderError as exc:
            typer.echo(f"MODEL CHECK FAILED: {key}: {exc}", err=True)
            ok = False
    return ok


def _ping_models(paths: Any, settings: Any, env: dict[str, str], slots: list[str]) -> None:
    from animedex.budget import Budget
    from animedex.providers.base import ProviderError
    from animedex.providers.client import CallContext
    from animedex.providers.factory import build_client, build_provider
    from animedex.store.runlog import RunLog, new_run_id

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
              "additionalProperties": False}
    runlog = RunLog(paths.raw_runs, new_run_id())
    budget = Budget.from_settings(settings)
    seen: set[tuple[str, str]] = set()
    for key in slots:
        spec = settings.models[key]
        if key == "embeddings" or (spec.provider, spec.model) in seen:
            continue
        seen.add((spec.provider, spec.model))
        try:
            provider = build_provider(spec.provider, settings, env)
            login = getattr(provider, "login_status", lambda: {"logged_in": True, "api_key": False})()
            if not login["logged_in"] or login["api_key"]:
                typer.echo(f"{spec.provider}/{spec.model}: SKIPPED, no plan login (method {login.get('method')})",
                           err=True)
                continue
            client = build_client(key, paths=paths, settings=settings, env=env, runlog=runlog,
                                  prompt_version="smoke-1", budget=budget, provider=provider)
            ctx = CallContext(pass_="SMOKE", record_id=f"{spec.provider}.{spec.model}", upstream=runlog.run_id)
            done = client.complete_ex("Reply with JSON only.", 'Return {"ok": true}.', schema, ctx=ctx)
        except ProviderError as exc:
            typer.echo(f"{spec.provider}/{spec.model}: FAILED: {exc}", err=True)
            continue
        served = f" (served by {done.model})" if done.substituted else ""
        typer.echo(f"{spec.provider}/{spec.model}: ok={done.data.get('ok')} "
                   f"tokens={done.usage.input_tokens}+{done.usage.output_tokens}{served}")
    runlog.write_ledger()
    typer.echo(f"smoke spend: ${budget.spent_run:.4f}; subscription calls: {budget.calls_run}")


def _ping_cli_providers(paths: Any, settings: Any, env: dict[str, str], only: str | None = None) -> bool:
    """G1a first live step: one tiny call per subscription CLI provider, reporting what billed it
    (login method, apiKeySource), what the CLI loaded, and the shadow cost. Nothing else runs."""
    from animedex.budget import Budget
    from animedex.config import CLI_TYPES, is_placeholder
    from animedex.providers.base import ProviderError
    from animedex.providers.cli_common import stripped_names, unexpected_loads
    from animedex.providers.client import CallContext
    from animedex.providers.factory import build_client, build_provider
    from animedex.store.runlog import RunLog, new_run_id

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
              "additionalProperties": False}
    picked: dict[str, str] = {}  # provider profile -> first model slot that uses it (config order)
    for key, spec in settings.models.items():
        profile = settings.providers.get(spec.provider)
        if profile and profile.type in CLI_TYPES and spec.provider not in picked and not is_placeholder(spec.model) \
                and only in (None, spec.provider):
            picked[spec.provider] = key
    if not picked:
        typer.echo("no model slot uses a subscription CLI provider", err=True)
        return False
    typer.echo("stripped from every CLI call (names only): " + (", ".join(stripped_names()) or "none"))
    runlog = RunLog(paths.raw_runs, new_run_id())
    budget = Budget.from_settings(settings)
    ok = True
    for provider_name, key in picked.items():
        spec = settings.models[key]
        try:
            provider = build_provider(spec.provider, settings, env)
        except ProviderError as exc:
            typer.echo(f"{provider_name}: CLI unavailable: {exc}", err=True)
            ok = False
            continue
        login = provider.login_status()
        typer.echo(f"{provider_name} ({provider.identity}): logged_in={login['logged_in']} method={login['method']}")
        if not login["logged_in"] or login["api_key"]:
            why = "an API-key login would bill the API, not your plan" if login["api_key"] else "not logged in"
            typer.echo(f"  SKIPPED: {why}; no call made", err=True)
            ok = False
            continue
        client = build_client(key, paths=paths, settings=settings, env=env, runlog=runlog, prompt_version="smoke-1",
                              budget=budget, provider=provider)
        ctx = CallContext(pass_="SMOKE", record_id=f"{provider_name}.{spec.model}", upstream=runlog.run_id)
        try:
            done = client.complete_ex("Reply with JSON only.", 'Return {"ok": true}.', schema, ctx=ctx)
        except ProviderError as exc:
            typer.echo(f"  FAILED: {exc}", err=True)
            ok = False
            continue
        init = dict(getattr(provider, "last_init", {}) or {})
        shadow = runlog.shadow_cost.get(f"SMOKE:{ctx.record_id}", 0.0)
        typer.echo(f"  slot={key} requested={spec.model} served={done.model} ok={done.data.get('ok')} "
                   f"tokens={done.usage.input_tokens}+{done.usage.output_tokens} shadow_cost=${shadow:.4f}")
        typer.echo("  loaded: " + json.dumps({k: (v if isinstance(v, (str, int, bool)) or v is None else len(v))
                                              for k, v in init.items() if k != "cwd"}, sort_keys=True))
        for item in unexpected_loads(init) + [f"user-level: {x}" for x in init.get("user_level_leaks", [])]:
            typer.echo(f"  REPORT: {item}")
    runlog.write_ledger()
    typer.echo(f"calls made: {budget.calls_run}; run log: {runlog.dir}")
    typer.echo("Stop here: check your Claude and ChatGPT usage pages before any partner run.")
    return ok


@gold_app.command("init")
def gold_init(title_id: str, title: str = typer.Option(..., "--title", help="Display title.")) -> None:
    """Write a blank blind-annotation template (never overwrites)."""
    from animedex.gold import annotation_path, render_template
    from animedex.ontology import get_vocab
    from animedex.store.atomic import atomic_write_text

    paths = _paths()
    settings = load_settings(paths)
    path = annotation_path(paths, title_id)
    if path.exists():
        typer.echo(f"{path.relative_to(paths.root)} already exists; not overwriting", err=True)
        raise typer.Exit(1)
    bounds = settings.eval.get("gold_elements", {})
    text = render_template(title_id, title, list(settings.eval.get("gold_key_fields", [])), get_vocab(paths),
                           int(bounds.get("min", 3)))
    atomic_write_text(path, text)
    typer.echo(f"wrote {path.relative_to(paths.root)}")


@gold_app.command("status")
def gold_status_cmd() -> None:
    """Same as `animedex eval` readiness section."""
    eval_()


def main() -> None:
    app()


if __name__ == "__main__":
    main()
