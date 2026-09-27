"""Pipeline stages (05). Stages arrive milestone by milestone; stubs say which milestone."""

from __future__ import annotations

STAGE_MILESTONE = {
    "ep": "M6",
    "rollup": "M6",
    "patterns": "M7",
}


class StageNotImplemented(RuntimeError):
    def __init__(self, stage: str):
        super().__init__(f"stage '{stage}' is built in {STAGE_MILESTONE[stage]}; not available yet")
        self.stage = stage
