"""INTERPRET (v1.7, gather-first P1): the full profile from GATHER's facts, no web.

The strong model fills every lens field and the moments from the gathered facts (documented fields)
and interprets the analysis fields from them, citing fact ids per field in `evidence`. It reuses
P1's prompt (field docs, enums, example), schema, validation, length repair and assembly, so P1's
rules hold unchanged. Afterwards, in code:
- a field whose cited facts all exist and sit inside the scope becomes `source: web`,
  `verification: gathered`, with the first fact's URL as `source_ref` (unplaced facts never settle
  anything);
- the outcome comes from reception facts (API numbers and critic verdicts) with their URLs;
- VERIFY's list keeps only what is still unsourced (plus its always-checked items, which VERIFY's
  gold-only rule then narrows).
Outputs are P1's candidate files, so CANONICALIZE and VERIFY need no change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from animedex.budget import BudgetExceeded
from animedex.config import Settings
from animedex.content_guards import GuardConfig
from animedex.guards import LiveRunRefused
from animedex.models import CorpusEntry, Moment, title_profile_model
from animedex.models.common import PRINT_MEDIA
from animedex.ontology import Vocab
from animedex.paths import Paths
from animedex.pipeline.common import render_profile, supersede
from animedex.pipeline.gather import gather_paths, load_gathered
from animedex.pipeline.p1 import (
    _is_length,
    assemble,
    draft_problems,
    normalize_draft,
    output_schema,
    render_prompt,
    render_user,
    shorten_phrases,
)
from animedex.prompts import RenderedPrompt, read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, InvalidOutput, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.cache import upstream_hash
from animedex.store.canonical import normalize_record
from animedex.store.jsonl import dumps_jsonl
from animedex.store.quarantine import quarantine
from animedex.textutil import word_count

CONFOUNDERS = ("studio", "budget_signal", "source_popularity", "platform", "release_context")
SHARED_SLOT = ("mentor", "deuteragonist")


@dataclass
class InterpretResult:
    titles: list[dict[str, Any]] = field(default_factory=list)
    characters: dict[str, int] = field(default_factory=dict)    # title -> characters written
    notes: dict[str, list[str]] = field(default_factory=dict)
    sourced: dict[str, int] = field(default_factory=dict)       # title -> fields settled by gathered facts
    outcomes: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    quarantined: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    stopped: str | None = None


def render_system(paths: Paths, vocab: Vocab, settings: Settings) -> RenderedPrompt:
    pre = read_prompt(paths.prompts / "interpret.md")
    p1 = render_prompt(paths, vocab, settings)
    return RenderedPrompt(pre.body + "\n" + p1.system, f"{pre.meta['version']}+p1-{p1.version}")


def fact_index(gathered: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every gathered item by id: F (fields), C (characters), R (verdicts), A (API reception)."""
    out: dict[str, dict[str, Any]] = {f["id"]: {**f, "kind": "field"} for f in gathered.get("facts") or []}
    for ch in gathered.get("characters") or []:
        for f in ch.get("facts") or []:
            out[f["id"]] = {**f, "kind": "character", "role": ch.get("role"), "name": ch.get("name")}
    for r in gathered.get("reception") or []:
        out[r["id"]] = {**r, "kind": "verdict", "scope": "in_scope"}
    for a in gathered.get("reception_api") or []:
        out[a["id"]] = {**a, "kind": "reception", "scope": "in_scope", "source_url": a.get("url")}
    return out


def _where(f: dict[str, Any]) -> str:
    """Where a fact is placed: s1e7 for screen, c12 (and v2) for print (v1.9), nothing when unplaced."""
    if f.get("season") and f.get("episode"):
        return f" s{f['season']}e{f['episode']}"
    parts = [f"c{f['chapter']}" if f.get("chapter") else "", f"v{f['volume']}" if f.get("volume") else ""]
    joined = "".join(parts)
    return f" {joined}" if joined else ""


