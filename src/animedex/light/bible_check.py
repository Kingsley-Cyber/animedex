"""Series-bible checks with no model call: a series folder in seeds/ against the owner's bible spec.

`make bible-snapshot SERIES=seeds/<folder>` writes `<folder>/.canon_manifest`: every .md file there now, with
its sha256, i.e. the canon a bible run must not touch. `make bible-check SERIES=seeds/<folder> [SPEC=lite|full]`
then checks the run's output: the files the spec needs, the tagged viewer questions, the pilot's scene lines,
the overview's sections, the stress test (full spec), house style in the files the run added (no em-dashes, no
banned words), the pitch's length, and that every canon file is unchanged. It does the job of the writers' own
re-check passes, which were the most expensive part of a run (D-064).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

MANIFEST = ".canon_manifest"
EM_DASH = "—"
BANNED = ("delve", "testament", "tapestry", "load-bearing", "worth noting", "it's important to remember")
TAG = re.compile(r"\b(?:RULE|MYSTERY|BACKGROUND)\b")
SCENE_LINES = ("Shows", "Teaches", "Ledger")
PITCH_MAX_WORDS = 800  # `make diagnose` refuses a longer concept
PITCH_FLAGGED = "monster"  # the name-leak check reads it as a show title


@dataclass(frozen=True)
class Spec:
    files: dict[str, tuple[str, ...]]  # what the spec needs -> filename globs, any one of which will do
    min_questions: int = 0  # tagged questions; 0 skips the check
    min_scene_lines: int = 0  # Shows / Teaches / Ledger lines in the pilot; 0 skips the check
    overview: bool = False  # the overview names conflicts, additions and R1 to R5
    stress_test: bool = False
    markers: tuple[tuple[str, str, str, int], ...] = ()  # (check name, file glob, regex, at least this many)


WORLD_FILES = ("00_README", "01_CONCEPT", "02_WORLD", "03_POWER_SYSTEM", "04_MASK_CATALOG", "05_LORE_AND_HISTORY",
               "06_CHARACTERS", "07_FACTIONS", "08_STORY_ENGINE", "09_SEASON_01", "10_PILOT",
               "11_TRANSFORMATION_BIBLE", "12_VISUAL_AND_AUDIO_BIBLE", "13_MYSTERIES_AND_ENDGAME", "14_CANON_LEDGER",
               "15_DIAGNOSIS")

SPECS: dict[str, Spec] = {
    "lite": Spec({"overview": ("00_OVERVIEW*.md",), "questions": ("*QUESTIONS*.md",), "pilot": ("*PILOT*.md",),
                  "seasons": ("*SEASONS*.md",)},
                 min_questions=60, min_scene_lines=10, overview=True),
    # The template's 150 counts questions before duplicates are merged; the files hold the merged list, whose
    # finished runs landed between 139 and 254, so the floor for the merged list is 120.
    "full": Spec({"overview": ("00_OVERVIEW*.md",), "questions": ("*QUESTIONS*.md",), "pilot": ("*PILOT*.md",),
                  "seasons": ("*SEASONS*.md",), "variations": ("*VARIATIONS*.md",), "faq": ("*FAQ*.md",)},
                 min_questions=120, min_scene_lines=20, overview=True, stress_test=True),
    # The owner's sixteen-file world bible (2026-09-28): the files, the ledger's tiers and laid-out contradictions,
    # both audits, at least eight catalogued masks, and a transformation sheet that reaches the legendary form.
    "world": Spec({name: (f"{name}.md",) for name in WORLD_FILES},
                  markers=(("ledger tiers", "14_CANON_LEDGER.md", r"\bLOCKED\b", 1),
                           ("ledger contradictions", "14_CANON_LEDGER.md", r"\bVERSION A\b", 1),
                           ("complexity audit", "15_DIAGNOSIS.md", r"(?i)\bcomplexity\b", 1),
                           ("originality audit", "15_DIAGNOSIS.md", r"(?i)\boriginality\b", 1),
                           ("mask catalog", "04_MASK_CATALOG.md", r"(?i)\bweakness\b", 8),
                           ("transformation sheet", "11_TRANSFORMATION_BIBLE.md", r"(?i)\blegendary\b", 1))),
}
STRESS_PARTS = (("edge-case matrix", r"edge[- ]case"), ("shortcut audit", r"why don.?t they just"),
                ("ladder", r"\bladder\b"))


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(paths: list[Path]) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in paths)


def snapshot(folder: Path) -> Path:
    """Record every .md file now in `folder` as canon; returns the manifest path."""
    lines = [f"{_sha256(p)}  {p.name}" for p in sorted(folder.glob("*.md"))]
    out = folder / MANIFEST
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def read_manifest(folder: Path) -> dict[str, str] | None:
    """{file name: sha256} from the folder's manifest, or None when the folder has none."""
    path = folder / MANIFEST
    if not path.is_file():
        return None
    canon: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            canon[name.strip()] = digest
    return canon


