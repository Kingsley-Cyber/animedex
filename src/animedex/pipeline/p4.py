"""P4 TRANSFER (05): each load-bearing-eligible atom becomes a domain-neutral pattern with
essential, variable, and failure conditions and at least one bridge concept. Patterns carry no
titles, character names, or medium words (04 invariant; AC-18). v1.8 abstraction ladder: every
transfer also carries a mechanism, a principle ("when X, do Y, because Z") and an anti-pattern,
under the same no-names, no-medium-words rule."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from animedex.config import Settings
from animedex.content_guards import GuardConfig, record_problems
from animedex.eligibility import eligible_atom_ids
from animedex.integrity import name_leaks, name_list
from animedex.models import TransferAtom
from animedex.models.atoms import LADDER
from animedex.ontology import Vocab, get_bridge
from animedex.paths import Paths
from animedex.pipeline.common import (
    StageResult,
    guarded_call,
    provenance,
    raise_problems,
    write_candidates,
)
from animedex.prompts import RenderedPrompt, read_prompt
from animedex.providers.client import LLMClient
from animedex.store.cache import upstream_hash
from animedex.store.canonical import CanonicalStore
from animedex.textutil import medium_words

LISTS = ("essential_conditions", "variable_details", "failure_conditions")
NEUTRAL_TEXTS = ("pattern", *LADDER)   # texts that must stay free of names and medium words


def render_prompt(paths: Paths) -> RenderedPrompt:
    main = read_prompt(paths.prompts / "p4_transfer.md")
    bridge = get_bridge(paths)
    lines = [f"- {name}: {c['definition']}" for name, c in bridge.concepts.items()]
    return RenderedPrompt(main.body + "\n\nBridge concepts\n" + "\n".join(lines), main.version)


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def output_schema(atom_ids: list[str], bridge_names: list[str]) -> dict[str, Any]:
    items = {"type": "array", "items": {"type": "string"}}
    transfer = _obj({"source_atom_id": {"type": "string", "enum": atom_ids}, "pattern": {"type": "string"},
                     "bridge": {"type": "array", "items": {"type": "string", "enum": bridge_names}},
                     **{k: items for k in LISTS}, **{k: {"type": "string"} for k in LADDER}})
    return _obj({"transfers": {"type": "array", "items": transfer}})


def _atom_text(a: dict[str, Any]) -> str:
    if a["atom_kind"] == "effect":
        e = a["effect"]
        return f"- {a['atom_id']} (effect): {e['element']} -> {e['feeling']}, because {e['because']}"
    g = a["engine"]
    return (f"- {a['atom_id']} (engine): {g['agent']} wants {g['goal']} but {g['constraint']}; chooses {g['strategy']}; "
            f"gets {g['benefit']}, pays {g['cost']}; dilemma: {g['dilemma']}; question: {g['dramatic_question']}")


def assemble(out: dict[str, Any], atoms: dict[str, dict[str, Any]], prov: dict[str, Any]) -> list[dict[str, Any]]:
    ordered = sorted(out.get("transfers") or [], key=lambda t: str(t.get("source_atom_id")))
    records = []
    for n, t in enumerate(ordered, start=1):
        aid = str(t.get("source_atom_id"))
        records.append({"transfer_id": f"{aid.split('.')[0]}.t.{n:03d}", "source_atom_id": aid,
                        "atom_kind": (atoms.get(aid) or {}).get("atom_kind", "effect"), "pattern": t.get("pattern"),
                        "bridge": list(t.get("bridge") or []), **{k: list(t.get(k) or []) for k in LISTS},
                        **{k: t.get(k) or None for k in LADDER}, "provenance": prov})
    return records


def output_problems(out: dict[str, Any], atoms: dict[str, dict[str, Any]], names: tuple[set[str], set[str]],
                    guards: GuardConfig, vocab: Vocab) -> list[str]:
    problems: list[str] = []
    given = [t.get("source_atom_id") for t in out.get("transfers") or []]
    missing, dupes = sorted(set(atoms) - set(given)), sorted({g for g in given if given.count(g) > 1})
    if missing:
        problems.append(f"give one transfer for every atom; missing {missing[:5]}")
    if dupes:
        problems.append(f"one transfer per atom; duplicated {dupes[:5]}")
    prov = {"run_id": "check", "pass": "P4", "model": None, "prompt_version": None, "schema_version": "0",
            "vocab_version": vocab.version, "cache_key": None, "created_at": "1970-01-01T00:00:00+00:00"}
    for rec in assemble(out, atoms, prov):
        aid = rec["source_atom_id"]
        missing = [k for k in LADDER if not rec.get(k)]
        if missing:
            problems.append(f"{aid}: give {', '.join(missing)} (the abstraction ladder)")
        for key in NEUTRAL_TEXTS:
            text = str(rec.get(key) or "")
            leaks = name_leaks(text, *names)
            if leaks:
                problems.append(f"{aid}: {key} names {leaks[:3]}; remove titles and names")
            medium = medium_words(text)
            if medium:
                problems.append(f"{aid}: {key} uses medium words {medium}")
        try:
            TransferAtom.model_validate(rec)
        except ValidationError as exc:
            problems += [f"{aid}: {'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in exc.errors()[:4]]
        problems += [f"{aid}: {p}" for p in record_problems(rec, guards)]
    return problems


def run_p4(paths: Paths, title_ids: list[str], client: LLMClient, vocab: Vocab, settings: Settings, *, run_id: str,
           guards: GuardConfig | None = None, created_at: str | None = None) -> StageResult:
    guards = guards or GuardConfig.from_settings(settings)
    prompt = render_prompt(paths)
    client.prompt_version = prompt.version
    state = CanonicalStore(paths).state()
    eligible = eligible_atom_ids(state)
    names = name_list(state, vocab)
    bridge_names = list(get_bridge(paths).names)
    done_sources = {t["source_atom_id"] for t in state.get("transfer", [])}
    result = StageResult()
    for tid in title_ids:
        atoms = {m["atom_id"]: m for m in state.get("mechanism", [])
                 if m["title_id"] == tid and m["atom_id"] in eligible}
        if not atoms:
            result.skipped.append((tid, "no load-bearing-eligible atoms (after P3 and CHECK)"))
            continue
        if set(atoms) <= done_sources:
            result.skipped.append((tid, "transfers already canonical"))
            continue

        def check(out: dict[str, Any], _a: dict = atoms) -> None:
            raise_problems(output_problems(out, _a, names, guards, vocab))

        call = guarded_call(result, paths, "P4", "transfer", tid, client, prompt.system,
                            "ATOMS\n" + "\n".join(_atom_text(atoms[a]) for a in sorted(atoms)),
                            output_schema(sorted(atoms), bridge_names), upstream=upstream_hash(list(atoms.values())),
                            validate=check)
        if call.stop:
            break
        if call.completion is None:
            continue
        prov = provenance("P4", run_id, call.completion, prompt.version, vocab, created_at)
        records = assemble(call.completion.data, atoms, prov)
        write_candidates(paths, "transfer", tid, records)
        result.done.append(tid)
        result.bump("transfers", len(records))
    return result
