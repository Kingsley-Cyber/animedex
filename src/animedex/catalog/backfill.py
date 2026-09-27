"""`make backfill LIST=<file>`: a plain title list (one per line) -> scoped corpus entries -> the full
pipeline, in paced batches, reporting counts only.

- Titles already in corpus/titles.yaml are skipped.
- A version in parentheses is used as given; otherwise the most-watched adaptation is picked and
  every choice is listed in build/reports/backfill.md so Kingsley can correct it.
- Two versions of the same story (e.g. Berserk 1997 / 2016) become each other's nearest-neighbor
  contrast partner: same story, different execution.
- If the list is all hits or all anime, the report warns and suggests flops, mixed titles, and
  non-anime titles to keep the mix. It never blocks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from animedex.catalog.anilist import AniList, CatalogError
from animedex.catalog.resolve import TRAILING_YEAR, Resolved, TvMaze, norm, resolve
from animedex.models import CorpusEntry
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text

NON_ANIME_SUGGESTIONS = ("Arcane (2021)", "Castlevania (2017)", "Avatar: The Legend of Korra (2012)", "Primal (2019)",
                         "Blue Eye Samurai (2023)", "Scavengers Reign (2023)", "Daredevil (2015)", "Stranger Things (2016)")


@dataclass
class BackfillPlan:
    new: list[Resolved] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    pairs: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: dict[str, list[str]] = field(default_factory=dict)


def read_list(path: Path) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def _base(title: str) -> str:
    return norm(TRAILING_YEAR.sub("", title))


def plan_backfill(cat: AniList, lines: list[str], corpus: dict[str, CorpusEntry], *, tvmaze: TvMaze | None = None,
                  suggest: bool = True) -> BackfillPlan:
    plan = BackfillPlan()
    ids = set(corpus)
    refs = {e.catalog_ref: t for t, e in corpus.items() if e.catalog_ref}
    names = {(_base(e.title), e.year): t for t, e in corpus.items()}
    seen: set[str] = set()
    for line in lines:
        try:
            r = resolve(cat, line, tvmaze=tvmaze)
        except CatalogError as exc:
            plan.unresolved.append(f"{line} (catalog error: {exc})")
            continue
        if r is None:
            plan.unresolved.append(line)
            continue
        e = r.entry
        hit = (e["title_id"] if e["title_id"] in ids else refs.get(e.get("catalog_ref"))
               or names.get((_base(e["title"]), e["year"])))
        if hit:
            plan.skipped.append((line, f"already in the corpus as {hit}"))
        elif e["title_id"] in seen:
            plan.skipped.append((line, "listed twice"))
        else:
            seen.add(e["title_id"])
            plan.new.append(r)
    for a, b in combinations(plan.new, 2):
        same_story = (b.entry.get("catalog_ref") in a.alternative_refs or a.entry.get("catalog_ref") in b.alternative_refs
                      or (_base(a.entry["title"]) == _base(b.entry["title"]) and a.entry["year"] != b.entry["year"]))
        if same_story and a.entry["medium"] == b.entry["medium"]:
            plan.pairs.append((a.entry["title_id"], b.entry["title_id"]))
            for x, y in ((a, b), (b, a)):
                x.entry.setdefault("partners", {})["nearest_neighbor"] = y.entry["title_id"]
    _mix(plan, cat, corpus, suggest)
    return plan


def _mix(plan: BackfillPlan, cat: AniList, corpus: dict[str, CorpusEntry], suggest: bool) -> None:
    if not plan.new:
        return
    likely = [r.likely for r in plan.new]
    hits = sum(1 for x in likely if x == "hit")
    if not any(x in ("mixed", "flop") for x in likely) or hits / len(plan.new) > 0.7:
        plan.warnings.append(f"{hits} of {len(plan.new)} new titles look like hits by catalog score. Flops and mixed "
                             "titles teach the engine why things fail; consider adding some.")
    if all(r.entry["medium"] in ("anime", "donghua") for r in plan.new):
        plan.warnings.append("Every new title is anime or donghua. Cross-medium partners and imported lanes need "
                             "western animation, live action, or film.")
    if not (plan.warnings and suggest):
        return
    have = {_base(e.title) for e in corpus.values()} | {_base(r.entry["title"]) for r in plan.new}
    flops, mixed = [], []
    try:
        for page in range(1, 7):
            for m in cat.popular(page, country="JP", formats=("TV",)):
                name = m.english or m.romaji
                if _base(name) in have or any(r.kind == "PREQUEL" for r in m.relations) or m.score is None:
                    continue
                if m.score <= 62 and len(flops) < 6:
                    flops.append(f"{name} ({m.start[0]}; AniList {m.score})")
                elif 65 <= m.score <= 72 and len(mixed) < 6:
                    mixed.append(f"{name} ({m.start[0]}; AniList {m.score})")
    except CatalogError:
        pass
    plan.suggestions = {"flops": flops, "mixed": mixed,
                        "non-anime": [s for s in NON_ANIME_SUGGESTIONS if _base(s) not in have][:6]}


def add_to_corpus(paths: Paths, plan: BackfillPlan, source: str) -> list[str]:
    """Append validated entries to corpus/titles.yaml (comments above them are kept)."""
    entries = []
    for r in plan.new:
        entry = {k: v for k, v in r.entry.items() if v not in (None, [], {}) or k in ("role_tags",)}
        CorpusEntry.model_validate(entry)
        entries.append(entry)
    if not entries:
        return []
    text = paths.corpus_file.read_text(encoding="utf-8").rstrip("\n")
    m = re.search(r"^titles:[^\n]*\n(?:[ \t]*(?:#[^\n]*)?\n)*( *)- ", text, re.M)
    pad = m.group(1) if m else "  "  # match the file's own list indentation
    block = yaml.safe_dump(entries, sort_keys=False, allow_unicode=True, width=120)
    indented = "\n".join(f"{pad}{line}" if line else line for line in block.splitlines())
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    text += f"\n\n{pad}# --- backfill {stamp} from {source}: catalog-resolved; check the choices in build/reports/backfill.md ---\n"
    atomic_write_text(paths.corpus_file, text + indented + "\n")
    yaml.safe_load(paths.corpus_file.read_text(encoding="utf-8"))  # refuse to leave a broken corpus file
    return [e["title_id"] for e in entries]


def pending_titles(paths: Paths, title_ids: list[str]) -> list[str]:
    """Titles not yet through P4 (canonical coverage), in list order."""
    from animedex.store.canonical import CanonicalStore

    done = {c["title_id"] for c in CanonicalStore(paths).read("coverage") if "P4" in c.get("passes_done", [])}
    return [t for t in title_ids if t not in done]


def list_title_ids(plan: BackfillPlan, lines: list[str]) -> list[str]:
    """Every corpus id this list refers to (new and already present), in list order."""
    ids = [r.entry["title_id"] for r in plan.new]
    for _, why in plan.skipped:
        m = re.search(r"already in the corpus as (\S+)", why)
        if m:
            ids.append(m.group(1))
    return list(dict.fromkeys(ids))


def report(plan: BackfillPlan, source: str, batch_lines: list[str], waiting: int, list_path: str) -> str:
    lines = [f"# Backfill report: {source}", ""]
    if plan.new:
        lines += ["## Choices to check", "", "Correct any wrong pick by editing `corpus/titles.yaml` (or add the version "
                  "in parentheses to your list and run again).", "",
                  "| Your line | Chosen | Medium | Scope | How | Other matches |", "|---|---|---|---|---|---|"]
        for r in plan.new:
            e = r.entry
            lines.append(f"| {r.line} | {e['title']} ({e['year']}) `{e['title_id']}` | {e['medium']} | "
                         f"{e['scope']['version']}; seasons {e['scope']['seasons'] or 'n/a'} | {r.how} | "
                         f"{'; '.join(r.alternatives) or 'none'} |")
        lines.append("")
    if plan.pairs:
        lines += ["## Same story, different execution (paired as contrast partners)", ""]
        lines += [f"- {a} ↔ {b}" for a, b in plan.pairs] + [""]
    if plan.skipped:
        lines += ["## Skipped", ""] + [f"- {line}: {why}" for line, why in plan.skipped] + [""]
    if plan.unresolved:
        lines += ["## Not found in the catalogs", ""] + [f"- {u}" for u in plan.unresolved] + [""]
    if plan.warnings:
        lines += ["## Mix", ""] + [f"- {w}" for w in plan.warnings] + [""]
        for kind, items in plan.suggestions.items():
            if items:
                lines += [f"Suggested {kind}: " + "; ".join(items), ""]
    lines += ["## This batch (counts only)", "", *[f"- {x}" for x in batch_lines], ""]
    if waiting:
        lines += [f"{waiting} title(s) from this list still wait for the full pipeline. Run "
                  f"`make backfill LIST={list_path}` again; finished work is kept.", ""]
    return "\n".join(lines) + "\n"


def census_items(plan: BackfillPlan) -> list[Any]:
    from animedex.pipeline.census import CensusItem

    out = []
    for r in plan.new:
        e = r.entry
        if str(e.get("catalog_ref", "")).startswith("anilist:"):
            out.append(CensusItem(census_id=e["catalog_ref"], title=e["title"], year=e["year"], medium=e["medium"],
                                  format="MOVIE" if e["format"] == "film" else "TV", popularity=r.popularity))
    return out
