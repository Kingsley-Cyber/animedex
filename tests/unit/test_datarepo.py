"""Private data backups: mirror, push with paired tags, pull (a local bare repo stands in for GitHub)."""

from __future__ import annotations

import subprocess

import pytest

from animedex.datarepo import DataRepoConfig, mirror, pull, push
from animedex.paths import Paths

pytestmark = pytest.mark.unit


def _git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _root(tmp_path, name):
    root = tmp_path / name
    (root / "data" / "canonical").mkdir(parents=True)
    (root / "eval" / "gold").mkdir(parents=True)
    _git("init", "-q", str(root))
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "code", cwd=root)
    return root


def test_mirror_copies_updates_and_deletes_only_inside_the_listed_paths(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "a").mkdir(parents=True)
    (src / "a" / "one.jsonl").write_text("1\n")
    (dst / "a").mkdir(parents=True)
    (dst / "a" / "stale.jsonl").write_text("old\n")
    (dst / "keep").mkdir()
    (dst / "keep" / "x.txt").write_text("not managed\n")
    assert mirror(src, dst, ("a", "missing")) == 2  # one copied, one stale file removed
    assert (dst / "a" / "one.jsonl").read_text() == "1\n" and not (dst / "a" / "stale.jsonl").exists()
    assert (dst / "keep" / "x.txt").exists()  # outside the listed paths: untouched
    assert mirror(src, dst, ("a",)) == 0


def test_push_pairs_tags_and_pull_restores_on_a_fresh_checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    remote = tmp_path / "remote.git"
    _git("init", "-q", "--bare", str(remote))
    root = _root(tmp_path, "code")
    (root / "data" / "canonical" / "titles.jsonl").write_text('{"title_id": "iron_2020"}\n')
    (root / "eval" / "gold" / "notes.yaml").write_text("status: pending\n")
    (root / "data" / "cache").mkdir()
    (root / "data" / "cache" / "big.json").write_text("{}")  # never backed up
    cfg = DataRepoConfig(remote=str(remote), clone=tmp_path / "data-clone",
                         paths=("data/canonical", "eval/gold", "studio"))
    first = push(Paths(root), cfg, tag="m9-complete")
    assert first.committed and first.changed == 2 and first.tag == "m9-complete"
    assert "m9-complete" in _git("ls-remote", "--tags", str(remote))
    again = push(Paths(root), cfg)
    assert not again.committed  # nothing new: no empty commits
    fresh = _root(tmp_path, "fresh")
    restored = pull(Paths(fresh), DataRepoConfig(remote=str(remote), clone=tmp_path / "clone2", paths=cfg.paths))
    assert restored == 2 and (fresh / "data" / "canonical" / "titles.jsonl").read_text() == '{"title_id": "iron_2020"}\n'
    assert not (tmp_path / "data-clone" / "data" / "cache").exists()


