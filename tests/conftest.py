"""Shared fixtures. Every title and text here is synthetic (no copied or real-title text)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from animedex.paths import ROOT_ENV, Paths

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Paths:
    """A throwaway ANIMEDEX repo (real ontology, config, corpus, prompts) with ANIMEDEX_ROOT pointing at it."""
    root = tmp_path / "repo"
    root.mkdir()
    for name in ("ontology", "config", "corpus", "prompts"):
        shutil.copytree(REPO / name, root / name)
    (root / "eval" / "gold").mkdir(parents=True)
    monkeypatch.setenv(ROOT_ENV, str(root))
    return Paths(root)


def git(root: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


@pytest.fixture
def git_repo(repo: Paths) -> Paths:
    git(repo.root, "init", "-q", "-b", "main")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-q", "-m", "init")
    return repo


@pytest.fixture(autouse=True)
def no_real_cli(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Only fake CLIs under pytest's temp dir may run. A real `claude`/`codex` call would spend Kingsley's
    subscription, so every test refuses it."""
    from animedex.providers import cli_common

    base = str(tmp_path_factory.getbasetemp().resolve())
    monkeypatch.setattr(cli_common, "BINARY_GUARD", lambda binary: str(Path(binary).resolve()).startswith(base))