def render_facts(gathered: dict[str, Any]) -> str:
    """Compact `key: value` lines, one per fact, with its id (v1.7 compact context)."""
    lines = ["gathered_facts:"]
    for f in gathered.get("facts") or []:
        where = _where(f)
        lines.append(f"{f['id']}: {f['path']} = {f['value']}{where} [{f['scope']}]")
    for ch in gathered.get("characters") or []:
        for f in ch.get("facts") or []:
            where = _where(f)
            lines.append(f"{f['id']}: character {ch['role']} ({ch.get('name')}) {f['field']} = {f['value']}{where} [{f['scope']}]")
    for r in gathered.get("reception") or []:
        lines.append(f"{r['id']}: {r['kind']} verdict = {r['verdict']}")
    for a in gathered.get("reception_api") or []:
        nums = ", ".join(f"{k} {a[k]}" for k in ("score", "scorers", "rank", "popularity") if a.get(k) is not None)
        lines.append(f"{a['id']}: reception {a['source']} = {nums or 'no numbers'}")
    if len(lines) == 1:
        lines.append("none: nothing was gathered; fill from what you know, with honest confidence")
    return "\n".join(lines)


def schema_with_evidence(base: dict[str, Any], ids: list[str]) -> dict[str, Any]:
    fid = {"type": "string", "enum": ids or ["none"]}
    evidence = {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                           "required": ["path", "fact_ids"],
                                           "properties": {"path": {"type": "string"},
                                                          "fact_ids": {"type": "array", "items": fid}}}}
    signal = {"type": "object", "additionalProperties": False, "required": ["metric", "value", "fact_id"],
              "properties": {"metric": {"type": "string"}, "value": {"type": "string"}, "fact_id": fid}}
    outcome = {"type": ["object", "null"], "additionalProperties": False,
               "required": ["label", "signals", "failure_reason", "failure_level", "failure_evidence",
                            "failure_evidence_fact", "confounders"],
               "properties": {"label": {"type": "string", "enum": ["hit", "mixed", "flop"]},
                              "signals": {"type": "array", "items": signal},
                              "failure_reason": {"type": ["string", "null"]},
                              "failure_level": {"type": ["string", "null"],
                                                "enum": ["premise", "execution", "external", "unknown", None]},
                              "failure_evidence": {"type": ["string", "null"]},
                              "failure_evidence_fact": {"type": ["string", "null"]},
                              "confounders": {"type": "object", "additionalProperties": False,
                                              "required": list(CONFOUNDERS),
                                              "properties": {k: {"type": "string"} for k in CONFOUNDERS}}}}
    out = json.loads(json.dumps(base))
    out["properties"]["evidence"] = evidence
    out["properties"]["outcome"] = outcome
    out["required"] = [*out.get("required", []), "evidence", "outcome"]
    return out


def apply_evidence(record: dict[str, Any], evidence: list[dict[str, Any]], facts: dict[str, dict[str, Any]],
                   threshold: float) -> list[str]:
    """Mark fields settled by in-scope gathered facts; returns the paths sourced."""
    sourced = []
    for item in evidence or []:
        block, _, name = str(item.get("path") or "").partition(".")
        fv = (record.get(block) or {}).get(name)
        cited = [facts.get(i) for i in item.get("fact_ids") or []]
        if not isinstance(fv, dict) or fv.get("value") is None or not cited or any(
                c is None or c.get("scope") != "in_scope" or not c.get("source_url") for c in cited):
            continue
        fv.update(source="web", verification="gathered", source_ref=cited[0]["source_url"],
                  conf=max(float(fv.get("conf") or 0), threshold))
        sourced.append(f"{block}.{name}")
    return sourced


