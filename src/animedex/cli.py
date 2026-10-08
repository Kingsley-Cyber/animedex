"""`animedex` CLI: ingest, scan, abduct, quick, diagnose, analyze, export, review, data push/pull."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from animedex.config import environment, load_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="ANIMEDEX: a notes index of shows, and idea cards.")
data_app = typer.Typer(no_args_is_help=True, help="Private data backups (Kingsley-Cyber/animedex-data): push, pull.")
app.add_typer(data_app, name="data")


def _paths():
    from animedex.paths import Paths

    return Paths.discover()


def _catalog(paths: Any) -> tuple[Any, Any]:
    """(resolve(line), numbers(resolved)) on the AniList catalog, read-only."""
    from animedex.catalog.anilist import AniList
    from animedex.catalog.resolve import TvMaze, resolve
    from animedex.light.catalog import catalog_numbers

    anilist, tv = AniList(cache_dir=paths.cache / "anilist"), TvMaze()
    return (lambda line: resolve(anilist, line, tvmaze=tv)), (lambda res: catalog_numbers(anilist, res))


def _clients(paths: Any, settings: Any, keys: tuple[str, ...], calls_per_run: int | None = None) -> tuple[dict, Any]:
    """One client per slot under one call cap and one run log."""
    from animedex.budget import Budget
    from animedex.providers.factory import build_client
    from animedex.store.runlog import RunLog, new_run_id

    runlog = RunLog(paths.raw_runs, new_run_id())
    budget = Budget.from_settings(settings)
    if calls_per_run is not None:
        budget.calls_per_run = calls_per_run
    return {k: build_client(k, paths=paths, settings=settings, runlog=runlog, budget=budget) for k in keys}, runlog


@app.command()
def ingest(list_file: str = typer.Option(..., "--list", help="A text file, one show per line; (year) or (manga) hints.")
           ) -> None:
    """Study shows: one Sonnet call with web per three shows writes notes/<slug>.json (shows with a note are skipped)."""
    from animedex.light.ingest import read_list, run_ingest
    from animedex.ontology import get_vocab

    paths = _paths()
    settings, vocab = load_settings(paths), get_vocab(paths)
    resolve, numbers = _catalog(paths)
    clients, runlog = _clients(paths, settings, ("ingest",))
    result = run_ingest(paths, settings, vocab, read_list(Path(list_file)), client=clients["ingest"], resolve=resolve,
                        numbers=numbers, run_id=runlog.run_id, echo=typer.echo)
    runlog.write_ledger()
    for line in result.lines():
        typer.echo(line)
    if result.stopped:
        raise typer.Exit(3)


@app.command()
def scan() -> None:
    """Fetch current discourse and save source-backed candidate anomalies privately."""
    from animedex.light.abduction import AbductionError, AbductionPaused, run_scan

    paths = _paths()
    settings = load_settings(paths)
    scan_settings = settings.model_copy(update={"models": {**settings.models, "ingest": settings.models["scan"]}})
    clients, runlog = _clients(paths, scan_settings, ("ingest",))
    try:
        path, record = run_scan(paths, settings, client=clients["ingest"], run_id=runlog.run_id)
    except (AbductionError, AbductionPaused) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(3 if isinstance(exc, AbductionPaused) else 1) from exc
    finally:
        runlog.write_ledger()
    typer.echo(f"scan -> {path.relative_to(paths.root)}")
    for gap in record["gaps"]:
        typer.echo(f"  {gap['id']}: {gap['anomaly']} ({gap['source_date']}; {gap['source_url']})")


@app.command()
def abduct(scan_file: str = typer.Option(..., "--scan", help="A scan JSON path from animedex scan."),
           gap: str = typer.Option(..., "--gap", help="Gap ID printed by the scan, such as G1."),
           n: int = typer.Option(None, "--n", help="Candidate frames (default quick.cards)."),
           research: bool = typer.Option(False, "--research", help="Use the premise, reasoning, suspension, and feedback workflow."),
           hypothesis_check: bool = typer.Option(False, "--hypothesis-check", help="Challenge competing explanations before framing (research mode).")) -> None:
    """Turn a sourced gap into frames, then reject fusions before card scoring."""
    from animedex.light.abduction import (
        AbductionError,
        AbductionPaused,
        run_abduct,
        run_research_abduct,
    )

    paths = _paths()
    if hypothesis_check and not research:
        typer.echo("--hypothesis-check requires --research", err=True)
        raise typer.Exit(2)
    settings = load_settings(paths)
    clients, runlog = _clients(paths, settings, ("generate", "check"))
    try:
        runner = run_research_abduct if research else run_abduct
        kwargs = {"hypothesis_check": True} if hypothesis_check else {}
        path, record = runner(paths, scan_file=scan_file, gap_id=gap,
                              n=int(n if n is not None else settings.section("quick").get("cards", 6)),
                              clients=clients, run_id=runlog.run_id, **kwargs)
    except (AbductionError, AbductionPaused) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(3 if isinstance(exc, AbductionPaused) else 1) from exc
    finally:
        runlog.write_ledger()
    typer.echo(f"frames -> {path.relative_to(paths.root)}")
    for ref, frame in record["frames"].items():
        verdict = "ready" if frame["accepted"] else "rejected"
        typer.echo(f"  {ref} {verdict}: {frame['frame_sentence']} ({frame['gate']['reason']})")


@app.command()
def quick(seed: str = typer.Option(None, "--seed", help="A concept, a fight image, or a lane."),
          anomaly: str = typer.Option(None, "--anomaly", help="An observation that contradicts what you expected."),
          frames_file: str = typer.Option(None, "--frames-file", help="An abduct output containing an accepted frame."),
          frame_id: str = typer.Option(None, "--frame-id", help="Accepted frame ID, such as F1."),
          shows: str = typer.Option(None, "--shows", help="Shows to measure against, comma-separated (else research picks 3-5)."),
          n: int = typer.Option(None, "--n", help="Cards to write (default quick.cards).")) -> None:
    """Idea cards from a seed or anomaly: research, generate, check, prior art -> build/quick/ (private)."""
    from animedex.light.quick import QuickError, parse_shows, run_quick
    from animedex.ontology import get_vocab

    has_seed, has_anomaly = bool(seed and seed.strip()), bool(anomaly and anomaly.strip())
    has_frame = bool(frames_file and frames_file.strip() and frame_id and frame_id.strip())
    if sum((has_seed, has_anomaly, has_frame)) != 1 or bool(frames_file) != bool(frame_id):
        typer.echo('give either --seed "...", --anomaly "...", or --frames-file PATH with --frame-id F1', err=True)
        raise typer.Exit(2)
    paths = _paths()
    frame = None
    if has_frame:
        from animedex.light.abduction import AbductionError, load_selected_frame

        try:
            frame = load_selected_frame(paths, frames_file, frame_id)
        except AbductionError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
    settings, vocab = load_settings(paths), get_vocab(paths)
    cfg = settings.section("quick")
    resolve, numbers = _catalog(paths)
    clients, runlog = _clients(paths, settings, ("ingest", "generate", "check"), int(cfg.get("calls_per_run", 8)))
    try:
        result = run_quick(paths, settings, vocab,
                           seed=frame["sentence"] if frame else (anomaly if has_anomaly else seed),
                           anomaly=has_anomaly, selected_frame=frame,
                           shows=parse_shows(shows), n=int(n or cfg.get("cards", 6)),
                           clients=clients, resolve=resolve, numbers=numbers, run_id=runlog.run_id, echo=typer.echo)
    except QuickError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    runlog.write_ledger()
    for line in result.lines():
        typer.echo(line)
    if result.stopped:
        raise typer.Exit(3)


@app.command()
def diagnose(file: str = typer.Option(None, "--file", help="A text file holding your concept."),
             text: str = typer.Option(None, "--text", help="Your concept, pasted in quotes.")) -> None:
    """Check your own concept against the notes and steering/rules.yaml (two calls) -> data/diagnose/ (private)."""
    from animedex.embeddings.base import EmbedderUnavailable, build_embedder
    from animedex.light.diagnose import DiagnoseError, run_diagnose
    from animedex.ontology import get_vocab

    if bool(file) == bool(text):
        typer.echo('give your concept with --file PATH or --text "..." (one of them)', err=True)
        raise typer.Exit(2)
    concept = Path(file).read_text(encoding="utf-8") if file else text
    paths = _paths()
    settings, vocab = load_settings(paths), get_vocab(paths)
    clients, runlog = _clients(paths, settings, ("ingest", "check"), int(settings.section("diagnose").get("calls_per_run", 4)))
    try:
        embedder = build_embedder(settings, environment(paths))
    except EmbedderUnavailable as exc:
        typer.echo(f"  premise similarity skipped: {exc}", err=True)
        embedder = None
    try:
        result = run_diagnose(paths, settings, vocab, text=concept, clients=clients, embedder=embedder,
                              run_id=runlog.run_id, source="file" if file else "text")
    except DiagnoseError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    runlog.write_ledger()
    for line in result.lines:
        typer.echo(line)
    for handover in getattr(embedder, "fallbacks", []):  # never silent
        typer.echo(f"  embedder hand-over: {handover}", err=True)
    if result.stopped:
        raise typer.Exit(3)


@app.command()
def analyze() -> None:
    """Lanes and gaps from the notes, read in place -> build/reports/analysis.md."""
    from animedex.light.counts import analyze as run_analyze
    from animedex.ontology import get_vocab, load_cqs

    paths = _paths()
    answers, out = run_analyze(paths, get_vocab(paths), load_cqs(paths))
    for a in answers.values():
        g = a.get("gap_ranking")
        extra = f"; {len(g['real_gaps'])} real gap(s) over {g['n']} notes" if g else ""
        typer.echo(f"{a['id']}: {len(a['rows'])} row(s){extra}")
    typer.echo(f"report -> {out.relative_to(paths.root)}")


@app.command()
def export() -> None:
    """Spreadsheets: notes, cards, and linked ideation nodes and edges in build/exports/."""
    from animedex.light.counts import export as run_export
    from animedex.light.lookup import export_lookup

    paths = _paths()
    for f in [*run_export(paths), *export_lookup(paths)]:
        typer.echo(f"wrote {f.relative_to(paths.root)}")


@app.command()
def lookup(id: str = typer.Option(..., "--id", help="A node ID from ideation_nodes.csv.")) -> None:
    """Show a private record, its direct links, and its source lineage by stable ID."""
    from animedex.light.lookup import lookup as find

    try:
        result = find(_paths(), id)
    except KeyError:
        typer.echo(f"unknown ID: {id}", err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))


@app.command()
def review(port: int = typer.Option(8765, "--port"), open_browser: bool = typer.Option(True, "--open/--no-open"),
           summary: bool = typer.Option(False, "--summary", help="Review import: Bradley-Terry strengths from your "
                                        "ratings and panel picks, and the judge's agreement -> build/reports/taste.md"),
           date: str = typer.Option(None, "--date", help="With --summary: the packet date (default: the latest).")
           ) -> None:
    """Blind review page on http://127.0.0.1:<port> (localhost only); ratings save to eval/blind/."""
    import webbrowser

    from animedex.ideate.review import serve

    paths = _paths()
    if summary:
        from animedex.ideate.review import taste_summary

        try:
            res = taste_summary(paths, date)
        except FileNotFoundError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        p = res.picks
        typer.echo(f"taste: packet {res.date}, {res.rated}/{res.cards} rated; picks {p['kingsley']} from your ratings, "
                   f"{p['panel']} from {p['panel_files']} panel file(s), {p['skipped']} skipped -> {res.report}")
        if not res.complete:
            typer.echo("  arms stay hidden until every card is rated")
            return
        arms = ", ".join(f"{a} {v:.2f}" for a, v in sorted(res.arm_strength.items(), key=lambda x: -x[1]))
        agree = "n/a" if res.judge_agreement is None else f"{res.judge_agreement:.2f}"
        typer.echo(f"  arm strengths (Bradley-Terry): {arms or 'no cross-arm picks'}; judge agreement {agree} over "
                   f"{res.judge_pairs} pair(s)")
        return
    try:
        server = serve(paths.root / "eval" / "blind", port)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    typer.echo(f"blind review: {url} (this computer only). Ratings save as you go. Ctrl+C to stop.")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _data_config() -> tuple[Any, Any]:
    from animedex.datarepo import load_config

    paths = _paths()
    cfg = load_config(paths, load_settings(paths))
    if cfg is None:
        typer.echo("data_repo.remote is not set in config/settings.yaml", err=True)
        raise typer.Exit(1)
    return paths, cfg


@data_app.command("push")
def data_push(tag: str = typer.Option(None, "--tag", help="A tag to pair with the code, e.g. heavy-final.")) -> None:
    """Back up the notes, the cards and the private data to the data repo."""
    from animedex.datarepo import DataRepoError, push

    paths, cfg = _data_config()
    try:
        res = push(paths, cfg, tag=tag)
    except DataRepoError as exc:
        typer.echo(f"data push failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"data repo {res.head}: {res.changed} file(s) changed" + (", committed" if res.committed else ", nothing new")
               + (f"; tagged {res.tag}" if res.tag else ""))


@data_app.command("pull")
def data_pull() -> None:
    """Restore the backed-up data from the private data repo (never deletes local files)."""
    from animedex.datarepo import DataRepoError, pull

    paths, cfg = _data_config()
    try:
        n = pull(paths, cfg)
    except DataRepoError as exc:
        typer.echo(f"data pull failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"restored {n} file(s) from the data repo")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
