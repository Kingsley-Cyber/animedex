"""CHECK (05): the critic (a different model family: codex_cli) tries to falsify every P2 atom and
P3 proof of a title.

- ACCEPT: kept.
- REVISE: the corrected fields are applied, then the revised targets are re-checked once.
- CONTESTED: the atom's explanation becomes `contested` (in the index, never load-bearing-eligible).
- REJECT: the target moves to quarantine with its reasons. A rejected atom takes its proof along.
- NEEDS_ADJUDICATION: kept, queued for Kingsley in data/adjudication/, not eligible, never blocking.
If a proof's explanation test favors the rival, the critic must REVISE the atom to the rival
explanation or return CONTESTED (05).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from pydantic import ValidationError

from animedex.config import Settings
from animedex.content_guards import GuardConfig, record_problems
from animedex.models import CheckRecord, MechanismAtom, ProofRecord
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import (
    StageResult,
    canonical_titles,
    guarded_call,
    provenance,
    raise_problems,
    read_candidates,
    render_profile,
    write_candidates,
)
from animedex.pipeline.p3 import ABLATION, FAVORS
from animedex.prompts import RenderedPrompt, read_prompt
from animedex.providers.client import LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.cache import upstream_hash
from animedex.store.quarantine import quarantine

VERDICTS = ["ACCEPT", "REVISE", "REJECT", "CONTESTED", "NEEDS_ADJUDICATION"]
REASONS = ["unsupported", "overreach", "merged_claims", "off_vocab", "contradiction", "circular", "granularity",
           "scope_leak"]
EFFECT_KEYS = ("element", "feeling", "because", "rival_because")
ENGINE_KEYS = ("goal", "constraint", "strategy", "benefit", "cost", "dilemma", "dramatic_question")
PROOF_KEYS = ("ablation_verdict", "favors")


def render_prompt(paths: Paths) -> RenderedPrompt:
    main = read_prompt(paths.prompts / "check.md")
    return RenderedPrompt(main.body, main.version)


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def output_schema(vocab: Vocab, atom_ids: list[str]) -> dict[str, Any]:
    maybe = {"type": ["string", "null"]}
    revision = _obj({**{k: maybe for k in (*EFFECT_KEYS, *ENGINE_KEYS) if k != "feeling"},
                     "feeling": {"type": ["string", "null"], "enum": [*vocab.enum("feeling"), None]},
                     "ablation_verdict": {"type": ["string", "null"], "enum": [*ABLATION, None]},
                     "favors": {"type": ["string", "null"], "enum": [*FAVORS, None]}})
    verdict = _obj({"target_id": {"type": "string", "enum": atom_ids},
                    "target_type": {"type": "string", "enum": ["mechanism", "proof"]},
                    "verdict": {"type": "string", "enum": VERDICTS},
                    "reasons": {"type": "array", "items": {"type": "string", "enum": REASONS}},
                    "revision": revision, "note": maybe})
    return _obj({"verdicts": {"type": "array", "items": verdict}})


def _atom_text(a: dict[str, Any]) -> str:
    refs = ", ".join(a["evidence_refs"])
    if a["atom_kind"] == "effect":
        e = a["effect"]
        return (f"{a['atom_id']}: mechanism; kind: effect; module: {a['module']}; element: {e['element']}; "
                f"feeling: {e['feeling']}; because: {e['because']}; rival_because: {e['rival_because']}; "
                f"evidence: {refs}")
    g = a["engine"]
    return (f"{a['atom_id']}: mechanism; kind: engine; module: {a['module']}; agent: {g['agent']}; goal: {g['goal']}; "
            f"constraint: {g['constraint']}; strategy: {g['strategy']}; benefit: {g['benefit']}; cost: {g['cost']}; "
            f"dilemma: {g['dilemma']}; dramatic_question: {g['dramatic_question']}; evidence: {refs}")


def _proof_text(p: dict[str, Any]) -> str:
    parts = [f"{c['partner_title_id']} ({c['partner_role']}) has {c['partner_has']}, {c['difference']}"
             for c in p["contrast"]]
    test = p.get("explanation_test")
    t = f"; explanation_test: favors {test['favors']} via {test['via_partner']}, {test['note']}" if test else ""
    ab = p["ablation"]
    return (f"{p['atom_id']}: proof; contrast: {' | '.join(parts)}{t}; ablation: {ab['verdict']} "
            f"(conf {ab['conf']}), {ab['if_removed']}")


def render_user(record: dict[str, Any], atoms: list[dict[str, Any]], proofs: list[dict[str, Any]], vocab: Vocab) -> str:
    """The verified profile, then `atoms: N` and `proofs: N` groups: `key: value` lines (compact context,
    v1.7 §3). A proof has its atom's id."""
    return "\n".join([*render_profile(record, vocab), f"atoms: {len(atoms)}", *map(_atom_text, atoms),
                      f"proofs: {len(proofs)}", *map(_proof_text, proofs)])


