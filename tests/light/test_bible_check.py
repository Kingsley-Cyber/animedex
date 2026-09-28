"""bible-check: a synthetic series folder against the lite and full specs (no model call, no real series text)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from animedex.cli import app
from animedex.light.bible_check import MANIFEST, check, read_manifest, snapshot


def _write(folder: Path, name: str, text: str) -> None:
    (folder / name).write_text(text, encoding="utf-8")


def _lite_run(folder: Path, questions: int = 60, scenes: int = 10) -> None:
    """What a passing lite run adds to a folder."""
    _write(folder, "00_OVERVIEW.md", "# Overview\n## Big decisions (conflicts)\n## Additions\n"
                                      "R1 pass. R2 pass. R3 pass. R4 pass. R5 not applicable.\n")
    _write(folder, "01_OPEN_QUESTIONS_ANSWERED.md",
           "\n".join(f"Q{i}. A question? RULE. An answer." for i in range(questions)) + "\n")
    _write(folder, "05_PILOT.md", "".join(f"Scene {i}\n- Shows: x\n- Teaches: y\n- Ledger: z\n" for i in range(scenes)))
    _write(folder, "06_SEASONS_AND_REVEALS.md", "# Seasons\n")


def _series(tmp_path: Path) -> Path:
    folder = tmp_path / "series"
    folder.mkdir()
    _write(folder, "01_CONCEPT.md", "# Concept — canon may keep its dashes\n")
    snapshot(folder)
    return folder


def _failed(folder: Path, spec: str = "lite") -> dict[str, str]:
    return {c.name: c.detail for c in check(folder, spec) if not c.ok}


def test_snapshot_records_canon(tmp_path: Path) -> None:
    folder = _series(tmp_path)
    assert (folder / MANIFEST).is_file()
    assert list(read_manifest(folder) or {}) == ["01_CONCEPT.md"]


def test_a_complete_lite_run_passes(tmp_path: Path) -> None:
    folder = _series(tmp_path)
    _lite_run(folder)
    assert _failed(folder) == {}


def test_missing_files_and_thin_output_fail(tmp_path: Path) -> None:
    folder = _series(tmp_path)
    _lite_run(folder, questions=12, scenes=3)
    (folder / "06_SEASONS_AND_REVEALS.md").unlink()
    failed = _failed(folder)
    assert "seasons" in failed["files"]
    assert failed["questions"].startswith("12 tagged")
    assert "Shows 3" in failed["pilot scenes"]


def test_a_changed_canon_file_fails(tmp_path: Path) -> None:
    folder = _series(tmp_path)
    _lite_run(folder)
    _write(folder, "01_CONCEPT.md", "# Concept, rewritten\n")
    assert "01_CONCEPT.md" in _failed(folder)["canon"]


def test_style_is_checked_only_in_added_files(tmp_path: Path) -> None:
    folder = _series(tmp_path)
    _lite_run(folder)
    _write(folder, "07_NOTES.md", "A tapestry of ideas — twice — over.\n")
    detail = _failed(folder)["style"]
    assert "07_NOTES.md: 2 em-dash(es)" in detail and "tapestry" in detail
    assert "01_CONCEPT.md" not in detail


def test_no_manifest_fails_canon(tmp_path: Path) -> None:
    folder = _series(tmp_path)
    (folder / MANIFEST).unlink()
    _lite_run(folder)
    assert "run bible-snapshot" in _failed(folder)["canon"]


def test_pitch_length_and_flagged_word(tmp_path: Path) -> None:
    folder = _series(tmp_path)
    _lite_run(folder)
    _write(folder, "_pitch.md", "word " * 801 + "monster\n")
    detail = _failed(folder)["pitch"]
    assert "802 words" in detail and "monster" in detail


def test_full_spec_asks_for_more(tmp_path: Path) -> None:
    folder = _series(tmp_path)
    _lite_run(folder)
    failed = _failed(folder, "full")
    assert "variations" in failed["files"] and "faq" in failed["files"]
    assert failed["questions"].startswith("60 tagged (needs 150)")
    assert "edge-case matrix" in failed["stress test"]


def test_cli_exit_codes(tmp_path: Path) -> None:
    folder = tmp_path / "series"
    folder.mkdir()
    _write(folder, "01_CONCEPT.md", "# Concept\n")
    runner = CliRunner()
    assert runner.invoke(app, ["bible-snapshot", str(folder)]).exit_code == 0
    assert runner.invoke(app, ["bible-check", str(folder)]).exit_code == 1
    _lite_run(folder)
    result = runner.invoke(app, ["bible-check", str(folder)])
    assert result.exit_code == 0, result.output
    assert "0 of 6 check(s) failed" in result.output
    assert runner.invoke(app, ["bible-check", str(folder), "--spec", "huge"]).exit_code == 2
