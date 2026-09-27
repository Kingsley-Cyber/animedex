"""P2 WHY (05): from a canonical, verified profile and its moments, write
- effect atoms: element -> feeling -> because, plus the strongest rival explanation;
- engine atoms: agent wants goal but constraint; strategy -> benefit + cost -> dilemma; dramatic question.

Every atom cites evidence (profile field paths or moment ids of this title). New atoms start
`explanation: settled`, `support.status: profile_only`, `origin: p2`. Fewer than
`p2.low_atom_alarm` atoms is flagged for review, not failed.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from animedex.config import Settings
from animedex.content_guards import GuardConfig, record_problems
from animedex.models import MechanismAtom
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import (
    StageResult,
    canonical_titles,
    evidence_targets,
    guarded_call,
    provenance,
    raise_problems,
    render_moments,
    render_profile,
    write_candidates,
)
from animedex.prompts import RenderedPrompt, read_prompt
from animedex.providers.client import LLMClient
from animedex.store.cache import upstream_hash
from animedex.store.jsonl import read_jsonl

ENGINE_KEYS = ("agent", "goal", "constraint", "strategy", "benefit", "cost", "dilemma", "dramatic_question", "feeling")
_WORD = re.compile(r"[a-z0-9']+")
_STOP = {"the", "a", "an", "of", "to", "and", "is", "it", "in", "that", "his", "her", "their", "its", "as", "by", "for"}


def limits(settings: Settings) -> dict[str, int]:
    cfg = settings.p2
    engines = cfg.get("engine_atoms", {})
    return {"max_atoms": int(cfg.get("max_atoms", 15)), "max_effect": int(cfg.get("max_effect_atoms", 12)),
            "engine_min": int(engines.get("min", 1)), "engine_max": int(engines.get("max", 3)),
            "low_alarm": int(cfg.get("low_atom_alarm", 5))}


def render_prompt(paths: Paths, vocab: Vocab, settings: Settings) -> RenderedPrompt:
    main = read_prompt(paths.prompts / "p2_why.md")
    body = main.body
    for key, value in limits(settings).items():
        body = body.replace("{" + key + "}", str(value))
    system = body + "\n\nFeeling values: " + " | ".join(vocab.enum("feeling"))
    return RenderedPrompt(system, main.version)


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}


def output_schema(vocab: Vocab, modules: list[str]) -> dict[str, Any]:
    text, maybe = {"type": "string"}, {"type": ["string", "null"]}
    feeling = {"type": "string", "enum": list(vocab.enum("feeling"))}
    module = {"type": "string", "enum": ["core", *modules]}
    refs = {"type": "array", "items": {"type": "string"}}
    num = {"type": "number"}
    effect = _obj({"element": text, "element_field": maybe, "element_moment_id": maybe, "feeling": feeling,
                   "because": text, "rival_because": text, "module": module, "conf": num, "evidence_refs": refs})
    engine = _obj({**{k: text for k in ENGINE_KEYS if k != "feeling"}, "feeling": feeling, "module": module,
                   "conf": num, "evidence_refs": refs})
    return _obj({"effects": {"type": "array", "items": effect}, "engines": {"type": "array", "items": engine}})


def render_user(record: dict[str, Any], moments: list[dict[str, Any]], vocab: Vocab) -> str:
    return "\n".join(render_profile(record, vocab) + ["", "Moments:", *render_moments(moments)])


def _support() -> dict[str, Any]:
    return {"status": "profile_only", "supporting_episodes": [], "contradicting_episodes": [], "reframing_episodes": []}


def assemble(out: dict[str, Any], title_id: str, prov: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(label for repair messages, atom) pairs: engines first (m.001...), then effects."""
    atoms: list[tuple[str, dict[str, Any]]] = []
    items = [("engines", i, e) for i, e in enumerate(out.get("engines") or [])] + \
            [("effects", i, e) for i, e in enumerate(out.get("effects") or [])]
    for n, (kind, i, a) in enumerate(items, start=1):
        atom: dict[str, Any] = {
            "atom_id": f"{title_id}.m.{n:03d}", "title_id": title_id,
            "atom_kind": "engine" if kind == "engines" else "effect",
            "module": a.get("module"), "epistemic": "interpretive", "conf": float(a.get("conf") or 0),
            "evidence_refs": list(a.get("evidence_refs") or []), "explanation": "settled", "support": _support(),
            "origin": "p2", "provenance": prov,
        }
        if kind == "engines":
            atom["engine"] = {k: a.get(k) for k in ENGINE_KEYS}
        else:
            atom["effect"] = {"element": a.get("element"), "feeling": a.get("feeling"), "because": a.get("because"),
                              "rival_because": a.get("rival_because"),
                              "element_ref": {"field": a.get("element_field"), "moment_id": a.get("element_moment_id")}}
        atoms.append((f"{kind}[{i}]", atom))
    return atoms


