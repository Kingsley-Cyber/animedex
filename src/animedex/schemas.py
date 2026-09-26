"""`make schemas`: JSON Schemas generated from the pydantic models (04: models are the source)."""

from __future__ import annotations

import json
from pathlib import Path

from animedex.models import RECORD_TYPES, CorpusEntry
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text


def schema_documents() -> dict[str, str]:
    docs: dict[str, str] = {}
    for name, rt in RECORD_TYPES.items():
        docs[f"{name}.schema.json"] = json.dumps(rt.model.model_json_schema(by_alias=True), indent=2, sort_keys=True) + "\n"
    docs["corpus_entry.schema.json"] = json.dumps(CorpusEntry.model_json_schema(by_alias=True), indent=2, sort_keys=True) + "\n"
    return docs


def write_schemas(paths: Paths) -> list[Path]:
    out = []
    for name, text in sorted(schema_documents().items()):
        path = paths.schemas / name
        atomic_write_text(path, text)
        out.append(path)
    return out


def stale_schemas(paths: Paths) -> list[str]:
    stale = []
    docs = schema_documents()
    for name, text in sorted(docs.items()):
        path = paths.schemas / name
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            stale.append(name)
    if paths.schemas.is_dir():
        stale.extend(sorted(p.name for p in paths.schemas.glob("*.schema.json") if p.name not in docs))
    return stale
