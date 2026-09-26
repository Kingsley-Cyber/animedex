"""Owner ruling (G0): a live run on a gold title refuses to start unless its eval/gold annotation
is filled AND committed. Non-gold titles pass; titles outside the corpus never run live."""

from __future__ import annotations

import pytest
import yaml

from animedex.config import load_settings
from animedex.gold import annotation_path, gold_status, render_template
from animedex.guards import LiveRunRefused, check_live_title
from animedex.ontology import get_vocab
from tests.conftest import git

pytestmark = pytest.mark.unit

GOLD = "ironvale_circuit_2021"


def write_corpus(paths, gold=True):
    titles = [
        {"title_id": GOLD, "title": "Ironvale Circuit", "year": 2021, "medium": "anime", "format": "serialized",
         "scope": {"version": "synthetic TV", "seasons": [1], "numbering": "broadcast"},
         "role_tags": ["gold", "hit"] if gold else ["hit"]},
        {"title_id": "lantern_debt_2019", "title": "Lantern Debt", "year": 2019, "medium": "western_animation",
         "format": "episodic", "scope": {"version": "synthetic TV", "seasons": [1], "numbering": "broadcast"},
         "role_tags": ["contrast"]},
    ]
    paths.corpus_file.write_text(yaml.safe_dump({"titles": titles}))


def key_fields(paths):
    return list(load_settings(paths).eval["gold_key_fields"])


def fill(paths):
    vocab = get_vocab()
    path = annotation_path(paths, GOLD)
    data = yaml.safe_load(path.read_text())
    for f in key_fields(paths):
        data["key_enums"][f] = vocab.enum(vocab.lens_field(f).vocab)[0]
    data["load_bearing_elements"] = ["a private power meter", "memory as the price", "a rival crew"]
    data["main_engine"] = "She trades memories for grid power while hiding the cost."
    path.write_text(yaml.safe_dump(data))


def init_template(paths):
    path = annotation_path(paths, GOLD)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_template(GOLD, "Ironvale Circuit", key_fields(paths), get_vocab()))


def guard(paths):
    check_live_title(paths, load_settings(paths), get_vocab(), GOLD)


def test_template_lists_vocab_values_and_is_blank(repo):
    init_template(repo)
    text = annotation_path(repo, GOLD).read_text()
    assert "system_granted" in text and "individual | paired | collective" in text
    st = gold_status(repo, GOLD, key_fields(repo), get_vocab())
    assert st.exists and not st.filled and any("is empty" in p for p in st.problems)


def test_missing_annotation_refuses(git_repo):
    write_corpus(git_repo)
    with pytest.raises(LiveRunRefused, match="blind guard"):
        guard(git_repo)


def test_blank_template_refuses(git_repo):
    write_corpus(git_repo)
    init_template(git_repo)
    with pytest.raises(LiveRunRefused, match="is empty"):
        guard(git_repo)


def test_filled_but_uncommitted_refuses_then_commit_allows_then_edit_refuses(git_repo):
    write_corpus(git_repo)
    init_template(git_repo)
    fill(git_repo)
    with pytest.raises(LiveRunRefused, match="not committed"):
        guard(git_repo)
    git(git_repo.root, "add", "-A")
    git(git_repo.root, "commit", "-q", "-m", "gold annotation")
    guard(git_repo)  # ready
    path = annotation_path(git_repo, GOLD)
    path.write_text(path.read_text() + "notes: changed after commit\n")
    with pytest.raises(LiveRunRefused, match="not committed"):
        guard(git_repo)


def test_off_vocab_annotation_value_refuses(git_repo):
    write_corpus(git_repo)
    init_template(git_repo)
    fill(git_repo)
    path = annotation_path(git_repo, GOLD)
    data = yaml.safe_load(path.read_text())
    data["key_enums"]["core.outcome"] = "blockbuster"
    path.write_text(yaml.safe_dump(data))
    git(git_repo.root, "add", "-A")
    git(git_repo.root, "commit", "-q", "-m", "x")
    with pytest.raises(LiveRunRefused, match="not one of"):
        guard(git_repo)


def test_non_gold_title_is_allowed_and_unknown_title_refused(git_repo):
    write_corpus(git_repo, gold=False)
    guard(git_repo)
    with pytest.raises(LiveRunRefused, match="not in corpus"):
        check_live_title(git_repo, load_settings(git_repo), get_vocab(), "nobody_2000")
