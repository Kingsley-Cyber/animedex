"""Versioned prompt files (10 §13). Each file starts with YAML front matter carrying `version`.

The effective prompt version used in cache keys is `<file version>+<sha8 of the rendered system
prompt>`, so a fragment, vocab, or threshold change always invalidates, even if a bump is missed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PromptFile:
    path: Path
    meta: dict[str, Any]
    body: str

    @property
    def version(self) -> str:
        return str(self.meta["version"])


def read_prompt(path: Path) -> PromptFile:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path.name}: missing front matter")
    _, fm, body = text.split("---\n", 2)
    meta = yaml.safe_load(fm) or {}
    if "version" not in meta:
        raise ValueError(f"{path.name}: front matter needs a version")
    return PromptFile(path, meta, body.strip() + "\n")


@dataclass(frozen=True)
class RenderedPrompt:
    system: str
    file_version: str

    @property
    def version(self) -> str:
        return f"{self.file_version}+{hashlib.sha256(self.system.encode('utf-8')).hexdigest()[:8]}"
