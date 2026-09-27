"""Live-run guards (06). A live call (any non-mock provider) about a title must pass:
- the title is in corpus/titles.yaml (so it has a declared scope);
- gold blind guard (owner ruling, G0): a gold title's eval/gold annotations are filled and
  committed. Otherwise the run refuses to start, so no gold output exists before the blind
  annotation does.
- Owner ruling 2026-09-27 (autopilot): with `runs_without_annotations: true` in
  eval/gold/BLIND.yaml, gold runs proceed without annotations; their outputs are then shown only
  as counts until the blind state is `annotations_done` or `waived` (gold.masked_titles).
"""

from __future__ import annotations

from typing import Any

import yaml

from animedex.config import Settings
from animedex.gold import blind_settings, gold_status
from animedex.models import CorpusEntry
from animedex.ontology import Vocab
from animedex.paths import Paths


class LiveRunRefused(RuntimeError):
    pass


def load_corpus(paths: Paths) -> dict[str, CorpusEntry]:
    if not paths.corpus_file.is_file():
        return {}
    data: Any = yaml.safe_load(paths.corpus_file.read_text(encoding="utf-8")) or {}
    entries = [CorpusEntry.model_validate(t) for t in data.get("titles") or []]
    ids = [e.title_id for e in entries]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"corpus/titles.yaml has duplicate title_ids: {dupes}")
    return {e.title_id: e for e in entries}


def check_live_title(paths: Paths, settings: Settings, vocab: Vocab, title_id: str) -> None:
    entry = load_corpus(paths).get(title_id)
    if entry is None:
        raise LiveRunRefused(f"{title_id} is not in corpus/titles.yaml; every title needs a declared scope")
    if "gold" in entry.role_tags:
        cfg = settings.eval
        bounds = cfg.get("gold_elements", {})
        status = gold_status(
            paths, title_id, list(cfg.get("gold_key_fields", [])), vocab,
            int(bounds.get("min", 3)), int(bounds.get("max", 5)),
        )
        if not status.ready and not blind_settings(paths)["runs_without_annotations"]:
            raise LiveRunRefused(
                f"blind guard: {title_id} is a gold title and its annotation is not ready: "
                + "; ".join(status.problems)
            )


def live_title_guard(paths: Paths, settings: Settings, vocab: Vocab):
    """Callable for LLMClient: raises LiveRunRefused when a live call about `title_id` must not run."""

    def guard(title_id: str) -> None:
        check_live_title(paths, settings, vocab, title_id)

    return guard
