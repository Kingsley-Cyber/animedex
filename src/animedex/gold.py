"""Gold-set annotation files (09, G1c) and their readiness check (G2).

Kingsley fills `eval/gold/<title_id>/annotation.yaml` blind, before seeing model output for that
title. A title is ready only when every field is filled AND the file is committed unchanged.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from animedex.ontology import Vocab
from animedex.paths import Paths

ANNOTATION = "annotation.yaml"
MIN_ENGINE_WORDS = 4


def annotation_path(paths: Paths, title_id: str) -> Path:
    return paths.gold / title_id / ANNOTATION


def render_template(title_id: str, title: str, key_fields: list[str], vocab: Vocab, elements_min: int = 3) -> str:
    lines = [
        f"# Blind gold annotation: {title} ({title_id})",
        "# Fill this BEFORE any model output for this title is shown to you, then commit it.",
        "# Optional (owner ruling 2026-09-27): runs proceed without it; outputs stay counts-only until you say "
        '"annotations done" or "annotations waived".',
        f"title_id: {title_id}",
        "key_enums:   # one value each; allowed values are in the comment",
    ]
    for path in key_fields:
        lens = vocab.lens_field(path)
        allowed = " | ".join(vocab.enum(lens.vocab or path))
        lines.append(f'  {path}: ""   # {allowed}')
    lines.append("load_bearing_elements:   # 3-5 elements, in your own words")
    lines.extend('  - ""' for _ in range(elements_min))
    lines.append('main_engine: ""   # one sentence: who wants what, what blocks them, what it costs')
    lines.append('notes: ""')
    return "\n".join(lines) + "\n"


@dataclass
class GoldStatus:
    title_id: str
    path: Path
    exists: bool = False
    filled: bool = False
    committed: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.exists and self.filled and self.committed


def _git_ok(root: Path, *args: str) -> bool:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def is_committed(root: Path, path: Path) -> bool:
    """Tracked by git and identical to HEAD (no staged or unstaged edits)."""
    rel = str(path.relative_to(root))
    return _git_ok(root, "ls-files", "--error-unmatch", "--", rel) and _git_ok(
        root, "diff", "--quiet", "HEAD", "--", rel
    )


def _filled_problems(data: Any, title_id: str, key_fields: list[str], vocab: Vocab, lo: int, hi: int) -> list[str]:
    if not isinstance(data, dict):
        return ["file is not a YAML mapping"]
    problems = []
    if data.get("title_id") != title_id:
        problems.append(f"title_id must be {title_id}")
    enums = data.get("key_enums") or {}
    for path in key_fields:
        value = str(enums.get(path) or "").strip()
        allowed = vocab.enum(vocab.lens_field(path).vocab or path)
        if not value:
            problems.append(f"key_enums.{path} is empty")
        elif value not in allowed:
            problems.append(f"key_enums.{path}={value!r} is not one of {list(allowed)}")
    elements = [str(e).strip() for e in (data.get("load_bearing_elements") or []) if str(e or "").strip()]
    if not lo <= len(elements) <= hi:
        problems.append(f"load_bearing_elements needs {lo}-{hi} filled entries (has {len(elements)})")
    engine = str(data.get("main_engine") or "").strip()
    if len(engine.split()) < MIN_ENGINE_WORDS:
        problems.append("main_engine needs one full sentence")
    return problems


def gold_status(
    paths: Paths, title_id: str, key_fields: list[str], vocab: Vocab, lo: int = 3, hi: int = 5
) -> GoldStatus:
    path = annotation_path(paths, title_id)
    status = GoldStatus(title_id, path)
    if not path.is_file():
        status.problems.append(f"missing {path.relative_to(paths.root)}")
        return status
    status.exists = True
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        status.problems.append(f"invalid YAML: {exc}")
        return status
    fill = _filled_problems(data, title_id, key_fields, vocab, lo, hi)
    status.problems.extend(fill)
    status.filled = not fill
    status.committed = is_committed(paths.root, path)
    if not status.committed:
        status.problems.append("not committed (commit the filled file; edits after commit also block)")
    return status


BLIND_FILE = "BLIND.yaml"
BLIND_STATES = ("pending", "annotations_done", "waived")


def blind_settings(paths: Paths) -> dict[str, Any]:
    """eval/gold/BLIND.yaml (owner ruling 2026-09-27). Missing file = the original strict guard."""
    f = paths.gold / BLIND_FILE
    if not f.is_file():
        return {"state": "pending", "runs_without_annotations": False}
    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    state = str(data.get("state", "pending"))
    if state not in BLIND_STATES:
        raise ValueError(f"{f}: state must be one of {BLIND_STATES}")
    return {"state": state, "runs_without_annotations": bool(data.get("runs_without_annotations", False))}


def masked_titles(paths: Paths, gold_ids: set[str]) -> set[str]:
    """Gold titles whose outputs may be shown only as counts (state still pending)."""
    return set(gold_ids) if blind_settings(paths)["state"] == "pending" else set()