def restates(element: str, because: str) -> bool:
    """`because` that mostly repeats the element's words explains nothing (05: circular)."""
    e = {w for w in _WORD.findall(element.lower()) if w not in _STOP}
    b = {w for w in _WORD.findall(because.lower()) if w not in _STOP}
    return bool(b) and len(b - e) <= 1


def output_problems(out: dict[str, Any], record: dict[str, Any], moments: list[dict[str, Any]], vocab: Vocab,
                    lim: dict[str, int], guards: GuardConfig) -> list[str]:
    problems: list[str] = []
    effects, engines = out.get("effects") or [], out.get("engines") or []
    if len(effects) > lim["max_effect"]:
        problems.append(f"at most {lim['max_effect']} effect atoms (got {len(effects)})")
    if not lim["engine_min"] <= len(engines) <= lim["engine_max"]:
        problems.append(f"give {lim['engine_min']}-{lim['engine_max']} engine atoms (got {len(engines)})")
    if len(effects) + len(engines) > lim["max_atoms"]:
        problems.append(f"at most {lim['max_atoms']} atoms in total")
    targets = evidence_targets(record, moments, vocab)
    moment_ids = {m["moment_id"] for m in moments}
    for kind, items in (("effects", effects), ("engines", engines)):
        for i, a in enumerate(items):
            refs = a.get("evidence_refs") or []
            unknown = [r for r in refs if r not in targets]
            if not refs:
                problems.append(f"{kind}[{i}]: cite evidence_refs")
            elif unknown:
                problems.append(f"{kind}[{i}]: evidence_refs {unknown[:3]} are not listed field paths or moment ids")
    for i, e in enumerate(effects):
        field, moment = e.get("element_field"), e.get("element_moment_id")
        if not field and not moment:
            problems.append(f"effects[{i}]: give element_field or element_moment_id")
        if field and field not in targets:
            problems.append(f"effects[{i}].element_field {field!r} is not a listed field path")
        if moment and moment not in moment_ids:
            problems.append(f"effects[{i}].element_moment_id {moment!r} is not a listed moment id")
        if e.get("element") and e.get("because") and restates(str(e["element"]), str(e["because"])):
            problems.append(f"effects[{i}].because restates the element; explain why it produces the feeling")
    prov = {"run_id": "check", "pass": "P2", "model": None, "prompt_version": None, "schema_version": "0",
            "vocab_version": vocab.version, "cache_key": None, "created_at": "1970-01-01T00:00:00+00:00"}
    for label, atom in assemble(out, record["title_id"], prov):
        try:
            MechanismAtom.model_validate(atom)
        except ValidationError as exc:
            problems += [f"{label}.{'.'.join(str(p) for p in err['loc'][1:]) or err['loc'][0]}: {err['msg']}"
                         for err in exc.errors()[:4]]
        problems += [f"{label}: {p}" for p in record_problems(atom, guards)]
    return problems


def run_p2(paths: Paths, title_ids: list[str], client: LLMClient, vocab: Vocab, settings: Settings, *, run_id: str,
           guards: GuardConfig | None = None, created_at: str | None = None) -> StageResult:
    guards = guards or GuardConfig.from_settings(settings)
    prompt = render_prompt(paths, vocab, settings)
    client.prompt_version = prompt.version
    lim = limits(settings)
    titles = canonical_titles(paths)
    moments_by: dict[str, list[dict[str, Any]]] = {}
    for m in read_jsonl(paths.canonical / "moments.jsonl"):
        moments_by.setdefault(m["title_id"], []).append(m)
    result = StageResult()
    for tid in title_ids:
        record = titles.get(tid)
        if record is None:
            result.skipped.append((tid, "no canonical profile; run P1, VERIFY and canonicalize first"))
            continue
        moments = sorted(moments_by.get(tid, []), key=lambda m: m["moment_id"])

        def check(out: dict[str, Any], _r: dict = record, _m: list = moments) -> None:
            raise_problems(output_problems(out, _r, _m, vocab, lim, guards))

        call = guarded_call(result, paths, "P2", "mechanism", tid, client, prompt.system,
                            render_user(record, moments, vocab), output_schema(vocab, record.get("modules_active") or []),
                            upstream=upstream_hash([record, *moments]), validate=check)
        if call.stop:
            break
        if call.completion is None:
            continue
        prov = provenance("P2", run_id, call.completion, prompt.version, vocab, created_at)
        atoms = [a for _, a in assemble(call.completion.data, tid, prov)]
        write_candidates(paths, "mechanism", tid, atoms)
        result.done.append(tid)
        result.bump("atoms", len(atoms))
        result.bump("engine_atoms", sum(a["atom_kind"] == "engine" for a in atoms))
        if len(atoms) < lim["low_alarm"]:
            result.flags.append((tid, f"only {len(atoms)} atoms (fewer than {lim['low_alarm']}): review"))
    return result
