"""Module activation (05 P1 table). Deterministic rules live in ontology/vocab.json; modules marked
`judgment` are the model's call. `violations` returns what a profile gets wrong."""

from __future__ import annotations

from animedex.ontology import Vocab


def _clause(clause: dict, medium: str, fmt: str, active: set[str]) -> bool:
    if "module" in clause:
        return clause["module"] in active
    value = medium if clause["field"] == "medium" else fmt
    return value in clause["in"] if "in" in clause else value not in clause["not_in"]


def expected_by_rule(vocab: Vocab, medium: str, fmt: str, active: set[str]) -> dict[str, bool]:
    """For rule-driven modules only: must the module be active?"""
    out = {}
    for module, spec in vocab.module_activation.items():
        if spec["kind"] == "rule":
            out[module] = any(_clause(c, medium, fmt, active) for c in spec["any"])
    return out


def violations(vocab: Vocab, medium: str, fmt: str, modules_active: list[str]) -> list[str]:
    active = set(modules_active)
    problems = []
    for module, must in sorted(expected_by_rule(vocab, medium, fmt, active).items()):
        if must and module not in active:
            problems.append(f"module {module} must be active for medium={medium}, format={fmt}")
        if not must and module in active:
            problems.append(f"module {module} must not be active for medium={medium}, format={fmt}")
    return problems
