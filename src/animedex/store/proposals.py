"""Off-vocab proposals (04): `other:<phrase>` is stored as `other` and queued for owner review."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from animedex.store.atomic import atomic_write_text
from animedex.textutil import stable_json


@dataclass(frozen=True)
class Proposal:
    field: str
    proposed: str
    record_type: str
    record_id: str
    path: str
    run_id: str | None = None


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60] or "blank"


def proposal_file(root: Path, field: str, proposed: str) -> Path:
    return root / field / f"{slug(proposed)}.json"


def write_proposal(root: Path, proposal: Proposal) -> Path:
    """Create or extend the proposal file; examples stay sorted and de-duplicated."""
    path = proposal_file(root, proposal.field, proposal.proposed)
    data: dict[str, Any]
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"field": proposal.field, "proposed": proposal.proposed, "status": "pending", "examples": []}
    example = {
        "record_type": proposal.record_type,
        "record_id": proposal.record_id,
        "path": proposal.path,
        "run_id": proposal.run_id,
    }
    examples = {stable_json(e): e for e in data.get("examples", [])}
    examples[stable_json(example)] = example
    data["examples"] = [examples[k] for k in sorted(examples)]
    atomic_write_text(path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return path


def pending_proposals(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status") == "pending":
            out.append(data)
    return out