def banned_words(text: str) -> list[str]:
    low = text.lower()
    return [w for w in BANNED if re.search(rf"\b{re.escape(w)}\b", low)]


def check(folder: Path, spec_name: str = "lite") -> list[Check]:
    """Every check for one series folder; a Check with ok=False is a failure."""
    spec = SPECS[spec_name]
    found = {label: sorted({p for g in globs for p in folder.glob(g)}) for label, globs in spec.files.items()}
    missing = [label for label, paths in found.items() if not paths]
    checks = [Check("files", not missing,
                    f"missing: {', '.join(missing)}" if missing else f"{len(found)} of {len(found)} present")]

    if spec.min_questions:
        tags = len(TAG.findall(_text(found["questions"])))
        checks.append(Check("questions", tags >= spec.min_questions, f"{tags} tagged (needs {spec.min_questions})"))

    if spec.min_scene_lines:
        pilot = _text(found["pilot"])
        counts = {k: len(re.findall(rf"\b{k}\s*:", pilot)) for k in SCENE_LINES}
        checks.append(Check("pilot scenes", min(counts.values()) >= spec.min_scene_lines,
                            ", ".join(f"{k} {n}" for k, n in counts.items())
                            + f" (needs {spec.min_scene_lines} each)"))

    if spec.overview:
        overview = _text(found["overview"])
        rules = sorted(set(re.findall(r"\bR[1-5]\b", overview)))
        absent = [s for s in ("conflict", "addition") if s not in overview.lower()]
        checks.append(Check("overview", not absent and len(rules) == 5,
                            (f"no {' or '.join(absent)} section; " if absent else "")
                            + f"steering rules named: {', '.join(rules) or 'none'}"))

    for name, glob, pattern, least in spec.markers:
        hits = len(re.findall(pattern, _text(sorted(folder.glob(glob)))))
        checks.append(Check(name, hits >= least, f"{hits} in {glob} (needs {least})"))

    if spec.stress_test:
        whole = _text(sorted(folder.glob("*.md"))).lower()
        lacking = [name for name, pattern in STRESS_PARTS if not re.search(pattern, whole)]
        checks.append(Check("stress test", not lacking,
                            f"missing: {', '.join(lacking)}" if lacking else "edge cases, ladder and shortcut audit"))

    canon = read_manifest(folder)
    if canon is None:
        checks.append(Check("canon", False, f"no {MANIFEST}: run bible-snapshot before a bible run"))
    else:
        changed = [n for n, digest in canon.items() if not (folder / n).is_file() or _sha256(folder / n) != digest]
        checks.append(Check("canon", not changed, f"changed or missing: {', '.join(changed)}" if changed
                            else f"{len(canon)} file(s) unchanged"))
        added = [p for p in sorted(folder.glob("*.md")) if p.name not in canon]
        problems = []
        for p in added:
            text = p.read_text(encoding="utf-8")
            if text.count(EM_DASH):
                problems.append(f"{p.name}: {text.count(EM_DASH)} em-dash(es)")
            if words := banned_words(text):
                problems.append(f"{p.name}: {', '.join(words)}")
        checks.append(Check("style", not problems, "; ".join(problems) if problems
                            else f"{len(added)} added file(s) clean"))

    pitch = folder / "_pitch.md"
    if pitch.is_file():
        text = pitch.read_text(encoding="utf-8")
        words, flagged = len(text.split()), PITCH_FLAGGED in text.lower()
        checks.append(Check("pitch", words <= PITCH_MAX_WORDS and not flagged,
                            f"{words} words (max {PITCH_MAX_WORDS})" + (f"; says '{PITCH_FLAGGED}'" if flagged else "")))
    return checks
