#!/usr/bin/env python3
"""Repo-owned tool surface for IDE agents. All writes use the existing CLI."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = {
    "status": {"description": "Read local readiness and the latest private scan and frame IDs.",
               "required": [], "optional": []},
    "scan": {"description": "Fetch current anime discourse and save sourced candidate gaps.",
             "required": [], "optional": []},
    "abduct": {"description": "Challenge competing hypotheses, then run premise retrieval, reasoning lenses, frame comparison, feedback, and gate for a chosen sourced gap.",
               "required": ["--scan", "--gap"], "optional": ["--n"]},
    "quick": {"description": "Build cards only from a human-selected frame that passed the gate.",
              "required": ["--frames-file", "--frame-id"], "optional": ["--n"]},
    "lookup": {"description": "Trace a private scan, gap, hypothesis, frame, card, or verdict by ID.",
               "required": ["--id"], "optional": []},
}


def latest(directory: Path) -> tuple[Path, dict] | None:
    files = directory.glob("*.json") if directory.is_dir() else ()
    for path in sorted(files, key=lambda item: item.stat().st_mtime_ns, reverse=True):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict):
            return path, value
    return None


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def status() -> dict:
    scan = latest(ROOT / "notes" / "_scans")
    frames = latest(ROOT / "build" / "quick" / "_frames")
    result = {
        "root": str(ROOT),
        "available": {name: shutil.which(name) is not None for name in ("uv", "claude", "codex")},
        "latest_scan": None,
        "latest_frames": None,
        "human_gate": "Choose a sourced gap and a passing frame; the agent must not select for you.",
    }
    if scan:
        path, record = scan
        result["latest_scan"] = {
            "file": relative(path),
            "gaps": [gap.get("id") for gap in record.get("gaps", []) if isinstance(gap, dict)],
        }
    if frames:
        path, record = frames
        result["latest_frames"] = {
            "file": relative(path),
            "scan_file": record.get("scan_file"),
            "gap_id": (record.get("gap") or {}).get("id"),
            "passing_frames": [ref for ref, frame in (record.get("frames") or {}).items()
                               if isinstance(frame, dict) and frame.get("accepted")],
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="ANIMEDEX tools for Claude, Codex, or any IDE terminal")
    sub = parser.add_subparsers(dest="tool", required=True)
    sub.add_parser("tools", help="Print the tool contract as JSON")
    sub.add_parser("status", help="Print local state as JSON without model calls")
    sub.add_parser("scan", help="Fetch current discourse")
    abduct = sub.add_parser("abduct", help="Generate frames for a chosen gap")
    abduct.add_argument("--scan", required=True)
    abduct.add_argument("--gap", required=True)
    abduct.add_argument("--n", type=int)
    quick = sub.add_parser("quick", help="Build cards from a chosen passing frame")
    quick.add_argument("--frames-file", required=True)
    quick.add_argument("--frame-id", required=True)
    quick.add_argument("--n", type=int)
    lookup = sub.add_parser("lookup", help="Trace a node ID through the private ideation records")
    lookup.add_argument("--id", required=True)
    args = parser.parse_args()

    if args.tool == "tools":
        print(json.dumps({"tools": TOOLS, "sequence": ["status", "scan", "abduct", "quick", "lookup"],
                          "selection": "human", "implementation": "uv run animedex"}, indent=2))
        return 0
    if args.tool == "status":
        print(json.dumps(status(), indent=2))
        return 0
    if not shutil.which("uv"):
        print("uv is required to run ANIMEDEX", file=sys.stderr)
        return 1

    command = ["uv", "run", "animedex", args.tool]
    if args.tool == "abduct":
        command.extend(["--research", "--hypothesis-check", "--scan", args.scan, "--gap", args.gap])
    elif args.tool == "quick":
        command.extend(["--frames-file", args.frames_file, "--frame-id", args.frame_id])
    elif args.tool == "lookup":
        command.extend(["--id", args.id])
    if args.tool in {"abduct", "quick"} and args.n is not None:
        command.extend(["--n", str(args.n)])
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
