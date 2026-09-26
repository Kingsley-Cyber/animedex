"""Run logs (03 raw tier): every request/response + token/cost ledger, under data/raw/runs/<run_id>/.

Fetched web text is transient (03, 10 §9/§19, P-08, G0 D1): before anything is written, each
fetched text is replaced by `[[web url=... sha256:... chars=N]]`. If a fetched text still
appears after redaction, the write is refused.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from animedex.store.atomic import atomic_write_text
from animedex.textutil import sha256_text, stable_json

MIN_LEAK_CHECK_CHARS = 40


@dataclass(frozen=True)
class TransientText:
    """Web text fetched for this call only. Never stored; logs keep url + hash + length."""

    url: str
    text: str

    @property
    def placeholder(self) -> str:
        return f"[[web url={self.url} {sha256_text(self.text)} chars={len(self.text)}]]"


class RedactionError(RuntimeError):
    pass


def redact(text: str, transients: tuple[TransientText, ...] | list[TransientText]) -> str:
    out = text
    for t in sorted(transients, key=lambda t: -len(t.text)):
        if t.text:
            out = out.replace(t.text, t.placeholder)
    for t in transients:
        if len(t.text) >= MIN_LEAK_CHECK_CHARS and t.text in out:
            raise RedactionError(f"fetched text from {t.url} survived redaction")
    return out


def new_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return "run_" + now.strftime("%Y%m%d_%H%M%S_%f")


class RunLog:
    def __init__(self, root: Path, run_id: str):
        self.run_id = run_id
        self.dir = root / run_id
        self.tokens: dict[str, dict[str, int]] = defaultdict(lambda: {"input": 0, "output": 0, "calls": 0})
        self.cost: dict[str, float] = defaultdict(float)

    def log_call(
        self,
        *,
        pass_: str,
        record_id: str,
        provider: str,
        model: str,
        cache_key: str,
        cache_hit: bool,
        attempt: int,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        system: str,
        user: str,
        response: str | None,
        transients: tuple[TransientText, ...] | list[TransientText] = (),
        error: str | None = None,
    ) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        system_sha = sha256_text(system)
        prompt_file = self.dir / "prompts" / f"{system_sha.split(':')[1]}.txt"
        if not prompt_file.exists():
            atomic_write_text(prompt_file, system)
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "pass": pass_,
            "record_id": record_id,
            "provider": provider,
            "model": model,
            "cache_key": cache_key,
            "cache_hit": cache_hit,
            "attempt": attempt,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
            "cost_usd": round(cost_usd, 6),
            "request": {"system_sha256": system_sha, "user": redact(user, transients)},
            "response": None if response is None else redact(response, transients),
            "error": error,
        }
        with (self.dir / "calls.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(stable_json(entry) + "\n")
        bucket = f"{pass_}:{record_id}"
        self.tokens[bucket]["input"] += input_tokens
        self.tokens[bucket]["output"] += output_tokens
        self.tokens[bucket]["calls"] += 0 if cache_hit else 1
        self.cost[bucket] += cost_usd

    def write_ledger(self) -> Path:
        ledger = {
            "run_id": self.run_id,
            "by_pass_record": {k: {**self.tokens[k], "cost_usd": round(self.cost[k], 6)} for k in sorted(self.tokens)},
            "total_cost_usd": round(sum(self.cost.values()), 6),
        }
        path = self.dir / "ledger.json"
        atomic_write_text(path, json.dumps(ledger, indent=2, sort_keys=True) + "\n")
        return path