def _revised_atom(atom: dict[str, Any], rev: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(atom))
    keys = EFFECT_KEYS if atom["atom_kind"] == "effect" else ENGINE_KEYS
    body = out["effect"] if atom["atom_kind"] == "effect" else out["engine"]
    for k in keys:
        if rev.get(k):
            body[k] = rev[k]
    return out


def _revised_proof(proof: dict[str, Any], rev: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(proof))
    if rev.get("ablation_verdict"):
        out["ablation"]["verdict"] = rev["ablation_verdict"]
    if rev.get("favors") and out.get("explanation_test"):
        out["explanation_test"]["favors"] = rev["favors"]
    return out


def _relevant(rev: dict[str, Any] | None, target_type: str, kind: str) -> dict[str, Any]:
    keys = PROOF_KEYS if target_type == "proof" else (EFFECT_KEYS if kind == "effect" else ENGINE_KEYS)
    return {k: (rev or {}).get(k) for k in keys if (rev or {}).get(k) not in (None, "")}


def output_problems(out: dict[str, Any], atoms: dict[str, dict[str, Any]], proofs: dict[str, dict[str, Any]],
                    guards: GuardConfig) -> list[str]:
    problems: list[str] = []
    want = {(a, "mechanism") for a in atoms} | {(a, "proof") for a in proofs}
    got = [(v.get("target_id"), v.get("target_type")) for v in out.get("verdicts") or []]
    missing = sorted(want - set(got))
    if missing:
        problems.append(f"give one verdict per atom and per proof; missing {[f'{a} {t}' for a, t in missing[:6]]}")
    dupes = sorted({g for g in got if got.count(g) > 1})
    if dupes:
        problems.append(f"one verdict per target; duplicated {[f'{a} {t}' for a, t in dupes[:6]]}")
    verdict_of = {(v.get("target_id"), v.get("target_type")): v for v in out.get("verdicts") or []}
    for (aid, ttype), v in verdict_of.items():
        if (aid, ttype) not in want:
            problems.append(f"{aid} {ttype}: no such target")
            continue
        verdict, reasons = v.get("verdict"), v.get("reasons") or []
        if verdict != "ACCEPT" and not reasons:
            problems.append(f"{aid} {ttype}: {verdict} needs at least one reason")
        if verdict == "REVISE":
            rev = _relevant(v.get("revision"), ttype, atoms[aid]["atom_kind"])
            if not rev:
                problems.append(f"{aid} {ttype}: REVISE must fill the corrected {ttype} fields in revision")
            elif ttype == "mechanism":
                try:
                    MechanismAtom.model_validate(_revised_atom(atoms[aid], rev))
                except ValidationError as exc:
                    problems += [f"{aid} revision: {err['loc'][-1]}: {err['msg']}" for err in exc.errors()[:3]]
                problems += [f"{aid} revision: {p}" for p in record_problems(rev, guards)]
            else:
                try:
                    ProofRecord.model_validate(_revised_proof(proofs[aid], rev))
                except ValidationError as exc:
                    problems += [f"{aid} proof revision: {err['msg']}" for err in exc.errors()[:3]]
    for aid, proof in proofs.items():
        test = proof.get("explanation_test") or {}
        mech = verdict_of.get((aid, "mechanism"))
        if test.get("favors") == "rival" and mech and mech.get("verdict") == "ACCEPT":
            problems.append(f"{aid}: its explanation test favors the rival; REVISE to the rival explanation or CONTESTED")
    return problems


def _later(created_at: str | None, seconds: int) -> str | None:
    if created_at is None:
        return None
    return (datetime.fromisoformat(created_at) + timedelta(seconds=seconds)).isoformat()


