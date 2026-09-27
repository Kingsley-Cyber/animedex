"""P3 PROOF (05): one call per title tests every P2 atom against deterministic partners.
- contrast with each partner (nearest neighbor, flop, cross-medium for anime);
- explanation test for effect atoms: which explanation survives the natural experiment;
- ablation: collapses -> load_bearing, weakened -> supporting, unchanged -> decoration.
Load-bearing counts outside `p3.load_bearing_low_flag`-`p3.load_bearing_alarm` are flagged (AC-16).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from animedex.config import Settings
from animedex.content_guards import GuardConfig, record_problems
from animedex.guards import load_corpus
from animedex.models import ProofRecord
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import (
    StageResult,
    canonical_titles,
    guarded_call,
    outcomes,
    provenance,
    raise_problems,
    read_candidates,
    render_profile,
    write_candidates,
)
from animedex.pipeline.partners import select_partners
from animedex.prompts import RenderedPrompt, read_prompt
from animedex.providers.client import LLMClient
from animedex.store.cache import upstream_hash

ABLATION = ["load_bearing", "supporting", "decoration"]
FAVORS = ["because", "rival", "both", "neither"]


def render_prompt(paths: Paths) -> RenderedPrompt:
    main = read_prompt(paths.prompts / "p3_proof.md")
    return RenderedPrompt(main.body, main.version)


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def output_schema(atom_ids: list[str], partners: list[dict[str, str]]) -> dict[str, Any]:
    text, maybe = {"type": "string"}, {"type": ["string", "null"]}
    contrast = _obj({"partner_title_id": {"type": "string", "enum": [p["title_id"] for p in partners]},
                     "partner_role": {"type": "string", "enum": sorted({p["role"] for p in partners})},
                     "partner_has": {"type": "string", "enum": ["yes", "no", "partial"]}, "difference": text})
    test = _obj({"favors": {"type": ["string", "null"], "enum": [*FAVORS, None]}, "via_partner": maybe, "note": maybe})
    ablation = _obj({"if_removed": text, "verdict": {"type": "string", "enum": ABLATION}, "conf": {"type": "number"}})
    proof = _obj({"atom_id": {"type": "string", "enum": atom_ids}, "contrast": {"type": "array", "items": contrast},
                  "explanation_test": test, "ablation": ablation})
    return _obj({"proofs": {"type": "array", "items": proof}})


def _atom_lines(atom: dict[str, Any]) -> str:
    if atom["atom_kind"] == "effect":
        e = atom["effect"]
        return (f"{atom['atom_id']}: effect; element: {e['element']}; feeling: {e['feeling']}; "
                f"because: {e['because']}; rival: {e['rival_because']}")
    g = atom["engine"]
    return (f"{atom['atom_id']}: engine; agent: {g['agent']}; goal: {g['goal']}; constraint: {g['constraint']}; "
            f"strategy: {g['strategy']}; benefit: {g['benefit']}; cost: {g['cost']}; dilemma: {g['dilemma']}")


def render_user(record: dict[str, Any], atoms: list[dict[str, Any]], partners: list[dict[str, str]],
                titles: dict[str, dict[str, Any]], vocab: Vocab) -> str:
    """The title's profile and atoms, then each partner (`partner: id; role: r`) and its profile:
    `key: value` lines (compact context, v1.7 §3)."""
    lines = [*render_profile(record, vocab, verification=False), f"atoms: {len(atoms)}", *map(_atom_lines, atoms)]
    for p in partners:
        lines += [f"partner: {p['title_id']}; role: {p['role']}",
                  *render_profile(titles[p["title_id"]], vocab, verification=False)]
    return "\n".join(lines)


def assemble(out: dict[str, Any], atoms: dict[str, dict[str, Any]], prov: dict[str, Any]) -> list[dict[str, Any]]:
    proofs = []
    for p in out.get("proofs") or []:
        atom = atoms.get(p.get("atom_id"))
        test = p.get("explanation_test") or {}
        is_effect = atom is not None and atom["atom_kind"] == "effect"
        proofs.append({
            "atom_id": p.get("atom_id"),
            "contrast": [{k: c.get(k) for k in ("partner_title_id", "partner_role", "partner_has", "difference")}
                         for c in p.get("contrast") or []],
            "explanation_test": ({"favors": test.get("favors"), "via_partner": test.get("via_partner"),
                                  "note": test.get("note")} if is_effect else None),
            "ablation": {k: (p.get("ablation") or {}).get(k) for k in ("if_removed", "verdict", "conf")},
            "provenance": prov,
        })
    return proofs


def output_problems(out: dict[str, Any], atoms: dict[str, dict[str, Any]], partners: list[dict[str, str]],
                    guards: GuardConfig, vocab: Vocab) -> list[str]:
    problems: list[str] = []
    given = [p.get("atom_id") for p in out.get("proofs") or []]
    missing = sorted(set(atoms) - set(given))
    dupes = sorted({a for a in given if given.count(a) > 1})
    if missing:
        problems.append(f"give one proof for every atom; missing {missing[:5]}")
    if dupes:
        problems.append(f"one proof per atom; duplicated {dupes[:5]}")
    roles = {p["title_id"]: p["role"] for p in partners}
    prov = {"run_id": "check", "pass": "P3", "model": None, "prompt_version": None, "schema_version": "0",
            "vocab_version": vocab.version, "cache_key": None, "created_at": "1970-01-01T00:00:00+00:00"}
    for proof in assemble(out, atoms, prov):
        aid = proof["atom_id"]
        seen = [c["partner_title_id"] for c in proof["contrast"]]
        if sorted(seen) != sorted(roles):
            problems.append(f"{aid}: contrast with each partner exactly once ({', '.join(sorted(roles))})")
        for c in proof["contrast"]:
            if roles.get(c["partner_title_id"]) not in (None, c["partner_role"]):
                problems.append(f"{aid}: {c['partner_title_id']} has role {roles[c['partner_title_id']]}")
        test = proof["explanation_test"]
        if test is not None:
            if not test.get("favors") or not (test.get("note") or "").strip():
                problems.append(f"{aid}: effect atoms need an explanation test (favors + note)")
            elif test.get("via_partner") not in roles:
                problems.append(f"{aid}: explanation_test.via_partner must be one of the partners")
        try:
            ProofRecord.model_validate(proof)
        except ValidationError as exc:
            problems += [f"{aid}: {'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in exc.errors()[:4]]
        problems += [f"{aid}: {p}" for p in record_problems(proof, guards)]
    return problems


def run_p3(paths: Paths, title_ids: list[str], client: LLMClient, vocab: Vocab, settings: Settings, *, run_id: str,
           guards: GuardConfig | None = None, created_at: str | None = None) -> StageResult:
    guards = guards or GuardConfig.from_settings(settings)
    prompt = render_prompt(paths)
    client.prompt_version = prompt.version
    titles, outs, corpus = canonical_titles(paths), outcomes(paths), load_corpus(paths)
    alarm = int(settings.p3.get("load_bearing_alarm", 8))
    low = int(settings.p3.get("load_bearing_low_flag", 3))
    result = StageResult()
    for tid in title_ids:
        record = titles.get(tid)
        atom_list = read_candidates(paths, "mechanism", tid)
        if record is None or not atom_list:
            result.skipped.append((tid, "no canonical profile or no P2 atoms yet"))
            continue
        partners = select_partners(record, titles, outs, vocab, corpus.get(tid))
        if not partners:
            result.skipped.append((tid, "no partner title in the corpus yet"))
            continue
        if record["medium"] == "anime" and not any(p["role"] == "cross_medium" for p in partners):
            result.flags.append((tid, "no cross-medium partner available (AC-15)"))
        atoms = {a["atom_id"]: a for a in atom_list}

        def check(out: dict[str, Any], _a: dict = atoms, _p: list = partners) -> None:
            raise_problems(output_problems(out, _a, _p, guards, vocab))

        upstream = upstream_hash([record, *atom_list, *(titles[p["title_id"]] for p in partners), {"partners": partners}])
        call = guarded_call(result, paths, "P3", "proof", tid, client, prompt.system,
                            render_user(record, atom_list, partners, titles, vocab),
                            output_schema(sorted(atoms), partners), upstream=upstream, validate=check)
        if call.stop:
            break
        if call.completion is None:
            continue
        prov = provenance("P3", run_id, call.completion, prompt.version, vocab, created_at)
        proofs = sorted(assemble(call.completion.data, atoms, prov), key=lambda p: p["atom_id"])
        write_candidates(paths, "proof", tid, proofs)
        n_lb = sum(p["ablation"]["verdict"] == "load_bearing" for p in proofs)
        result.done.append(tid)
        result.bump("proofs", len(proofs))
        result.bump("load_bearing", n_lb)
        if not low <= n_lb <= alarm:
            result.flags.append((tid, f"{n_lb} load-bearing atoms (expected {low}-{alarm}): review"))
    return result
