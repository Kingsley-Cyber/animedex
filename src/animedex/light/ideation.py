"""Source mechanisms -> story hypotheses -> drafts -> scene tests -> prior art -> suggestions."""

from __future__ import annotations

import json
import random
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from animedex.config import Settings
from animedex.ideate.review import load_ratings
from animedex.light.abduction import AbductionError, AbductionPaused, _complete, _raise
from animedex.light.ingest import web_limits
from animedex.light.notes import ENGINE, TEXT, _arr, _obj, index_line, read_notes
from animedex.paths import Paths
from animedex.providers.client import LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.textutil import blocked_source, norm_url, sha256_text

DOMAINS = ("science", "history", "myth", "craft", "economics", "law", "sport", "daily_life")
CHECKS = ("rule_drives_choices", "engine_has_runway", "specific_not_cosmetic", "fits_brief", "distinct_from_notes")
MAYBE = {"type": ["string", "null"]}
FUNCTION_WORDS = frozenset("a an the and or but of to in on at for from with without by as is are was were be been being it its this that these those i me my we our you your they their he his she her can could would should will do does did have has had who what which where when why how".split())


def _content_terms(value: str) -> set[str]:
    return set(re.findall(r"[\w']+", value.casefold())) - FUNCTION_WORDS


def _text_problems(item: dict[str, Any], fields: tuple[str, ...], where: str) -> list[str]:
    return [f"{where}.{field}: give a concrete statement" for field in fields
            if not str(item.get(field) or "").strip()]


def material_schema() -> dict[str, Any]:
    return _obj({"materials": _arr(_obj({"domain": {"type": "string", "enum": list(DOMAINS)},
        **{field: TEXT for field in ("causal_rule", "surprise", "shape", "forced_choice", "cost", "source_url")}}))})


def material_problems(out: dict[str, Any], meta: dict[str, Any], n: int) -> list[str]:
    items = out.get("materials") or []
    problems = [] if len(items) == n else [f"return exactly {n} source mechanisms"]
    fetched = {norm_url(url) for url in (meta.get("web") or {}).get("fetched") or []}
    rules = [str(item.get("causal_rule") or "").strip().casefold() for item in items]
    if len(set(rules)) != len(rules):
        problems.append("source mechanisms must have different causal rules")
    for i, item in enumerate(items):
        problems += _text_problems(item, ("causal_rule", "surprise", "shape", "forced_choice", "cost"), f"materials[{i}]")
        if blocked_source(item.get("source_url")) or norm_url(item.get("source_url")) not in fetched:
            problems.append(f"materials[{i}].source_url: cite an allowed page opened in this call")
    return problems


def retain_sourced_materials(out: dict[str, Any], meta: dict[str, Any]) -> None:
    accepted, rejected = [], []
    for item in out.get("materials") or []:
        problems = material_problems({"materials": [item]}, meta, 1)
        if problems:
            rejected.append({"material": item, "problems": problems})
        else:
            accepted.append(item)
    if not accepted:
        _raise([problem for row in rejected for problem in row["problems"]]
               or ["no source mechanism supported by an opened page"])
    _raise(material_problems({"materials": accepted}, meta, len(accepted)))
    out["materials"] = accepted
    meta["rejected_materials"] = rejected


