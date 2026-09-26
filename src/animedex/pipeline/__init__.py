"""Pipeline stages (05). Stages arrive milestone by milestone; stubs say which milestone."""

from __future__ import annotations

STAGE_MILESTONE = {
    "p1": "M2",
    "verify": "M2",
    "p2": "M3",
    "p3": "M3",
    "check": "M3",
    "p4": "M3",
    "run": "M3",
    "analyze": "M4",
    "ideate": "M5",
    "ep": "M6",
    "rollup": "M6",
    "patterns": "M7",
}


class StageNotImplemented(RuntimeError):
    def __init__(self, stage: str):
        super().__init__(f"stage '{stage}' is built in {STAGE_MILESTONE[stage]}; not available yet")
        self.stage = stage