def build_outcome(tid: str, oc: dict[str, Any] | None, facts: dict[str, dict[str, Any]], prov: dict[str, Any]
                  ) -> dict[str, Any] | None:
    """An outcome only from reception facts (A.. numbers, R.. verdicts); anything else stays unresolved."""
    if not oc or oc.get("label") not in ("hit", "mixed", "flop"):
        return None
    from animedex.pipeline.verify import _copied

    signals = [{"metric": s["metric"], "value": s["value"], "source_ref": facts[s["fact_id"]]["source_url"]}
               for s in oc.get("signals") or []
               if facts.get(s.get("fact_id"), {}).get("kind") in ("reception", "verdict")
               and facts[s["fact_id"]].get("source_url")
               and not _copied(s.get("metric"), s.get("value"))]
    hit = oc["label"] == "hit"
    reason = None if hit else oc.get("failure_reason")
    if not signals or (not hit and (not reason or word_count(reason) > 25)):
        return None
    level = None if hit else (oc.get("failure_level") or "unknown")
    ev_fact = facts.get(oc.get("failure_evidence_fact") or "")
    evidence = oc.get("failure_evidence")
    sourced = (level not in (None, "unknown") and ev_fact is not None and ev_fact.get("source_url")
               and evidence and word_count(evidence) <= 25)
    if level not in (None, "unknown") and not sourced:
        level = "unknown"
    return {"title_id": tid, "label": oc["label"], "signals": signals,
            "confounders": {k: (oc.get("confounders") or {}).get(k, "") for k in CONFOUNDERS},
            "failure_reason": reason, "failure_level": level,
            "failure_evidence": evidence if sourced else None,
            "failure_evidence_ref": ev_fact["source_url"] if sourced else None,
            "failure_level_source": "verify" if level is not None else None, "provenance": prov}


def characters_schema(vocab: Vocab, ids: list[str]) -> dict[str, Any]:
    def enum(name: str, nullable: bool = True) -> dict[str, Any]:
        values = list(vocab.enum(name))
        return {"type": ["string", "null"], "enum": [*values, None]} if nullable else {"type": "string", "enum": values}

    s, sn = {"type": "string"}, {"type": ["string", "null"]}
    fid, fidn = {"type": "string", "enum": ids or ["none"]}, {"type": ["string", "null"], "enum": [*(ids or ["none"]), None]}

    def obj(props: dict[str, Any], nullable: bool = False) -> dict[str, Any]:
        return {"type": ["object", "null"] if nullable else "object", "additionalProperties": False,
                "required": list(props), "properties": props}

    trait = obj({"value": s, "condition": s}, nullable=True)
    kit = obj({"power_kind": enum("character.power_kind", nullable=False), "medium": sn,
               "functions": {"type": "array", "items": s}, "tools": {"type": "array", "items": obj({"tool": s, "function": s})},
               "limits": {"type": "array", "items": s},
               "forms": {"type": "array", "items": obj({"name": s, "trigger": s, "cost": s})},
               "creativity_level": enum("character.creativity_level"),
               "creativity_moves": {"type": "array", "items": obj({"move": s, "fact_id": fid})},
               "drama_source": enum("character.drama_source"), "evolution": sn}, nullable=True)
    villain = obj({"villain_type": enum("character.villain_type", False), "villain_reveal": enum("character.villain_reveal", False),
                   "relation_to_mc": enum("character.relation_to_mc", False)}, nullable=True)
    character = obj({"role": enum("character.role", False), "name": s, "origin": sn, "wound": sn, "want": sn, "need": sn,
                     "flaw": trait, "moral_line": trait, "relationship_to_power": enum("power_combat.mc_edge"),
                     "origin_power_link": enum("character.origin_power_link"), "arc_type": enum("character.arc_type"),
                     "backstory_reveal": enum("character.backstory_reveal"),
                     "turning_points": {"type": "array", "items": obj({"event": s, "season": {"type": ["integer", "null"]},
                                                                       "episode": {"type": ["integer", "null"]},
                                                                       "chapter": {"type": ["integer", "null"]},
                                                                       "volume": {"type": ["integer", "null"]},
                                                                       "fact_id": fidn})},
                     "power_kit": kit, "villain": villain, "fact_ids": {"type": "array", "items": fid}})
    return obj({"characters": {"type": "array", "items": character, "maxItems": 4}})


