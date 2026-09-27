"""The enums the notes use (ontology/vocab.json) and the questions the notes answer
(ontology/competency_questions.yaml)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from animedex.paths import Paths


class OntologyError(ValueError):
    """The ontology files are malformed."""


@dataclass(frozen=True)
class Vocab:
    version: str
    enums: dict[str, tuple[str, ...]]

    def enum(self, name: str) -> tuple[str, ...]:
        try:
            return self.enums[name]
        except KeyError as exc:
            raise OntologyError(f"unknown enum {name!r}; the notes use {sorted(self.enums)}") from exc


@lru_cache(maxsize=8)
def _load_vocab(path: Path) -> Vocab:
    data = json.loads(path.read_text(encoding="utf-8"))
    enums = data.get("enums")
    if not isinstance(enums, dict) or not enums:
        raise OntologyError(f"{path}: expected an `enums` object")
    return Vocab(str(data.get("version", "")), {k: tuple(v) for k, v in enums.items()})


def get_vocab(paths: Paths | None = None) -> Vocab:
    return _load_vocab((paths or Paths.discover()).vocab_file)


@dataclass(frozen=True)
class Question:
    id: str
    text: str


@dataclass(frozen=True)
class CQSet:
    version: str
    questions: tuple[Question, ...]


def load_cqs(paths: Paths | None = None) -> CQSet:
    data = yaml.safe_load((paths or Paths.discover()).cq_file.read_text(encoding="utf-8")) or {}
    return CQSet(str(data.get("version", "")),
                 tuple(Question(str(q["id"]), str(q["text"])) for q in data.get("questions") or []))
