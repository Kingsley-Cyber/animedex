"""`animedex` CLI (05). Stages not yet built exit 2 and name the milestone that builds them."""

from __future__ import annotations

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


@app.command()
def p1(title: str = TitleOpt, all_: bool = AllOpt, dry_run: bool = DryOpt) -> None:
    """P1 WHAT: title profile + moments (M2)."""
    _stub("p1")


@app.command()
def verify(title: str = TitleOpt, all_: bool = AllOpt, dry_run: bool = DryOpt) -> None:
    """VERIFY: web-check flagged fields + outcomes (M2)."""
    _stub("verify")


@app.command()
def p2(title: str = TitleOpt, all_: bool = AllOpt, dry_run: bool = DryOpt) -> None:
    """P2 WHY: effect + engine atoms (M3)."""
    _stub("p2")


@app.command()
def p3(title: str = TitleOpt, all_: bool = AllOpt, dry_run: bool = DryOpt) -> None:
    """P3 PROOF: contrast, explanation test, ablation (M3)."""
    _stub("p3")


@app.command()
def check(title: str = TitleOpt, all_: bool = AllOpt, dry_run: bool = DryOpt) -> None:
    """CHECK: falsifying critic (M3)."""
    _stub("check")


@app.command()
def p4(title: str = TitleOpt, all_: bool = AllOpt, dry_run: bool = DryOpt) -> None:
    """P4 TRANSFER: domain-neutral patterns + conditions (M3)."""
    _stub("p4")


@app.command()
def run(title: str = TitleOpt, all_: bool = AllOpt, dry_run: bool = DryOpt) -> None:
    """P1 -> CANONICALIZE for one title (M3)."""
    _stub("run")


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
    """Coverage, gaps, lanes, graveyard, CQ answers (M4)."""
    _stub("analyze")


@app.command()
def patterns() -> None:
    """Pattern cards (M7)."""
    _stub("patterns")


@app.command()
def ideate(generations: int = typer.Option(3, "--generations")) -> None:
    """MAP-Elites ideation (M5)."""
    _stub("ideate")


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
    from animedex.build.duckdb_build import build as run_build
    from animedex.build.duckdb_build import verify_determinism as run_verify

    paths = _paths()
    if verify_determinism:
        ok, diffs = run_verify(paths)
        for name, (a, b) in diffs.items():
            typer.echo(f"MISMATCH {name}: {a} != {b}", err=True)
        typer.echo("clean rebuild: identical hashes" if ok else "clean rebuild: HASH MISMATCH")
        raise typer.Exit(0 if ok else 1)
    hashes = run_build(paths)
    typer.echo(f"built {len(hashes)} tables/views -> {paths.build_db.relative_to(paths.root)}")


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
    typer.echo("agreement (AC-12) and load-bearing recall (AC-17) run once P1/P3 exist (M2/M3)")


@app.command()
def smoke(title: str = typer.Option(None, "--title")) -> None:
    """Live readiness: list what blocks live runs; when ready, one tiny call per configured model."""
    paths = _paths()
    settings = load_settings(paths)
    env = environment(paths)
    problems = live_problems(settings, env)
    if title:
        from animedex.guards import LiveRunRefused, check_live_title
        from animedex.ontology import get_vocab

        try:
            check_live_title(paths, settings, get_vocab(paths), title)
            typer.echo(f"{title}: live runs allowed (scope declared; blind guard clear)")
        except LiveRunRefused as exc:
            problems.append(str(exc))
    if problems:
        typer.echo("Live runs are blocked until these are filled (G1a):")
        for p in problems:
            typer.echo(f"  - {p}")
        raise typer.Exit(1)
    _ping_models(paths, settings, env)


def _ping_models(paths: Any, settings: Any, env: dict[str, str]) -> None:
    from animedex.budget import Budget
    from animedex.providers.client import CallContext
    from animedex.providers.factory import build_client
    from animedex.store.runlog import RunLog, new_run_id

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
              "additionalProperties": False}
    runlog = RunLog(paths.raw_runs, new_run_id())
    budget = Budget.from_settings(settings)
    seen: set[tuple[str, str]] = set()
    for key, spec in sorted(settings.models.items()):
        if key == "embeddings" or (spec.provider, spec.model) in seen:
            continue
        seen.add((spec.provider, spec.model))
        client = build_client(key, paths=paths, settings=settings, env=env, runlog=runlog,
                              prompt_version="smoke-1", budget=budget)
        ctx = CallContext(pass_="SMOKE", record_id=f"{spec.provider}.{spec.model}", upstream="none")
        data, usage = client.complete("Reply with JSON only.", 'Return {"ok": true}.', schema, ctx=ctx)
        typer.echo(f"{spec.provider}/{spec.model}: ok={data.get('ok')} tokens={usage.input_tokens}+{usage.output_tokens}")
    runlog.write_ledger()
    typer.echo(f"smoke spend: ${budget.spent_run:.4f}")


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
