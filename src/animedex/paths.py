"""Repository layout (03). Every module resolves files through here."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT_ENV = "ANIMEDEX_ROOT"


def find_root(start: Path | None = None) -> Path:
    """Locate the repo root: $ANIMEDEX_ROOT, else the nearest ancestor holding ontology/vocab.json."""
    env = os.environ.get(ROOT_ENV)
    if env:
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "ontology" / "vocab.json").is_file() and (candidate / "config").is_dir():
            return candidate
    raise RuntimeError("ANIMEDEX repo root not found; run inside the repo or set ANIMEDEX_ROOT")


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def discover(cls, start: Path | None = None) -> Paths:
        return cls(find_root(start))

    # ontology / config / corpus
    @property
    def ontology(self) -> Path:
        return self.root / "ontology"

    @property
    def vocab_file(self) -> Path:
        return self.ontology / "vocab.json"

    @property
    def bridge_file(self) -> Path:
        return self.ontology / "bridge.json"

    @property
    def cq_file(self) -> Path:
        return self.ontology / "competency_questions.yaml"

    @property
    def proposals(self) -> Path:
        return self.ontology / "proposals"

    @property
    def config_file(self) -> Path:
        return self.root / "config" / "settings.yaml"

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    @property
    def corpus_file(self) -> Path:
        return self.root / "corpus" / "titles.yaml"

    @property
    def schemas(self) -> Path:
        return self.root / "schemas"

    @property
    def prompts(self) -> Path:
        return self.root / "prompts"

    # data tiers (03): only canonical/ is committed
    @property
    def canonical(self) -> Path:
        return self.root / "data" / "canonical"

    @property
    def raw_runs(self) -> Path:
        return self.root / "data" / "raw" / "runs"

    @property
    def candidates(self) -> Path:
        return self.root / "data" / "candidates"

    @property
    def quarantine(self) -> Path:
        return self.root / "data" / "quarantine"

    @property
    def cache(self) -> Path:
        return self.root / "data" / "cache"

    # light path (owner instruction 2026-09-27): the notes index and quick cards, private (mirrored to the data repo)
    @property
    def notes(self) -> Path:
        return self.root / "notes"

    @property
    def research(self) -> Path:
        return self.notes / "_research"

    @property
    def quick(self) -> Path:
        return self.root / "build" / "quick"

    # derived (gitignored, rebuildable)
    @property
    def build(self) -> Path:
        return self.root / "build"

    @property
    def build_db(self) -> Path:
        return self.build / "animedex.duckdb"

    @property
    def build_hashes(self) -> Path:
        return self.build / "hashes.json"

    @property
    def exports(self) -> Path:
        return self.build / "exports"

    @property
    def reports(self) -> Path:
        return self.build / "reports"

    # eval
    @property
    def gold(self) -> Path:
        return self.root / "eval" / "gold"

    @property
    def blind(self) -> Path:
        return self.root / "eval" / "blind"