def run_check(paths: Paths, title_ids: list[str], client: LLMClient, vocab: Vocab, settings: Settings, *, run_id: str,
              guards: GuardConfig | None = None, created_at: str | None = None) -> StageResult:
    guards = guards or GuardConfig.from_settings(settings)
    prompt = render_prompt(paths)
    client.prompt_version = prompt.version
    titles = canonical_titles(paths)
    result = StageResult()
    for tid in title_ids:
        record = titles.get(tid)
        atom_list, proof_list = read_candidates(paths, "mechanism", tid), read_candidates(paths, "proof", tid)
        if record is None or not atom_list or not proof_list:
            result.skipped.append((tid, "needs a canonical profile plus P2 atoms and P3 proofs"))
            continue
        atoms = {a["atom_id"]: a for a in atom_list}
        proofs = {p["atom_id"]: p for p in proof_list if p["atom_id"] in atoms}
        checks: list[dict[str, Any]] = []
        targets_atoms, targets_proofs = dict(atoms), dict(proofs)
        stop = False
        for round_no in (0, 1):  # the second round re-checks revised targets once
            if not targets_atoms and not targets_proofs:
                break

            def validate(out: dict[str, Any], _a: dict = targets_atoms, _p: dict = targets_proofs) -> None:
                raise_problems(output_problems(out, _a, _p, guards))

            ids = sorted(set(targets_atoms) | set(targets_proofs))
            call = guarded_call(result, paths, "CHECK", "check", tid, client, prompt.system,
                                render_user(record, [atoms[a] for a in sorted(targets_atoms)],
                                            [proofs[a] for a in sorted(targets_proofs)], vocab),
                                output_schema(vocab, ids),
                                upstream=upstream_hash([record, *targets_atoms.values(), *targets_proofs.values()]),
                                validate=validate, record_id=tid if round_no == 0 else f"{tid}.recheck")
            if call.stop:
                stop = True
                break
            if call.completion is None:
                break
            prov = provenance("CHECK", run_id, call.completion, prompt.version, vocab, _later(created_at, round_no))
            revised_atoms: dict[str, dict[str, Any]] = {}
            revised_proofs: dict[str, dict[str, Any]] = {}
            for v in sorted(call.completion.data["verdicts"], key=lambda v: (v["target_id"], v["target_type"])):
                aid, ttype, verdict = v["target_id"], v["target_type"], v["verdict"]
                if aid not in atoms:  # rejected earlier in this call
                    continue
                rev = _relevant(v.get("revision"), ttype, atoms[aid]["atom_kind"]) if verdict == "REVISE" else None
                result.bump(f"{ttype}_{verdict.lower()}")
                if verdict == "REJECT":
                    what = atoms[aid] if ttype == "mechanism" else proofs.get(aid)
                    quarantine(paths.quarantine, "CHECK", ttype, aid, what, [f"REJECT: {', '.join(v['reasons'])}"])
                    if ttype == "mechanism":
                        atoms.pop(aid, None)
                        proofs.pop(aid, None)
                        checks = [c for c in checks if c["target_id"] != aid]
                    else:
                        proofs.pop(aid, None)
                        checks = [c for c in checks if not (c["target_id"] == aid and c["target_type"] == "proof")]
                    continue
                if verdict == "REVISE" and rev:
                    if ttype == "mechanism":
                        atoms[aid] = _revised_atom(atoms[aid], rev)
                        revised_atoms[aid] = atoms[aid]
                    elif aid in proofs:
                        proofs[aid] = _revised_proof(proofs[aid], rev)
                        revised_proofs[aid] = proofs[aid]
                if verdict == "CONTESTED":
                    atoms[aid]["explanation"] = "contested"
                if verdict == "NEEDS_ADJUDICATION":
                    result.flags.append((tid, f"{aid} {ttype} needs adjudication"))
                checks.append({"target_id": aid, "target_type": ttype, "verdict": verdict,
                               "reasons": list(v.get("reasons") or []), "revision": rev, "provenance": prov})
            targets_atoms = {a: atoms[a] for a in revised_atoms if a in atoms}
            targets_proofs = {a: proofs[a] for a in revised_proofs if a in proofs}
            if round_no == 0:
                # a revised atom's proof is re-checked with it; a revised proof's atom stays as it is
                for a in list(targets_atoms):
                    if a in proofs:
                        targets_proofs.setdefault(a, proofs[a])
        if stop:
            break
        if not checks:
            continue
        for c in checks:
            CheckRecord.model_validate(c)
        write_candidates(paths, "mechanism", tid, [atoms[a] for a in sorted(atoms)])
        write_candidates(paths, "proof", tid, [proofs[a] for a in sorted(proofs)])
        write_candidates(paths, "check", tid, checks)
        adjudicate = [c for c in checks if c["verdict"] == "NEEDS_ADJUDICATION"]
        if adjudicate:
            atomic_write_text(paths.root / "data" / "adjudication" / f"{tid}.json",
                              json.dumps(adjudicate, indent=2, sort_keys=True) + "\n")
        result.done.append(tid)
        result.bump("checks", len(checks))
    return result