def build_characters(entry: CorpusEntry, out: dict[str, Any], facts: dict[str, dict[str, Any]], vocab: Vocab,
                     prov: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Records that pass the model and the cast rules (04); anything else is dropped with a note, never
    left to hold the title's profile at CANONICALIZE (per-title transactions)."""
    from animedex.integrity import character_errors
    from animedex.models.characters import CharacterRecord

    notes: list[str] = []
    tid, film = entry.title_id, entry.format == "film"
    seasons = set(entry.scope.seasons or [])
    print_title, span = entry.medium in PRINT_MEDIA, entry.scope.range   # v1.9: print places by chapter/volume

    def placed(tp: dict[str, Any]) -> bool:
        if film:
            return True
        if print_title:
            unit = tp.get("chapter") if entry.scope.numbering == "chapters" else tp.get("volume")
            if unit is None:
                unit = tp.get("chapter") if tp.get("chapter") is not None else tp.get("volume")
            return unit is not None and (not span or span[0] <= unit <= span[1])
        return tp.get("episode") is not None and (not seasons or tp.get("season") in seasons)

    def ok_fact(fid: Any) -> dict[str, Any] | None:
        f = facts.get(fid or "")
        return f if f and f.get("scope") == "in_scope" and f.get("source_url") else None

    seen, cast = set(), []
    for ch in out.get("characters") or []:
        slot = "mentor|deuteragonist" if ch.get("role") in SHARED_SLOT else ch.get("role")
        if slot in seen or len(cast) >= 4:
            notes.append(f"character {ch.get('name')}: a second {slot} (dropped)")
            continue
        seen.add(slot)
        cast.append(ch)
    if not any(c.get("role") == "protagonist" for c in cast):
        return [], [*notes, "no protagonist: no characters written"]
    protagonist_kit = any(c.get("role") == "protagonist" and c.get("power_kit") for c in cast)
    records, kits = [], 0
    for n, ch in enumerate(sorted(cast, key=lambda c: c.get("role") != "protagonist"), start=1):
        kit = ch.get("power_kit")
        if kit and (not protagonist_kit or kits >= 3):
            notes.append(f"character {ch.get('name')}: power kit dropped (the protagonist's comes first; 3 at most)")
            kit = None
        if kit:
            kits += 1
            moves = [{"move": m["move"], "source_ref": ok_fact(m.get("fact_id"))["source_url"]}
                     for m in kit.get("creativity_moves") or [] if ok_fact(m.get("fact_id"))]
            level = kit.get("creativity_level")
            if level in ("inventive", "transcendent") and not moves:
                level = "literal"  # a creative reading needs a sourced move
            if kit.get("power_kind") == "none":
                kit = {"power_kind": "none"}
            else:
                kit = {**{k: v for k, v in kit.items() if k != "creativity_moves"}, "creativity_moves": moves,
                       "creativity_level": level if kit.get("power_kind") != "stat_block" else None}
        tps = [{"event": tp["event"], "locator": {"season": tp.get("season"), "episode": tp.get("episode"),
                                                  **({"chapter": tp.get("chapter"), "volume": tp.get("volume")}
                                                     if print_title else {})}}
               for tp in ch.get("turning_points") or [] if placed(tp)]
        cited = [ok_fact(i) for i in ch.get("fact_ids") or []]
        rec = {"character_id": f"{tid}.c.{n:02d}", "title_id": tid, "name": ch.get("name"), "role": ch.get("role"),
               **{k: ch.get(k) for k in ("origin", "wound", "want", "need", "flaw", "moral_line", "relationship_to_power",
                                         "origin_power_link", "arc_type", "backstory_reveal")},
               "turning_points": tps[:3], "power_kit": kit,
               "villain": ch.get("villain") if ch.get("role") == "main_antagonist" else None,
               "source_refs": sorted({c["source_url"] for c in cited if c}), "provenance": prov}
        try:
            CharacterRecord.model_validate(normalize_record("character", rec, vocab)[0])
        except (ValidationError, ValueError) as exc:
            if rec["role"] == "protagonist":
                return [], [*notes, f"the protagonist's record is invalid ({str(exc)[:120]}): no characters written"]
            notes.append(f"character {rec['name']}: dropped ({str(exc)[:120]})")
            continue
        records.append(rec)
    title = {"title_id": tid, "format": entry.format, "scope": entry.scope.model_dump(mode="json")}
    if errors := character_errors({"character": records}, {tid: title}):
        return [], [*notes, f"cast rules failed ({errors[0]}): no characters written"]
    return records, notes


def run_interpret(paths: Paths, entries: list[CorpusEntry], client: LLMClient, vocab: Vocab, settings: Settings, *,
                  run_id: str, guards: GuardConfig | None = None, created_at: str | None = None,
                  params: dict[str, Any] | None = None, out_dir: Path | None = None) -> InterpretResult:
    """`out_dir` + `params` (e.g. {"rerun": 2} or {"effort": "high"}): an extra run written there instead
    of candidates (AC-12 agreement runs, the effort A/B)."""
    guards = guards or GuardConfig.from_settings(settings)
    prompt = render_system(paths, vocab, settings)
    client.prompt_version = prompt.version
    threshold = float(settings.verify.get("conf_threshold", 0.7))
    title_model = title_profile_model(vocab)
    documented = gather_paths(vocab, settings)
    needs_source = {f.path for f in vocab.lens_fields() if f.needs_source}
    result = InterpretResult()
    for entry in entries:
        tid = entry.title_id
        gathered = load_gathered(paths, tid)
        if gathered is None:
            result.skipped.append((tid, "no GATHER facts; run `animedex gather` first"))
            continue
        facts = fact_index(gathered)
        schema = schema_with_evidence(output_schema(vocab, entry), sorted(facts))
        user = render_user(entry) + "\n\n" + render_facts(gathered)

        def check(draft: dict[str, Any], _entry: CorpusEntry = entry) -> None:
            problems = draft_problems(normalize_draft(draft, _entry, vocab), _entry, vocab, threshold, guards)
            other = [p for p in problems if not _is_length(p)]
            if other:
                raise ValueError("; ".join(other[:25]))

        ctx = CallContext(pass_="INTERPRET", record_id=tid, title_id=tid,
                          upstream=upstream_hash([entry.model_dump(mode="json"), {"gathered": sorted(facts.items())}]))
        try:
            completion = client.complete_ex(prompt.system, user, schema, params, ctx=ctx, validate=check)
        except InvalidOutput as exc:
            quarantine(paths.quarantine, "INTERPRET", "title", tid, exc.raw, exc.errors)
            result.quarantined.append((tid, exc.errors[-1][:300]))
            continue
        except LiveRunRefused as exc:
            result.skipped.append((tid, str(exc)))
            continue
        except (BudgetExceeded, RateLimited, CliAuthError) as exc:  # stop the run; finished titles stay cached
            result.stopped = str(exc)
            break
        except ProviderError as exc:
            result.failed.append((tid, str(exc)))
            continue
        data = completion.data
        draft = normalize_draft(data, entry, vocab)
        long = [p for p in draft_problems(draft, entry, vocab, threshold, guards) if _is_length(p)]
        if long:
            try:
                draft = normalize_draft(shorten_phrases(client, entry, draft, long, params), entry, vocab)
            except InvalidOutput as exc:
                quarantine(paths.quarantine, "INTERPRET", "title", tid, draft, [*exc.errors, *long])
                result.quarantined.append((tid, "phrases still over their word limits after the length repair"))
                continue
            except (BudgetExceeded, RateLimited, CliAuthError) as exc:
                result.stopped = str(exc)
                break
            except ProviderError as exc:
                result.failed.append((tid, str(exc)))
                continue
        record, moments, to_verify = assemble(draft, entry, vocab, settings, run_id=run_id,
                                              prompt_version=prompt.version, completion=completion,
                                              created_at=created_at)
        sourced = apply_evidence(record, data.get("evidence") or [], facts, threshold)
        outcome = build_outcome(tid, data.get("outcome"), facts, record["provenance"])
        if outcome and entry.medium in PRINT_MEDIA and gathered.get("adaptation"):  # v1.9: from the catalog
            outcome["adaptation"] = gathered["adaptation"]
        if outcome:  # the profile's outcome field follows the reception-backed outcome
            record["core"]["outcome"].update(value=outcome["label"], source="web", verification="gathered",
                                             source_ref=outcome["signals"][0]["source_ref"],
                                             conf=max(float(record["core"]["outcome"].get("conf") or 0), threshold))
            sourced.append("core.outcome")
        # VERIFY checks documented facts only (v1.7): what GATHER could have sourced, the outcome, and the
        # sensory/moment items VERIFY's gold rule decides; analysis fields have no page that could confirm them
        checkable = set(documented) | {"core.outcome"} | needs_source  # a source-required field goes to VERIFY
        to_verify = [p for p in to_verify if p not in set(sourced)
                     and (p in checkable or p.startswith(("sensory.", "moments.")))]
        for block, fields in record.items():
            if block in ("core", *record.get("modules_active", [])) and isinstance(fields, dict):
                for name, fv in fields.items():
                    if isinstance(fv, dict) and fv.get("verification") == "unverified" and f"{block}.{name}" not in to_verify:
                        fv["verification"] = "not_required"
        try:
            title_model.model_validate(normalize_record("title", record, vocab)[0])
            for m in moments:
                Moment.model_validate(normalize_record("moment", m, vocab)[0])
        except ValidationError as exc:
            quarantine(paths.quarantine, "INTERPRET", "title", tid, {"record": record, "moments": moments}, [str(exc)])
            result.quarantined.append((tid, f"assembly: {exc.errors()[0]['msg']}"))
            continue
        result.titles.append(record)
        result.sourced[tid] = len(sourced)
        if outcome:
            result.outcomes.append(tid)
        if out_dir is not None:
            atomic_write_text(out_dir / f"{tid}.json", json.dumps({"record": record, "outcome": outcome}, indent=2) + "\n")
            continue
        # the raw profile before VERIFY: the first run of the AC-12 pair (eval/agreement is git-ignored)
        atomic_write_text(paths.root / "eval" / "agreement" / "interpret" / "first" / f"{tid}.json",
                          json.dumps({"record": record, "outcome": outcome}, indent=2) + "\n")
        atomic_write_text(paths.candidates / "title" / f"{tid}.jsonl", dumps_jsonl([record]))
        atomic_write_text(paths.candidates / "moment" / f"{tid}.jsonl", dumps_jsonl(moments))
        atomic_write_text(paths.candidates / "verify" / f"{tid}.json",
                          json.dumps({"title_id": tid, "run_id": run_id, "verify": to_verify}, indent=2) + "\n")
        if outcome:
            atomic_write_text(paths.candidates / "outcome" / f"{tid}.jsonl", dumps_jsonl([outcome]))
        # characters (v1.8): a second call from the same facts plus the interpreted profile
        cprompt = read_prompt(paths.prompts / "interpret_characters.md")
        cuser = "\n".join([*render_profile(record, vocab, verification=False), "", render_facts(gathered)])
        cctx = CallContext(pass_="INTERPRET", record_id=f"{tid}.characters", title_id=tid,
                           upstream=upstream_hash([record, {"facts": sorted(facts.items())}]))
        version, client.prompt_version = client.prompt_version, f"{cprompt.meta['version']}+{prompt.version}"
        chars: list[dict[str, Any]] = []
        try:
            done = client.complete_ex(cprompt.body, cuser, characters_schema(vocab, sorted(facts)), params, ctx=cctx,
                                      validate=None)
            chars, notes = build_characters(entry, done.data, facts, vocab, record["provenance"])
            result.notes[tid] = notes
        except (InvalidOutput, ProviderError) as exc:
            if isinstance(exc, (RateLimited, CliAuthError)):
                result.stopped = str(exc)
            result.notes[tid] = [f"characters not written: {str(exc)[:160]}"]
        except (BudgetExceeded, LiveRunRefused) as exc:
            result.notes[tid] = [f"characters not written: {exc}"]
            if isinstance(exc, BudgetExceeded):
                result.stopped = str(exc)
        finally:
            client.prompt_version = version
        cfile = paths.candidates / "character" / f"{tid}.jsonl"
        if chars:
            atomic_write_text(cfile, dumps_jsonl(chars))
        else:
            supersede(cfile, run_id)  # an older run's cast no longer stands
        result.characters[tid] = len(chars)
        if result.stopped:
            break
    return result