def read_materials(paths: Paths) -> dict[str, dict[str, Any]]:
    directory = paths.notes / "_materials"
    result = {}
    for path in sorted(directory.glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        problems = material_problems({"materials": [item]}, item.get("provenance") or {}, 1)
        if item.get("domain") not in DOMAINS or item.get("id") != path.stem or problems:
            raise AbductionError(f"invalid saved source mechanism: {path}")
        result[path.stem] = item
    return result


def retrieve_materials(brief: str, materials: dict[str, dict[str, Any]], n: int) -> list[str]:
    """Match structural text, then prefer unused domains; zero-overlap records do not fill a query."""
    query = _content_terms(brief)
    scores = {id_: len(query & _content_terms(" ".join(
        str(item.get(field) or "") for field in ("causal_rule", "surprise", "shape", "forced_choice", "cost"))))
        for id_, item in materials.items() if item.get("domain") in DOMAINS}
    remaining = {id_ for id_, score in scores.items() if score}
    selected: list[str] = []
    domains: set[str] = set()
    while remaining and len(selected) < n:
        id_ = min(remaining, key=lambda value: (materials[value]["domain"] in domains, -scores[value],
                                                sha256_text(brief + value)))
        selected.append(id_)
        domains.add(materials[id_]["domain"])
        remaining.remove(id_)
    return selected


def hypothesis_schema(material_ids: list[str]) -> dict[str, Any]:
    item = _obj({**{field: TEXT for field in ("surprise", "claim", "forced_choice", "supporting_question", "falsifying_question")},
                 "material_ids": _arr({"type": "string", "enum": material_ids})})
    return _obj({"hypotheses": _arr(item)})


def hypothesis_problems(out: dict[str, Any], ids: list[str], n: int) -> list[str]:
    items = out.get("hypotheses") or []
    problems = [] if len(items) == n else [f"return exactly {n} distinct story hypotheses"]
    claims = [str(item.get("claim") or "").strip().casefold() for item in items]
    if len(set(claims)) != len(claims):
        problems.append("hypotheses must propose different causal rules")
    for i, item in enumerate(items):
        problems += _text_problems(item, ("surprise", "claim", "forced_choice", "supporting_question", "falsifying_question"), f"hypotheses[{i}]")
        refs = item.get("material_ids") or []
        if not refs or len(set(refs)) != len(refs) or any(ref not in ids for ref in refs):
            problems.append(f"hypotheses[{i}].material_ids: cite distinct supplied mechanism IDs")
    return problems


def draft_schema(hypothesis_ids: list[str] | None) -> dict[str, Any]:
    ref = {"type": "string", "enum": hypothesis_ids} if hypothesis_ids else {"type": "null"}
    return _obj({"ideas": _arr(_obj({**{field: TEXT for field in
        ("logline", "premise", "story_rule", "protagonist_advantage", "cold_open")},
        "engine": _obj({field: TEXT for field in ENGINE}), "hypothesis_ref": ref}))})


def draft_problems(out: dict[str, Any], ids: list[str] | None, n: int) -> list[str]:
    items = out.get("ideas") or []
    problems = [] if len(items) == n else [f"draft exactly {n} ideas"]
    rules = [str(item.get("story_rule") or "").strip().casefold() for item in items]
    if len(set(rules)) != len(rules):
        problems.append("ideas must use different causal rules")
    if ids is not None and sorted(item.get("hypothesis_ref") for item in items) != sorted(ids):
        problems.append("draft each supplied hypothesis exactly once")
    for i, item in enumerate(items):
        problems += _text_problems(item, ("logline", "premise", "story_rule", "protagonist_advantage", "cold_open"), f"ideas[{i}]")
        problems += _text_problems(item.get("engine") or {}, ENGINE, f"ideas[{i}].engine")
    return problems


def stress_schema(refs: list[str], note_ids: list[str]) -> dict[str, Any]:
    peer = {"type": ["string", "null"], "enum": [*refs, None]}
    note = {"type": ["string", "null"], "enum": [*note_ids, None]}
    return _obj({"tests": _arr(_obj({"ref": {"type": "string", "enum": refs},
        **{field: {"type": "boolean"} for field in CHECKS},
        **{field: TEXT for field in ("pressure_scene", "escalation_scene", "removal_test", "reason")},
        "same_engine_as": peer, "closest_note": note}))})


def stress_problems(out: dict[str, Any], refs: list[str]) -> list[str]:
    tests = out.get("tests") or []
    problems = [] if sorted(item.get("ref") for item in tests) == sorted(refs) else ["test every idea exactly once"]
    for i, item in enumerate(tests):
        problems += _text_problems(item, ("pressure_scene", "escalation_scene", "removal_test", "reason"), f"tests[{i}]")
        if item.get("same_engine_as") == item.get("ref"):
            problems.append(f"tests[{i}].same_engine_as: cannot name itself")
    return problems


def prior_schema(refs: list[str]) -> dict[str, Any]:
    return _obj({"checks": _arr(_obj({"ref": {"type": "string", "enum": refs},
        "overlap": {"type": "string", "enum": ["same_engine", "partial", "unknown"]},
        "title": MAYBE, "url": MAYBE, "difference": TEXT}))})


def prior_problems(out: dict[str, Any], meta: dict[str, Any], refs: list[str]) -> list[str]:
    checks = out.get("checks") or []
    problems = [] if sorted(item.get("ref") for item in checks) == sorted(refs) else ["check prior art for every idea exactly once"]
    fetched = {_prior_source_key(url) for url in (meta.get("web") or {}).get("fetched") or []}
    for i, item in enumerate(checks):
        problems += _text_problems(item, ("difference",), f"checks[{i}]")
        if item.get("overlap") != "unknown" and (
            not str(item.get("title") or "").strip() or blocked_source(item.get("url"))
            or _prior_source_key(item.get("url")) not in fetched):
            problems.append(f"checks[{i}]: comparison needs a title and an opened, allowed source")
    return problems


def _prior_source_key(url: Any) -> tuple[str, str, str, str]:
    parts = urlsplit(norm_url(url))
    # Wikipedia /wiki/ titles can be emitted encoded by the web tool and decoded by the model.
    # Host and query still have to match; other publishers' path aliases are not inferred.
    path = unquote(parts.path) if parts.netloc == "en.wikipedia.org" and parts.path.startswith("/wiki/") else parts.path
    return parts.scheme, parts.netloc, path, parts.query


def _request(paths: Paths, clients: dict[str, LLMClient], record: dict[str, Any], path: Path,
             echo: Callable[[str], None], stage: str, slot: str, prompt: str, user: str,
             schema: dict[str, Any], validate: Any, params: dict[str, Any] | None = None) -> dict[str, Any]:
    record["stage"] = stage
    atomic_write_text(path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    echo(f"ideate: {stage}")
    done = _complete(paths, clients[slot], f"IDEATION_{stage.upper()}", sha256_text(user), prompt,
                     user, schema, validate, params)
    record["provenance"][stage] = {"model": done.provenance_model, "cache_key": done.cache_key,
                                 "cache_hit": done.cache_hit, "web": done.meta.get("web") or {}}
    if "rejected_materials" in done.meta:
        record["provenance"][stage]["rejected_materials"] = done.meta["rejected_materials"]
    return done.data


def _finish_prior(paths: Paths, settings: Settings, record: dict[str, Any], request: Any) -> None:
    ideas = record["ideas"]
    limits = web_limits(settings, len(ideas))
    user = f"web limits: {json.dumps(limits)}\n" + "\n".join(
        f"idea {ref}: {item['logline']} | rule: {item['story_rule']} | engine: {json.dumps(item['engine'], ensure_ascii=False)}" for ref, item in ideas.items())
    checked = request("prior_art", "scan", "ideation_prior_art.md", user, prior_schema(list(ideas)),
        lambda out, meta: _raise(prior_problems(out, meta, list(ideas))), {"web": limits})
    record["prior_art"] = {item["ref"]: item for item in checked["checks"]}
    duplicate_ids = {ref for ref, test in record["tests"].items() if test.get("same_engine_as")}
    duplicate_ids.update(test["same_engine_as"] for test in record["tests"].values() if test.get("same_engine_as"))
    record["suggested"] = [ref for ref, test in record["tests"].items() if ideas[ref]["arm"] == "hypothesis"
        and all(test[field] for field in CHECKS) and ref not in duplicate_ids
        and record["prior_art"][ref]["overlap"] == "partial"]
    if record.get("compare") or any(item["arm"] == "direct" for item in ideas.values()):
        record["packet_file"] = str(_packet(paths, record).relative_to(paths.root))
    record["status"], record["stage"] = "complete", "complete"
    record.pop("error", None)


def _brief_input(record: dict[str, Any]) -> str:
    return (f"medium: {record['medium']}\nbrief: {record['brief'] or 'suggest distinct new series concepts'}"
            f"\nideas: {record['requested']}\ntaste: {json.dumps(record['preferences'], ensure_ascii=False)}")


def _stress_drafts(paths: Paths, record: dict[str, Any], request: Any, stage: str = "stress") -> None:
    notes = read_notes(paths)
    fields = ("logline", "premise", "story_rule", "protagonist_advantage", "cold_open", "engine")
    user = _brief_input(record) + "\n" + "\n".join(
        f"idea {ref}: {json.dumps({field: item[field] for field in fields}, ensure_ascii=False)}"
        for ref, item in record["ideas"].items())
    user += "\ncomparison index (use only for criticism):\n" + "\n".join(index_line(note) for note in notes.values())
    tested = request(stage, "check", "ideation_stress.md", user,
                     stress_schema(list(record["ideas"]), list(notes)),
                     lambda out: _raise(stress_problems(out, list(record["ideas"]))))
    record["tests"] = {item["ref"]: item for item in tested["tests"]}


def _packet(paths: Paths, record: dict[str, Any]) -> Path:
    """Blind all drafts before filtering; both arms share the model, brief, visible fields, and tests."""
    entries = [(ref, item) for ref, item in record["ideas"].items()]
    random.Random(record["id"]).shuffle(entries)
    cards, key = [], {}
    for i, (ref, item) in enumerate(entries, start=1):
        id_ = f"P{i}"
        cards.append({"id": id_, "logline": item["logline"], "premise": item["premise"]})
        key[id_] = {"arm": item["arm"], "source": f"idea:{record['id']}:{ref}"}
    date = record["id"]
    path = paths.blind / f"packet_{date}.json"
    atomic_write_text(path, json.dumps({"date": date, "cards": cards}, indent=2, ensure_ascii=False) + "\n")
    atomic_write_text(paths.root / "data" / "blind" / f"key_{date}.json", json.dumps(key, indent=2) + "\n")
    return path


def render(record: dict[str, Any]) -> str:
    lines = [f"# Idea suggestions: {record['medium']}", "", f"Brief: {record['brief'] or 'open ideation'}", "",
             "These are proposed story rules. Source mechanisms are analogies; critic verdicts are model judgments.", ""]
    if record.get("packet_file"):
        return "\n".join([*lines, f"Blind comparison ready: {record['packet_file']}", "",
            "Rate all cards with `make review` before reading arm identities or detailed results.", ""])
    for ref in record.get("suggested") or []:
        idea, test, prior = record["ideas"][ref], record["tests"][ref], record["prior_art"][ref]
        lines += [f"## {ref}: {idea['logline']}", "", idea["premise"], "",
                  f"Story rule: {idea['story_rule']}", f"Cold open: {idea['cold_open']}", "",
                  f"Pressure scene: {test['pressure_scene']}", f"Escalation: {test['escalation_scene']}",
                  f"Removal test: {test['removal_test']}", "",
                  f"Prior comparison: {prior.get('title') or 'unresolved'}; {prior['difference']} ({prior.get('url') or 'no source'})", ""]
    lines += ["## Other candidates", ""]
    for ref, idea in record.get("ideas", {}).items():
        if ref not in (record.get("suggested") or []):
            test = (record.get("tests") or {}).get(ref, {})
            prior = (record.get("prior_art") or {}).get(ref, {})
            lines.append(f"- {ref}: {idea['logline']} ({test.get('reason') or 'not tested'}; prior art: {prior.get('overlap', 'not checked')})")
    return "\n".join(lines) + "\n"


def run_ideation(paths: Paths, settings: Settings, *, brief: str, medium: str, n: int, compare: bool,
                 clients: dict[str, LLMClient], run_id: str,
                 echo: Callable[[str], None] = lambda value: None) -> tuple[Path, dict[str, Any]]:
    if n < 1 or not medium.strip():
        raise AbductionError("ideation needs a positive requested count and a target medium")
    profile = paths.root / "steering" / "ideation.json"
    preferences = json.loads(profile.read_text(encoding="utf-8")) if profile.is_file() else {"preferences": []}
    now = datetime.now(UTC)
    id_ = now.strftime("%Y%m%d_%H%M%S_%f")
    path = paths.quick / "_ideation" / f"{id_}.json"
    record: dict[str, Any] = {"id": id_, "workflow": "hypothesis_ideation_v1", "run_id": run_id,
        "created_at": now.isoformat(), "brief": brief, "medium": medium, "requested": n,
        "preferences": preferences, "compare": compare, "status": "running", "stage": "materials", "ideas": {}, "provenance": {}}

    def save() -> None:
        atomic_write_text(path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")

    def complete(stage: str, slot: str, prompt: str, user: str, schema: dict[str, Any], validate: Any,
                 params: dict[str, Any] | None = None) -> dict[str, Any]:
        return _request(paths, clients, record, path, echo, stage, slot, prompt, user, schema, validate, params)

    base = _brief_input(record)
    save()
    try:
        materials = read_materials(paths)
        selected = retrieve_materials(brief, materials, n)
        needed = n - len(selected)
        record["retrieved_material_ids"] = selected
        if needed:
            # Existing repository web allocation, applied per requested source record.
            limits = web_limits(settings, needed)
            user = f"{base}\nas_of: {now.date().isoformat()}\nnew source mechanisms: {needed}\nweb limits: {json.dumps(limits)}\n" + "\n".join(
                f"already selected {ref}: {json.dumps(materials[ref], ensure_ascii=False)}" for ref in selected)
            sourced = complete("materials", "scan", "ideation_materials.md", user, material_schema(),
                retain_sourced_materials, {"web": limits})
            record["rejected_materials"] = record["provenance"]["materials"].get("rejected_materials") or []
            for item in sourced["materials"]:
                material_id = sha256_text(norm_url(item["source_url"]) + "\n" + item["causal_rule"]).split(":")[-1]
                material = {"id": material_id, **item, "retrieved_at": now.isoformat(),
                            "authority": "source-linked model extraction", "provenance": record["provenance"]["materials"]}
                material_path = paths.notes / "_materials" / f"{material_id}.json"
                if not material_path.exists():
                    atomic_write_text(material_path, json.dumps(material, indent=2, ensure_ascii=False) + "\n")
                materials[material_id] = json.loads(material_path.read_text(encoding="utf-8"))
                selected.append(material_id)
        record["materials"] = {ref: materials[ref] for ref in selected}
        hypothesis_user = base + "\n" + "\n".join(f"mechanism {ref}: {json.dumps(materials[ref], ensure_ascii=False)}" for ref in selected)
        hypothesized = complete("hypotheses", "generate", "ideation_hypotheses.md", hypothesis_user,
            hypothesis_schema(selected), lambda out: _raise(hypothesis_problems(out, selected, n)))
        hypotheses = {f"H{i}": {**item, "status": "invented, untested"} for i, item in enumerate(hypothesized["hypotheses"], start=1)}
        record["hypotheses"] = hypotheses
        user = base + "\nmode: hypothesis\n" + "\n".join(f"hypothesis {ref}: {json.dumps(item, ensure_ascii=False)}" for ref, item in hypotheses.items())
        drafted = complete("drafts", "generate", "ideation_drafts.md", user, draft_schema(list(hypotheses)),
            lambda out: _raise(draft_problems(out, list(hypotheses), n)))
        ideas = {f"I{i}": {**item, "arm": "hypothesis"} for i, item in enumerate(drafted["ideas"], start=1)}
        record["ideas"] = ideas
        if compare:
            direct = complete("baseline", "generate", "ideation_drafts.md", base + "\nmode: direct; draft from the brief without supplied source mechanisms or hypothesis traces",
                draft_schema(None), lambda out: _raise(draft_problems(out, None, n)))
            ideas.update({f"B{i}": {**item, "arm": "direct"} for i, item in enumerate(direct["ideas"], start=1)})
        entries = list(ideas.values())
        random.Random(id_ + ":critic").shuffle(entries)
        ideas = {f"C{i}": item for i, item in enumerate(entries, start=1)}
        record["ideas"] = ideas
        # Both arms face the same blinded critic. Source/arm labels are excluded from its input.
        _stress_drafts(paths, record, complete)
        _finish_prior(paths, settings, record, complete)
        save()
        atomic_write_text(path.with_suffix(".md"), render(record))
        return path, record
    except (AbductionError, AbductionPaused) as exc:
        record["status"] = "paused" if isinstance(exc, AbductionPaused) else "failed"
        record["error"] = str(exc)
        save()
        raise


def retry_prior_art(paths: Paths, settings: Settings, *, run_file: str | Path,
                    clients: dict[str, LLMClient], run_id: str,
                    echo: Callable[[str], None] = lambda value: None) -> tuple[Path, dict[str, Any]]:
    path = Path(run_file)
    if not path.is_absolute():
        path = paths.root / path
    if not path.resolve().is_relative_to((paths.quick / "_ideation").resolve()):
        raise AbductionError("use an ideation record under build/quick/_ideation")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("stage") != "prior_art" or not record.get("ideas") or set(record.get("tests") or {}) != set(record["ideas"]):
        raise AbductionError("--resume retries prior art only after the saved drafts and scene tests are complete")
    record.setdefault("resumed_run_ids", []).append(run_id)
    record["status"] = "running"

    def request(stage: str, slot: str, prompt: str, user: str, schema: dict[str, Any], validate: Any,
                params: dict[str, Any] | None = None) -> dict[str, Any]:
        return _request(paths, clients, record, path, echo, stage, slot, prompt, user, schema, validate, params)

    try:
        _finish_prior(paths, settings, record, request)
    except (AbductionError, AbductionPaused) as exc:
        record["status"] = "paused" if isinstance(exc, AbductionPaused) else "failed"
        record["error"] = str(exc)
        raise
    finally:
        atomic_write_text(path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    atomic_write_text(path.with_suffix(".md"), render(record))
    return path, record


def comparison_results(paths: Paths, run_file: str | Path) -> dict[str, Any]:
    path = Path(run_file)
    if not path.is_absolute():
        path = paths.root / path
    if not path.resolve().is_relative_to((paths.quick / "_ideation").resolve()):
        raise AbductionError("use an ideation record under build/quick/_ideation")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not record.get("packet_file"):
        raise AbductionError("this run has no blind comparison; use ideate --compare")
    packet = json.loads((paths.root / record["packet_file"]).read_text(encoding="utf-8"))
    ratings = load_ratings(paths.blind, record["id"])
    ids = [item["id"] for item in packet["cards"]]
    complete = all(isinstance((ratings.get(id_) or {}).get("rating"), int)
                   and (ratings.get(id_) or {}).get("greenlight") in (True, False) for id_ in ids)
    result: dict[str, Any] = {"complete": complete, "rated": sum(
        isinstance((ratings.get(id_) or {}).get("rating"), int) for id_ in ids), "total": len(ids)}
    if not complete:
        return result
    key = json.loads((paths.root / "data" / "blind" / f"key_{record['id']}.json").read_text(encoding="utf-8"))
    result["arms"] = {arm: {"ratings": [ratings[id_]["rating"] for id_ in ids if key[id_]["arm"] == arm],
        "kept": [id_ for id_ in ids if key[id_]["arm"] == arm and ratings[id_]["greenlight"] is True]}
        for arm in ("hypothesis", "direct")}
    result["provenance"] = {id_: key[id_] for id_ in ids}
    return result


def recheck_ideas(paths: Paths, settings: Settings, *, run_file: str | Path,
                  clients: dict[str, LLMClient], run_id: str,
                  echo: Callable[[str], None] = lambda value: None) -> tuple[Path, dict[str, Any]]:
    path = Path(run_file)
    if not path.is_absolute():
        path = paths.root / path
    if not path.resolve().is_relative_to((paths.quick / "_ideation").resolve()):
        raise AbductionError("use an ideation record under build/quick/_ideation")
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("status") != "complete" or not record.get("ideas"):
        raise AbductionError("--recheck needs a completed ideation run")
    record.setdefault("test_history", []).append({"tests": record["tests"],
                                                   "provenance": record["provenance"].get("stress")})
    record.setdefault("resumed_run_ids", []).append(run_id)
    record["status"] = "running"

    def request(stage: str, slot: str, prompt: str, user: str, schema: dict[str, Any], validate: Any,
                params: dict[str, Any] | None = None) -> dict[str, Any]:
        return _request(paths, clients, record, path, echo, stage, slot, prompt, user, schema, validate, params)

    try:
        _stress_drafts(paths, record, request, "stress_recheck")
        record["provenance"]["stress"] = record["provenance"]["stress_recheck"]
        _finish_prior(paths, settings, record, request)
    except (AbductionError, AbductionPaused) as exc:
        record["status"] = "paused" if isinstance(exc, AbductionPaused) else "failed"
        record["error"] = str(exc)
        raise
    finally:
        atomic_write_text(path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    atomic_write_text(path.with_suffix(".md"), render(record))
    return path, record
