"""P1 WHAT (05): one title per call -> title profile + 3-5 moments + verify list, as candidates.

Only events inside the title's scope. The verify list is recomputed in code from `conf` and
`verify.always_verify` (the model's list is advisory), so AC-10 holds whatever the model says.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from animedex import SCHEMA_VERSION
from animedex.activation import violations as activation_violations
from animedex.budget import BudgetExceeded
from animedex.config import Settings
from animedex.content_guards import GuardConfig, dialogue_problems, framing_problems, quote_problems
from animedex.guards import LiveRunRefused
from animedex.integrity import proper_nouns
from animedex.models import CorpusEntry, Moment, title_profile_model
from animedex.ontology import LensField, Vocab
from animedex.paths import Paths
from animedex.pipeline.common import supersede
from animedex.pipeline.lens_values import ENUM_HINT, describe, phrase_texts, shape_problems
from animedex.prompts import RenderedPrompt, read_prompt
from animedex.providers.base import ProviderError, Usage
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, Completion, InvalidOutput, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.cache import upstream_hash
from animedex.store.canonical import normalize_record
from animedex.store.jsonl import dumps_jsonl, read_jsonl
from animedex.store.quarantine import quarantine
from animedex.textutil import medium_words, word_count

EPISTEMIC = ["observed", "derived", "interpretive"]
MOMENTS = (3, 5)


# ---------------------------------------------------------------- prompt
def enum_lines(vocab: Vocab) -> list[str]:
    """Every enum the lens asks for (list and group parts included), each value's discrimination test
    under it where the vocab has one (grid reliability ruling: the tests live in vocab.json only)."""
    lines: list[str] = []
    tested: dict[str, str] = {}
    for f in vocab.lens_fields():
        for sub, vf in f.enum_vocabs():
            label = f"{f.path}{sub}" + (" (one or more)" if f.kind == "enum_multi" else "")
            if vf in tested:
                lines.append(f"- {label}: the values and tests of {tested[vf]}")
                continue
            lines.append(f"- {label}: {' | '.join(vocab.enum(vf))}")
            tests = vocab.tests(vf)
            if tests:
                tested[vf] = f"{f.path}{sub}"
                lines.append("  Tests (choose the value whose test holds):")
                lines += [f"  - {v}: {tests[v]}" for v in vocab.enum(vf) if v in tests]
    return lines


def render_prompt(paths: Paths, vocab: Vocab, settings: Settings) -> RenderedPrompt:
    main = read_prompt(paths.prompts / "p1_what.md")
    blocks = ["core", *vocab.module_names]
    fragments = [read_prompt(paths.prompts / "p1_modules" / f"{b}.md").body for b in blocks]
    example = read_prompt(paths.prompts / "p1_example.md").body
    enums = enum_lines(vocab)
    enums.append(f"- moments[].moment_type: {' | '.join(vocab.enum('moment_type'))}")
    threshold = str(settings.verify.get("conf_threshold", 0.7))
    system = "\n".join([
        main.body.replace("{conf_threshold}", threshold),
        "Modules and fields",
        *fragments,
        "Enum values",
        *enums,
        "",
        example,
    ])
    return RenderedPrompt(system, main.version)


def render_user(entry: CorpusEntry) -> str:
    scope = entry.scope
    seasons = ", ".join(str(s) for s in scope.seasons) or "none (film)"
    exclude = "; ".join(scope.exclude) or "nothing listed"
    return (
        f"Title: {entry.title} ({entry.year})\n"
        f"Medium: {entry.medium}\nFormat: {entry.format}\n"
        f"Scope: version = {scope.version}; seasons = {seasons}; numbering = {scope.numbering or 'n/a'}\n"
        f"Out of scope: {exclude}\n"
        "Profile this title inside the scope."
    )


# ---------------------------------------------------------------- output schema (for the model)
NOTE_MAX_WORDS = 15  # condition and uncertainty_reason (04; vocab 1.4.0 caps, owner-approved)


def _value_schema(f: LensField, vocab: Vocab) -> dict[str, Any]:
    """The draft shape of a value by kind (vocab 1.5.0). Enum members stay free strings so the model can
    write other:<phrase>; item limits are in the description and checked in code."""
    description = describe(f, vocab, values=False)
    if f.kind in ("phrase", "enum"):
        return {"type": ["string", "null"], "description": description}
    if f.kind == "enum_multi":
        return {"type": ["array", "null"], "items": {"type": "string"}, "description": description}
    parts = {p.name: {"type": "string" if f.kind == "list" else ["string", "null"],
                      "description": f"{p.max_words} words or fewer" if p.kind == "phrase" else "a listed value"}
             for p in f.parts}
    obj = {"type": "object", "properties": parts, "required": list(parts), "additionalProperties": False}
    if f.kind == "list":
        return {"type": ["array", "null"], "items": obj, "description": description}
    return {**obj, "type": ["object", "null"], "description": description}


def _field_schema(f: LensField, vocab: Vocab) -> dict[str, Any]:
    props: dict[str, Any] = {
        "value": _value_schema(f, vocab),
        "conf": {"type": "number"},
        "uncertainty_reason": {"type": ["string", "null"], "description": f"{NOTE_MAX_WORDS} words or fewer"},
        "epistemic": {"type": "string", "enum": EPISTEMIC},
    }
    if f.conditional:
        props["condition"] = {"type": ["string", "null"], "description": f"{NOTE_MAX_WORDS} words or fewer"}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def module_rules(vocab: Vocab, medium: str, fmt: str) -> tuple[set[str], set[str]]:
    """(allowed, required) modules for a medium/format. Rule clauses on medium/format are decided
    here; a clause on another module (sensory <- power_combat) leaves the module allowed, and
    judgment modules are always allowed. Nothing else may appear in a P1 draft."""
    allowed, required = set(), set()
    for module, spec in vocab.module_activation.items():
        if spec["kind"] != "rule":
            allowed.add(module)
            continue
        for clause in spec["any"]:
            if "module" in clause:
                allowed.add(module)
                continue
            value = medium if clause["field"] == "medium" else fmt
            if (value in clause["in"]) if "in" in clause else (value not in clause["not_in"]):
                allowed.add(module)
                required.add(module)
    return allowed, required


def _all_null(block: Any) -> bool:
    return isinstance(block, dict) and all(isinstance(fv, dict) and fv.get("value") is None for fv in block.values())


UNKNOWN_REASON = "no reliable recall"
NO_SECONDARY = "no second value as strong as the first"
OUTCOME_BOUND = "only for {outcomes} titles"


def _unset(fv: dict[str, Any], reason: str) -> None:
    fv.update(value=None, conf=0, uncertainty_reason=reason)


def _normalize_kinds(d: dict[str, Any], vocab: Vocab) -> None:
    """vocab 1.5.0 kinds: an empty multi-value list or an all-null group is unknown; a secondary equal
    to its primary (or without one) adds nothing; an outcome-bound field on another outcome is cleared."""
    outcome = ((d.get("core") or {}).get("outcome") or {}).get("value")
    for block in ["core", *d["modules_active"]]:
        body = d.get(block) or {}
        for f in vocab.block_fields(block):
            fv = body.get(f.name)
            if not isinstance(fv, dict) or fv.get("value") is None:
                continue
            value = fv["value"]
            if (f.kind == "enum_multi" and value == []) or (
                    f.kind == "group" and isinstance(value, dict) and all(v is None for v in value.values())):
                fv["value"] = None
            elif f.differs_from:
                primary = (body.get(f.differs_from) or {}).get("value")
                if primary is None or primary == value:
                    _unset(fv, NO_SECONDARY)
            elif f.outcome_in and outcome not in f.outcome_in:
                _unset(fv, OUTCOME_BOUND.format(outcomes=" or ".join(f.outcome_in)))


def normalize_draft(draft: dict[str, Any], entry: CorpusEntry, vocab: Vocab) -> dict[str, Any]:
    """Deterministic clean-up before the checks (P1 1.1.0), so the one repair is spent on real errors:
    - module blocks the rules forbid for this medium/format are dropped;
    - a module that is not rule-required and whose every field is null is dropped (it does not apply);
    - sensory outside animation stays only if power_combat does (activation rule);
    - `modules_active` is derived from the blocks that remain, never taken from the model;
    - vocab 1.5.0 kinds: see `_normalize_kinds`;
    - a null field is unknown: its conf becomes 0, and without a reason it gets 'no reliable recall'.
    A non-null guess below the confidence floor without a reason is left for the checks to reject."""
    d = {k: v for k, v in draft.items()}
    allowed, required = module_rules(vocab, entry.medium, entry.format)
    for m in vocab.module_names:
        if d.get(m) is None:
            d.pop(m, None)
        elif m not in allowed or (m not in required and _all_null(d[m])):
            d.pop(m)
    active = {m for m in vocab.module_names if isinstance(d.get(m), dict)}
    if "sensory" in active and "sensory" not in required and "power_combat" not in active:
        d.pop("sensory")
        active.discard("sensory")
    d["modules_active"] = [m for m in vocab.module_names if m in active]
    _normalize_kinds(d, vocab)
    for block in ["core", *d["modules_active"]]:
        for fv in (d.get(block) or {}).values():
            if not isinstance(fv, dict) or fv.get("value") is not None:
                continue
            fv["conf"] = 0  # a null value is unknown; confidence in an unknown value means nothing
            if not (fv.get("uncertainty_reason") or "").strip():
                fv["uncertainty_reason"] = UNKNOWN_REASON
    return d


def output_schema(vocab: Vocab, entry: CorpusEntry | None = None) -> dict[str, Any]:
    """Per title (P1 1.1.0): only the modules the activation rules allow are offered, rule-required
    ones are required, and `modules_active` is derived afterwards (normalize_draft)."""
    def block(name: str) -> dict[str, Any]:
        fields = vocab.block_fields(name)
        return {"type": "object", "properties": {f.name: _field_schema(f, vocab) for f in fields},
                "required": [f.name for f in fields], "additionalProperties": False}

    moment = {"type": "object", "additionalProperties": False, "properties": {
        "description": {"type": "string"}, "season": {"type": ["integer", "null"]},
        "episode": {"type": ["integer", "null"]}, "timestamp": {"type": ["string", "null"]},
        "moment_type": {"type": "string"}, "why_it_hit": {"type": "string"}, "conf": {"type": "number"}}}
    moment["required"] = list(moment["properties"])
    allowed, required = (module_rules(vocab, entry.medium, entry.format) if entry is not None
                         else (set(vocab.module_names), set()))
    modules = [m for m in vocab.module_names if m in allowed]
    props: dict[str, Any] = {
        "core": block("core"),
        **{m: block(m) for m in modules},
        "moments": {"type": "array", "items": moment},
        "verify": {"type": "array", "items": {"type": "string"}},
    }
    return {"type": "object", "properties": props,
            "required": ["core", *[m for m in modules if m in required], "moments", "verify"],
            "additionalProperties": False}


# ---------------------------------------------------------------- draft checks (drive the one repair)
def _enum_ok(vocab: Vocab, vocab_field: str, value: str) -> bool:
    return value in vocab.enum(vocab_field) or (value.lower().startswith("other:") and bool(value[6:].strip()))


def value_problems(f: LensField, value: Any, vocab: Vocab, guards: GuardConfig, title: str) -> list[str]:
    """What is wrong with a non-null draft value: shape and enum problems (vocab 1.5.0 kinds), word caps
    (each phrase its own; tagged for the length-only repair), quotes and dialogue, framing claims in
    sensory fields, and names or medium words in an abstract phrase."""
    problems = []
    for sub, msg in shape_problems(f, value, vocab):
        problems.append(f"{f.path}={value!r}: {ENUM_HINT}" if (sub, f.kind) == ("", "enum") and ENUM_HINT in msg
                        else f"{f.path}{sub}: {msg}")
    for sub, text, cap in phrase_texts(f, value):
        where = f"{f.path}{sub}"
        if word_count(text) > (cap or NOTE_MAX_WORDS):
            problems.append(f"{where}: has {word_count(text)} words; {LENGTH_TAG} {cap} or fewer")
        problems += [f"{where}: {p}" for p in quote_problems(text, guards.min_quote_words) + dialogue_problems(text)]
        if f.block == "sensory":
            problems += [f"{where}: {p}" for p in framing_problems(text, guards.framing_terms)]
        if f.abstract:
            if found := medium_words(text):
                problems.append(f"{where}: no medium words ({', '.join(found)})")
            if title and title.lower() in text.lower():
                problems.append(f"{where}: no names (it names the title)")
            if found := proper_nouns(text):
                problems.append(f"{where}: no names ({', '.join(found)})")
    return problems


def draft_problems(draft: dict[str, Any], entry: CorpusEntry, vocab: Vocab, threshold: float,
                   guards: GuardConfig) -> list[str]:
    problems: list[str] = []
    active = draft.get("modules_active") or []
    unknown = [m for m in active if m not in vocab.module_names]
    problems += [f"unknown module {m}" for m in unknown]
    problems += activation_violations(vocab, entry.medium, entry.format, [m for m in active if m not in unknown])
    for m in vocab.module_names:
        if m in active and not isinstance(draft.get(m), dict):
            problems.append(f"active module {m} is missing")
        if m not in active and draft.get(m) is not None:
            problems.append(f"module {m} is present but not active; omit it")
    for block in ["core", *[m for m in active if m in vocab.module_names]]:
        body = draft.get(block) or {}
        for f in vocab.block_fields(block):
            fv = body.get(f.name)
            if not isinstance(fv, dict):
                problems.append(f"{f.path} is missing")
                continue
            value, conf = fv.get("value"), fv.get("conf")
            if not isinstance(conf, (int, float)) or not 0 <= conf <= 1:
                problems.append(f"{f.path}.conf must be 0-1")
                continue
            if value is None and conf != 0:
                problems.append(f"{f.path}: unknown value must carry conf 0")
            if value is not None:
                problems += value_problems(f, value, vocab, guards, entry.title)
            if f.conditional and value is not None and not (fv.get("condition") or "").strip():
                problems.append(f"{f.path}: needs a condition")
            if conf < threshold and not (fv.get("uncertainty_reason") or "").strip():
                problems.append(f"{f.path}: conf < {threshold} needs an uncertainty_reason")
            for key in ("uncertainty_reason", "condition"):
                if isinstance(fv.get(key), str) and word_count(fv[key]) > NOTE_MAX_WORDS:
                    problems.append(f"{f.path}.{key}: has {word_count(fv[key])} words; "
                                    f"{LENGTH_TAG} {NOTE_MAX_WORDS} or fewer")
    moments = draft.get("moments") or []
    if not MOMENTS[0] <= len(moments) <= MOMENTS[1]:
        problems.append(f"give {MOMENTS[0]}-{MOMENTS[1]} moments (got {len(moments)})")
    for i, mo in enumerate(moments):
        for key in ("description", "why_it_hit"):
            text = str(mo.get(key) or "")
            if not text.strip() or word_count(text) > 25:
                problems.append(f"moments[{i}].{key}: 1-25 words")
            problems += [f"moments[{i}].{key}: {p}" for p in quote_problems(text, guards.min_quote_words) + dialogue_problems(text)]
        if not _enum_ok(vocab, "moment_type", str(mo.get("moment_type") or "")):
            problems.append(f"moments[{i}].moment_type: use a listed value or other:<phrase>")
    return problems


# ---------------------------------------------------------------- assembly
def verify_list(record: dict[str, Any], moment_ids: list[str], vocab: Vocab, settings: Settings,
                advisory: list[str]) -> list[str]:
    threshold = float(settings.verify.get("conf_threshold", 0.7))
    patterns = list(settings.verify.get("always_verify", []))
    active = [f for f in vocab.lens_fields() if f.block == "core" or f.block in record["modules_active"]]
    active_paths = [f.path for f in active]
    candidates = set(active_paths) | {f"moments.{m}.locator" for m in moment_ids}
    out = {p for p in active_paths if record[p.split(".")[0]][p.split(".")[1]]["conf"] < threshold}
    # a value that needs a cited source is always checked (vocab 1.5.0: promise_break)
    out |= {f.path for f in active if f.needs_source and record[f.block][f.name]["value"] is not None}
    for pattern in patterns:
        out |= {c for c in candidates if fnmatch.fnmatchcase(c, pattern)}
    out |= {a for a in advisory if a in candidates}
    return sorted(out)


def assemble(draft: dict[str, Any], entry: CorpusEntry, vocab: Vocab, settings: Settings, *, run_id: str,
             prompt_version: str, completion: Completion, created_at: str | None = None
             ) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    created_at = created_at or datetime.now(UTC).isoformat()
    prov = {"run_id": run_id, "pass": "P1", "model": completion.provenance_model, "prompt_version": prompt_version,
            "schema_version": SCHEMA_VERSION, "vocab_version": vocab.version, "cache_key": completion.cache_key,
            "created_at": created_at}
    active = list(draft["modules_active"])
    record: dict[str, Any] = {
        "title_id": entry.title_id, "title": entry.title, "year": entry.year, "medium": entry.medium,
        "format": entry.format, "scope": entry.scope.model_dump(mode="json"), "role_tags": list(entry.role_tags),
        "modules_active": active, "provenance": prov,
    }
    for block in ["core", *active]:
        record[block] = {}
        for f in vocab.block_fields(block):
            fv = draft[block][f.name]
            out = {"value": json.loads(json.dumps(fv.get("value"))), "conf": float(fv.get("conf", 0)),
                   "uncertainty_reason": fv.get("uncertainty_reason") or None, "source": "recall",
                   "verification": "not_required", "source_ref": None,
                   "epistemic": "external_metric" if f.path == "core.outcome" else fv.get("epistemic", "interpretive")}
            if f.conditional:
                out["condition"] = fv.get("condition") or None
            record[block][f.name] = out
    moments = []
    for i, mo in enumerate(draft["moments"], start=1):
        moments.append({
            "moment_id": f"{entry.title_id}.mo.{i:02d}", "title_id": entry.title_id,
            "description": mo["description"], "why_it_hit": mo["why_it_hit"], "moment_type": mo["moment_type"],
            "locator": {"season": mo.get("season"), "episode": mo.get("episode"), "timestamp": mo.get("timestamp"),
                        "episode_id": None},
            "conf": float(mo.get("conf", 0)), "verification": "unverified", "source_ref": None, "provenance": prov,
        })
    to_verify = verify_list(record, [m["moment_id"] for m in moments], vocab, settings, list(draft.get("verify") or []))
    for path in to_verify:
        if not path.startswith("moments."):
            block, name = path.split(".")
            record[block][name]["verification"] = "unverified"
    return record, moments, to_verify


# ---------------------------------------------------------------- stage
@dataclass
class P1Result:
    titles: list[dict[str, Any]] = field(default_factory=list)
    moments: list[dict[str, Any]] = field(default_factory=list)
    quarantined: list[tuple[str, str]] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    substituted: list[tuple[str, str]] = field(default_factory=list)
    stopped: str | None = None


LENGTH_TAG = "rewrite it in"
SHORTEN_SYSTEM = ("You shorten phrases. Rewrite each listed phrase within the word limit shown after it, keeping its "
                  "meaning and facts and dropping filler words. Paraphrase only; no quotes. Output JSON only.")
_LIMIT = re.compile(r"rewrite it in (\d+) or fewer")


def _is_length(problem: str) -> bool:
    return LENGTH_TAG in problem


NOTE_KEYS = ("condition", "uncertainty_reason")


def _field_ref(draft: dict[str, Any], path: str) -> tuple[Any, Any] | None:
    """(container, key) of the text a problem path names: `core.tone` (the value), `core.flaw.condition`,
    `core.thematic_argument.resolution` (a group part), `core.institutions.0.role` (a list item part)."""
    parts = path.split(".")
    if len(parts) < 2 or not isinstance((draft.get(parts[0]) or {}).get(parts[1]), dict):
        return None
    fv = draft[parts[0]][parts[1]]
    rest, value = parts[2:], fv.get("value")
    if not rest:
        return fv, "value"
    if len(rest) == 1 and rest[0] in NOTE_KEYS:
        return fv, rest[0]
    if len(rest) == 1 and isinstance(value, dict) and rest[0] in value:
        return value, rest[0]
    if len(rest) == 2 and rest[0].isdigit() and isinstance(value, list) and int(rest[0]) < len(value) \
            and isinstance(value[int(rest[0])], dict):
        return value[int(rest[0])], rest[1]
    return None


def shorten_phrases(client: LLMClient, entry: CorpusEntry, draft: dict[str, Any], problems: list[str],
                    params: dict[str, Any] | None) -> dict[str, Any]:
    """Length-only repair (P1 1.2.0): rewrite just the over-long phrases, keep everything else. Each
    phrase keeps its own word cap (vocab 1.4.0); nothing is truncated."""
    targets, caps = [], {}
    for prob in problems:
        path = prob.split(":")[0].strip()
        ref = _field_ref(draft, path)
        limit = _LIMIT.search(prob)
        if ref and isinstance(ref[0].get(ref[1]), str) and limit:
            targets.append((path, ref[0][ref[1]]))
            caps[path] = int(limit.group(1))
    paths_ = [t[0] for t in targets]
    item = {"type": "object", "additionalProperties": False, "required": ["path", "text"],
            "properties": {"path": {"type": "string", "enum": paths_}, "text": {"type": "string"}}}
    schema = {"type": "object", "additionalProperties": False, "required": ["items"],
              "properties": {"items": {"type": "array", "items": item}}}

    def check(out: dict[str, Any]) -> None:
        got = {i.get("path"): i.get("text") or "" for i in out.get("items") or []}
        bad = [f"{p}: missing" for p in paths_ if p not in got]
        bad += [f"{p}: has {word_count(t)} words; {caps.get(p, NOTE_MAX_WORDS)} or fewer" for p, t in got.items()
                if word_count(t) > caps.get(p, NOTE_MAX_WORDS) or not t.strip()]
        if bad:
            raise ValueError("; ".join(bad))

    ctx = CallContext(pass_="P1", record_id=f"{entry.title_id}.shorten", title_id=entry.title_id,
                      upstream=upstream_hash([{"shorten": targets}]))
    done = client.complete_ex(SHORTEN_SYSTEM, "\n".join(f"- {p}: {t} [max {caps[p]} words]" for p, t in targets),
                              schema, params, ctx=ctx,
                              validate=check)
    out = json.loads(json.dumps(draft))
    for i in done.data["items"]:
        fv, key = _field_ref(out, i["path"])
        fv[key] = i["text"]
    return out


def stored_draft(paths: Paths, client: LLMClient, title_id: str) -> tuple[Completion | None, dict[str, Any], str]:
    """Replay: the P1 draft behind a title's current candidate, read from the response cache (no call),
    with the provenance of the run that produced it. Returns (None, {}, why) when it is not there."""
    title_file = paths.candidates / "title" / f"{title_id}.jsonl"
    if not title_file.is_file():
        return None, {}, "no P1 candidate to replay"
    [record] = read_jsonl(title_file)
    prov = record.get("provenance") or {}
    key = str(prov.get("cache_key") or "")
    hit = client.cache.get("P1", key) if prov.get("pass") == "P1" and key else None
    if hit is None:
        return None, {}, "its stored draft is not in the response cache"
    return (Completion(hit["json"], Usage(), hit.get("model", ""), key, True, False,
                       hit.get("identity", client.identity), hit.get("meta") or {}), prov, "")


def run_p1(paths: Paths, entries: list[CorpusEntry], client: LLMClient, vocab: Vocab, settings: Settings,
           *, run_id: str, guards: GuardConfig | None = None, created_at: str | None = None,
           params: dict[str, Any] | None = None, agreement_dir: Path | None = None, replay: bool = False) -> P1Result:
    """`agreement_dir` + `params={"rerun": n}`: a second, independent run for AC-12, written to
    eval/agreement instead of candidates (the extra param changes the cache key).
    `replay`: rebuild each title's candidates from the stored draft behind its current candidate, with
    that run's provenance and no model call (resets a title before a fresh VERIFY)."""
    guards = guards or GuardConfig.from_settings(settings)
    prompt = render_prompt(paths, vocab, settings)
    client.prompt_version = prompt.version  # cache keys follow the rendered prompt
    threshold = float(settings.verify.get("conf_threshold", 0.7))
    title_model = title_profile_model(vocab)
    result = P1Result()
    for entry in entries:
        tid = entry.title_id

        schema = output_schema(vocab, entry)

        def check(draft: dict[str, Any], _entry: CorpusEntry = entry) -> None:
            problems = draft_problems(normalize_draft(draft, _entry, vocab), _entry, vocab, threshold, guards)
            other = [p for p in problems if not _is_length(p)]  # over-long phrases get their own small repair
            if other:
                raise ValueError("; ".join(other[:25]))

        origin: dict[str, Any] = {}
        if replay:
            completion, origin, why = stored_draft(paths, client, tid)
            if completion is None:
                result.failed.append((tid, why))
                continue
            try:
                check(completion.data)
            except ValueError as exc:
                result.failed.append((tid, f"stored draft fails the current checks: {str(exc)[:200]}"))
                continue
        else:
            ctx = CallContext(pass_="P1", record_id=tid, title_id=tid,
                              upstream=upstream_hash([entry.model_dump(mode="json")]))
            try:
                completion = client.complete_ex(prompt.system, render_user(entry), schema, params, ctx=ctx,
                                                validate=check)
            except InvalidOutput as exc:
                quarantine(paths.quarantine, "P1", "title", tid, exc.raw, exc.errors)
                result.quarantined.append((tid, exc.errors[-1][:300]))
                continue
            except LiveRunRefused as exc:
                result.refused.append((tid, str(exc)))
                continue
            except (BudgetExceeded, RateLimited, CliAuthError) as exc:  # stop the run; finished titles stay cached
                result.stopped = str(exc)
                break
            except ProviderError as exc:
                result.failed.append((tid, str(exc)))
                continue
        if completion.substituted:
            result.substituted.append((tid, completion.model))
        draft = normalize_draft(completion.data, entry, vocab)
        long = [p for p in draft_problems(draft, entry, vocab, threshold, guards) if _is_length(p)]
        if long:
            identity = client.identity
            if replay:  # its length repair replays from the cache too, keyed as it was then
                client.prompt_version = origin.get("prompt_version", prompt.version)
                client.identity = completion.identity or identity
            try:
                draft = normalize_draft(shorten_phrases(client, entry, draft, long, params), entry, vocab)
            except InvalidOutput as exc:
                quarantine(paths.quarantine, "P1", "title", tid, draft, [*exc.errors, *long])
                result.quarantined.append((tid, "phrases still over their word limits after the length repair"))
                continue
            except (BudgetExceeded, RateLimited, CliAuthError) as exc:
                result.stopped = str(exc)
                break
            except ProviderError as exc:
                result.failed.append((tid, "its length repair is not in the response cache; a replay makes no "
                                           "model call" if replay else str(exc)))
                continue
            finally:
                client.prompt_version, client.identity = prompt.version, identity
            left = draft_problems(draft, entry, vocab, threshold, guards)
            if left:
                quarantine(paths.quarantine, "P1", "title", tid, draft, left)
                result.quarantined.append((tid, left[0][:300]))
                continue
        record, moments, to_verify = assemble(draft, entry, vocab, settings,
                                              run_id=origin.get("run_id", run_id),
                                              prompt_version=origin.get("prompt_version", prompt.version),
                                              completion=completion, created_at=origin.get("created_at", created_at))
        try:  # candidates keep raw other:<phrase>; check the normalized form CANONICALIZE will store
            title_model.model_validate(normalize_record("title", record, vocab)[0])
            for m in moments:
                Moment.model_validate(normalize_record("moment", m, vocab)[0])
        except ValidationError as exc:
            quarantine(paths.quarantine, "P1", "title", tid, {"record": record, "moments": moments}, [str(exc)])
            result.quarantined.append((tid, f"assembly: {exc.errors()[0]['msg']}"))
            continue
        result.titles.append(record)
        result.moments.extend(moments)
        if agreement_dir is not None:
            continue
        if replay:  # what the replay replaces is kept, and the old VERIFY's outcome no longer stands
            for sub in ("title", "moment", "outcome"):
                supersede(paths.candidates / sub / f"{tid}.jsonl", run_id)
        # one candidate file per title and record type: VERIFY rewrites these in place
        atomic_write_text(paths.candidates / "title" / f"{tid}.jsonl", dumps_jsonl([record]))
        atomic_write_text(paths.candidates / "moment" / f"{tid}.jsonl", dumps_jsonl(moments))
        atomic_write_text(paths.candidates / "verify" / f"{tid}.json",
                          json.dumps({"title_id": tid, "run_id": run_id, "verify": to_verify}, indent=2) + "\n")
    if agreement_dir is not None and result.titles:
        atomic_write_text(agreement_dir / "titles.jsonl", dumps_jsonl(result.titles))
    return result
