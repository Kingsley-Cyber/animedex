"""Kingsley's steering rules (`steering/rules.yaml`, private; owner decision 2026-09-27).

M5 fair baselines (controls A5): every arm of the blind review gets the same rules, rendered by
the same function, so ANIMEDEX's brief and both baselines read identical lines. The file is a
YAML list (or `rules:` list) of `{id, rule, strength}`, strength `hard` or `soft`. No file means
no rules. A malformed file stops the run (fail closed) rather than silently dropping a rule.
Checking rules in code or by the judge comes after blind review #1 (CHANGE_PLAN_ideation_modes §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from animedex.paths import Paths

STRENGTHS = ("hard", "soft")


class SteeringError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    id: str
    rule: str
    strength: str


def rules_file(paths: Paths):
    return paths.root / "steering" / "rules.yaml"


def load_rules(paths: Paths) -> list[Rule]:
    path = rules_file(paths)
    if not path.is_file():
        return []
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SteeringError(f"steering/rules.yaml is not valid YAML: {exc}") from exc
    items = data.get("rules") if isinstance(data, dict) else data
    if items is None:
        return []
    if not isinstance(items, list):
        raise SteeringError("steering/rules.yaml must be a list of {id, rule, strength}")
    rules: list[Rule] = []
    for n, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise SteeringError(f"steering/rules.yaml item {n}: expected {{id, rule, strength}}")
        rid, text = str(item.get("id") or "").strip(), " ".join(str(item.get("rule") or "").split())
        strength = str(item.get("strength") or "").strip().lower()
        if not rid or not text or strength not in STRENGTHS:
            raise SteeringError(f"steering/rules.yaml item {n}: needs id, rule and strength (hard|soft)")
        rules.append(Rule(rid, text, strength))
    ids = [r.id for r in rules]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise SteeringError(f"steering/rules.yaml: duplicate rule ids {dupes}")
    return rules


def rule_lines(rules: list[Rule]) -> list[str]:
    """The one rendering every arm receives (`key: value`, hard rules first, then by id)."""
    ordered = sorted(rules, key=lambda r: (STRENGTHS.index(r.strength), r.id))
    return [f"rule {r.id} ({r.strength}): {r.rule}" for r in ordered]
