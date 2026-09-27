"""Repository layout. Every module resolves files through here."""

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

    # ontology / config
    @property
    def vocab_file(self) -> Path:
        return self.root / "ontology" / "vocab.json"

    @property
    def cq_file(self) -> Path:
        return self.root / "ontology" / "competency_questions.yaml"

    @property
    def config_file(self) -> Path:
        return self.root / "config" / "settings.yaml"

    @property
    def env_file(self) -> Path:
        return self.root / ".env"

    @property
    def corpus_file(self) -> Path:
        """The heavy path's corpus; the light path reads only its gold tags (blind masking)."""
        return self.root / "corpus" / "titles.yaml"

    @property
    def prompts(self) -> Path:
        return self.root / "prompts"

    # the one store, and what the runs write
    @property
    def notes(self) -> Path:
        return self.root / "notes"

    @property
    def research(self) -> Path:
        return self.notes / "_research"

    @property
    def raw_runs(self) -> Path:
        return self.root / "data" / "raw" / "runs"

    @property
    def quarantine(self) -> Path:
        return self.root / "data" / "quarantine"

    @property
    def cache(self) -> Path:
        return self.root / "data" / "cache"

    @property
    def diagnose(self) -> Path:
        return self.root / "data" / "diagnose"

    # derived (gitignored)
    @property
    def build(self) -> Path:
        return self.root / "build"

    @property
    def quick(self) -> Path:
        return self.build / "quick"

    @property
    def exports(self) -> Path:
        return self.build / "exports"

    @property
    def reports(self) -> Path:
        return self.build / "reports"

    # the blind review (`make review`)
    @property
    def gold(self) -> Path:
        return self.root / "eval" / "gold"

    @property
    def blind(self) -> Path:
        return self.root / "eval" / "blind"
