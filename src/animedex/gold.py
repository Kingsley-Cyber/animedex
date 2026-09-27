"""Gold titles and the blind rule: while the blind review is pending (eval/gold/BLIND.yaml), what a model
writes about a gold title is masked in diagnose output, so rating the packet stays blind."""

from __future__ import annotations

from typing import Any

import yaml

from animedex.paths import Paths

BLIND_FILE = "BLIND.yaml"
BLIND_STATES = ("pending", "annotations_done", "waived")


def gold_ids(paths: Paths) -> set[str]:
    """Title ids tagged `gold` in corpus/titles.yaml (the heavy path's corpus)."""
    if not paths.corpus_file.is_file():
        return set()
    data = yaml.safe_load(paths.corpus_file.read_text(encoding="utf-8")) or {}
    return {str(t["title_id"]) for t in data.get("titles") or [] if "gold" in (t.get("role_tags") or [])}


def blind_settings(paths: Paths) -> dict[str, Any]:
    """eval/gold/BLIND.yaml. A missing file means pending (the strict reading)."""
    f = paths.gold / BLIND_FILE
    if not f.is_file():
        return {"state": "pending"}
    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    state = str(data.get("state", "pending"))
    if state not in BLIND_STATES:
        raise ValueError(f"{f}: state must be one of {BLIND_STATES}")
    return {"state": state}


def masked_titles(paths: Paths, gold: set[str] | None = None) -> set[str]:
    """Gold titles whose model output is masked (the blind review is still pending)."""
    ids = gold_ids(paths) if gold is None else set(gold)
    return ids if blind_settings(paths)["state"] == "pending" else set()
