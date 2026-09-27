"""Steering library (v1.8, owner decision 2026-09-27): rules Kingsley passes to `make ideas`.

`steering/rules.yaml` is his own input (git-ignored; backed up to the private data repo). It holds a
`version` and the rules, each with an id `rule.nnn`, the rule text (30 words or fewer), `hard` or
`soft`, 1-2 examples, and, for rules code can test, a `check` on an idea-card field (`op` in or
not_in `values`). A missing file is an empty library. `config/steering.example.yaml` shows the
format. Wiring the rules into IDEATE (reject before scoring, list them on every card) belongs to
M5; nothing here changes ideation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, model_validator

from animedex.models.common import RULE_ID, StrictModel, check_id
from animedex.models.ideation import IdeaCard
from animedex.paths import Paths
from animedex.textutil import Words30, Words40


def idea_field_schema(path: str) -> dict[str, Any] | None:
    """The JSON Schema of a dotted idea-card path (e.g. `mc.edge`), or None if the card has no such field.
    Lists resolve to their items, so a check on a list field tests its members."""
    root = IdeaCard.model_json_schema(by_alias=True)
    defs = root.get("$defs", {})
    node: dict[str, Any] = root

    def deref(n: dict[str, Any]) -> dict[str, Any]:
        while True:
            if "$ref" in n:
                n = defs[n["$ref"].split("/")[-1]]
            elif "anyOf" in n:
                n = next((b for b in n["anyOf"] if b.get("type") != "null"), n["anyOf"][0])
            elif n.get("type") == "array" and isinstance(n.get("items"), dict):
                n = n["items"]
            else:
                return n

    for part in path.split("."):
        props = deref(node).get("properties") or {}
        if part not in props:
            return None
        node = props[part]
    return deref(node)


def _resolve(card: dict[str, Any], path: str) -> Any:
    value: Any = card
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


class SteeringCheck(StrictModel):
    """A rule code can test on an idea card: `field` (a dotted card path) `op` (in|not_in) `values`.
    On a list field, `in` passes when any member is listed; `not_in` when none is."""

    field: str = Field(min_length=1)
    op: Literal["in", "not_in"]
    values: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _known(self) -> SteeringCheck:
        schema = idea_field_schema(self.field)
        if schema is None:
            raise ValueError(f"check.field {self.field!r} is not an idea-card field")
        allowed = [v for v in schema.get("enum") or [] if v is not None]
        unknown = [v for v in self.values if allowed and v not in allowed]
        if unknown:
            raise ValueError(f"check.values {unknown} are not values of {self.field} {allowed}")
        return self

    def passes(self, card: dict[str, Any]) -> bool | None:
        """True/False on a card that has the field; None when the card leaves it empty."""
        value = _resolve(card, self.field)
        if value is None or value == []:
            return None
        members = value if isinstance(value, list) else [value]
        listed = any(str(m) in self.values for m in members)
        return listed if self.op == "in" else not listed


class SteeringRule(StrictModel):
    id: str
    rule: Words30
    strength: Literal["hard", "soft"]
    examples: list[Words40] = Field(min_length=1, max_length=2)
    check: SteeringCheck | None = None

    @model_validator(mode="after")
    def _id(self) -> SteeringRule:
        check_id(RULE_ID, self.id, "rule id")
        return self


class SteeringLibrary(StrictModel):
    version: str = ""
    rules: list[SteeringRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> SteeringLibrary:
        ids = [r.id for r in self.rules]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate rule ids {dupes}")
        if self.rules and not self.version.strip():
            raise ValueError("a steering library with rules needs a version (cards record which rules they met)")
        return self


def steering_file(paths: Paths) -> Path:
    return paths.root / "steering" / "rules.yaml"


def load_steering(path: Path) -> SteeringLibrary:
    """The library at `path`; a missing file is an empty library."""
    if not path.is_file():
        return SteeringLibrary()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path.name}: expected a mapping with `version` and `rules`")
    return SteeringLibrary.model_validate({**data, "version": str(data.get("version", ""))})


def load_steering_rules(path: Path) -> list[SteeringRule]:
    return load_steering(path).rules
