"""Live discourse gaps, candidate frames, and a gate before idea-card scoring."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from animedex.budget import BudgetExceeded
from animedex.config import Settings
from animedex.light.ingest import web_limits
from animedex.light.notes import TEXT, _arr, _obj, index_line, read_notes
from animedex.light.premises import retrieve_premises
from animedex.paths import Paths
from animedex.prompts import read_prompt
from animedex.providers.base import ProviderError
from animedex.providers.cli_common import CliAuthError, RateLimited
from animedex.providers.client import CallContext, Completion, InvalidOutput, LLMClient
from animedex.store.atomic import atomic_write_text
from animedex.store.quarantine import quarantine
from animedex.textutil import blocked_source, norm_url, sha256_text


class AbductionError(ValueError):
    pass


class AbductionPaused(AbductionError):
    pass


def _complete(paths: Paths, client: LLMClient, pass_: str, record_id: str, prompt_file: str,
              user: str, schema: dict[str, Any], validate: Any, params: dict[str, Any] | None = None) -> Completion:
    prompt = read_prompt(paths.prompts / prompt_file)
    client.prompt_version = prompt.version
    context = CallContext(pass_=pass_, record_id=record_id, upstream=sha256_text(user))
    try:
        return client.complete_ex(prompt.body, user, schema, params, ctx=context, validate=validate)
    except InvalidOutput as exc:
        quarantine(paths.quarantine, pass_, "abduction", record_id, exc.raw, exc.errors)
        raise AbductionError(f"{pass_.lower()}: invalid answer after repair ({exc.errors[-1][:160]})") from exc
    except (BudgetExceeded, RateLimited, CliAuthError) as exc:
        raise AbductionPaused(str(exc)) from exc
    except ProviderError as exc:
        raise AbductionError(f"{pass_.lower()}: {str(exc)[:160]}") from exc


def scan_schema() -> dict[str, Any]:
    gap = _obj({"genre": TEXT, "expected_pattern": TEXT, "observation": TEXT,
                "anomaly": TEXT, "source_url": TEXT, "source_date": TEXT})
    return _obj({"gaps": _arr(gap)})


def scan_problems(out: dict[str, Any], meta: dict[str, Any], as_of: date) -> list[str]:
    fetched = {norm_url(url) for url in (meta.get("web") or {}).get("fetched") or []}
    problems: list[str] = []
    gaps = out.get("gaps") or []
    if not fetched:
        problems.append("fetch a live discourse page; a search result alone is not evidence")
    if not gaps:
        problems.append("return at least one source-backed candidate anomaly")
    seen: set[str] = set()
    for i, gap in enumerate(gaps):
        for field in ("genre", "expected_pattern", "observation", "anomaly"):
            if not str(gap.get(field) or "").strip():
                problems.append(f"gaps[{i}].{field}: give it")
        anomaly = str(gap.get("anomaly") or "").strip().casefold()
        if anomaly in seen:
            problems.append(f"gaps[{i}].anomaly: duplicate")
        seen.add(anomaly)
        url = gap.get("source_url")
        if blocked_source(url) or norm_url(url) not in fetched:
            problems.append(f"gaps[{i}].source_url: use a fetched, allowed page")
        try:
            published = date.fromisoformat(str(gap.get("source_date") or ""))
            if published > as_of:
                problems.append(f"gaps[{i}].source_date: cannot be in the future")
        except ValueError:
            problems.append(f"gaps[{i}].source_date: use YYYY-MM-DD from the page")
    return problems


def run_scan(paths: Paths, settings: Settings, *, client: LLMClient, run_id: str,
             now: datetime | None = None) -> tuple[Path, dict[str, Any]]:
    now = now or datetime.now(UTC)
    limits = web_limits(settings, 1)
    user = "\n".join([f"as_of: {now.date().isoformat()}", "landscape: current anime discourse",
                      f"limits: searches {limits['max_searches']}, fetches {limits['max_fetches']}"])
    done = _complete(paths, client, "ANOMALY_SCAN", f"scan:{run_id}", "scan.md", user,
                     scan_schema(), lambda out, meta: _raise(scan_problems(out, meta, now.date())),
                     {"web": limits})
    gaps = [{"id": f"G{i}", **gap} for i, gap in enumerate(done.data["gaps"], start=1)]
    scan_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{sha256_text(run_id).split(':')[-1][:8]}"
    record = {"id": scan_id, "created_at": now.isoformat(), "as_of": now.date().isoformat(),
              "source": "live web fetch", "web": {"queries": (done.meta.get("web") or {}).get("queries") or [],
                                                   "fetched": (done.meta.get("web") or {}).get("fetched") or []},
              "gaps": gaps}
    path = paths.notes / "_scans" / f"{scan_id}.json"
    atomic_write_text(path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return path, record


def _raise(problems: list[str]) -> None:
    if problems:
        raise ValueError("; ".join(problems))


def _read_record(paths: Paths, path: str | Path) -> tuple[Path, dict[str, Any]]:
    file = Path(path)
    if not file.is_absolute():
        file = paths.root / file
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AbductionError(f"cannot read {file}: {exc}") from exc
    if not isinstance(data, dict):
        raise AbductionError(f"invalid record: {file}")
    return file, data


def load_gap(paths: Paths, scan_file: str | Path, gap_id: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    file, scan = _read_record(paths, scan_file)
    if not file.resolve().is_relative_to((paths.notes / "_scans").resolve()):
        raise AbductionError("use a scan written under notes/_scans")
    matches = [gap for gap in scan.get("gaps") or [] if gap.get("id") == gap_id]
    if len(matches) != 1:
        raise AbductionError(f"gap {gap_id} not found in {file}")
    gap = matches[0]
    fetched = {norm_url(url) for url in (scan.get("web") or {}).get("fetched") or []}
    if norm_url(gap.get("source_url")) not in fetched:
        raise AbductionError(f"gap {gap_id} has no fetched source evidence")
    return file, scan, gap


def frames_schema() -> dict[str, Any]:
    frame = _obj({"frame_sentence": TEXT, "explanation": TEXT, "new_concept": TEXT})
    return _obj({"frames": _arr(frame)})


def frame_problems(out: dict[str, Any], n: int) -> list[str]:
    frames = out.get("frames") or []
    problems = [f"generate exactly {n} candidate frames"] if len(frames) != n else []
    sentences = [str(frame.get("frame_sentence") or "").strip() for frame in frames]
    if any(not sentence for sentence in sentences) or len({s.casefold() for s in sentences}) != len(sentences):
        problems.append("each frame needs a distinct one-sentence statement")
    for i, frame in enumerate(frames):
        if len([part for part in re.split(r"(?<=[.!?])\s+", sentences[i]) if part.strip()]) != 1:
            problems.append(f"frames[{i}].frame_sentence: use one sentence")
        if not str(frame.get("explanation") or "").strip() or not str(frame.get("new_concept") or "").strip():
            problems.append(f"frames[{i}]: explain the gap and name the new concept")
    return problems


def gate_schema(refs: list[str], note_ids: list[str]) -> dict[str, Any]:
    example = _obj({"slug": {"type": "string", "enum": note_ids}, "why_not": TEXT})
    item = _obj({"ref": {"type": "string", "enum": refs}, "explains_gap": {"type": "boolean"},
                 "parent_independent": {"type": "boolean"}, "fusion": {"type": "boolean"},
                 "anti_examples_valid": {"type": "boolean"}, "anti_examples": _arr(example), "reason": TEXT})
    return _obj({"frames": _arr(item)})


def gate_problems(out: dict[str, Any], refs: list[str], note_ids: list[str]) -> list[str]:
    frames = out.get("frames") or []
    problems = []
    if sorted(frame.get("ref") for frame in frames) != sorted(refs):
        problems.append(f"gate each frame exactly once: {refs}")
    for i, frame in enumerate(frames):
        examples = frame.get("anti_examples") or []
        slugs = [e.get("slug") for e in examples]
        if len(slugs) != 3 or len(set(slugs)) != 3 or any(slug not in note_ids for slug in slugs):
            problems.append(f"frames[{i}].anti_examples: three distinct indexed shows")
        if any(not str(e.get("why_not") or "").strip() for e in examples):
            problems.append(f"frames[{i}].anti_examples: explain each contrast")
        if not str(frame.get("reason") or "").strip():
            problems.append(f"frames[{i}].reason: explain the gate verdict")
    return problems


def passes_gate(verdict: dict[str, Any]) -> bool:
    return bool(verdict.get("explains_gap") and verdict.get("parent_independent")
                and not verdict.get("fusion") and verdict.get("anti_examples_valid"))


def run_abduct(paths: Paths, *, scan_file: str | Path, gap_id: str, n: int,
               clients: dict[str, LLMClient], run_id: str, now: datetime | None = None) -> tuple[Path, dict[str, Any]]:
    file, scan, gap = load_gap(paths, scan_file, gap_id)
    notes = read_notes(paths)
    if len(notes) < 3:  # the owner's frame gate asks for three contrasting shows
        raise AbductionError("frame gate needs three indexed shows; run make ingest or make data-pull")
    if n < 1:
        raise AbductionError("request at least one frame")
    source = f"{gap['source_url']} (published {gap['source_date']})"
    context = "\n".join([f"genre: {gap['genre']}", f"expected: {gap['expected_pattern']}",
                         f"observed: {gap['observation']}", f"anomaly: {gap['anomaly']}",
                         f"discourse source: {source}"])
    user = f"{context}\nframes: {n}"
    key = f"{scan['id']}:{gap_id}:{n}"
    generated = _complete(paths, clients["generate"], "ABDUCT", key, "abduct.md", user,
                          frames_schema(), lambda out: _raise(frame_problems(out, n)))
    candidates = {f"F{i}": frame for i, frame in enumerate(generated.data["frames"], start=1)}
    gate_user = "\n".join([context, *(f"frame {ref}: {frame['frame_sentence']} | explanation: "
                                     f"{frame['explanation']} | new concept: {frame['new_concept']}"
                                     for ref, frame in candidates.items()),
                           *(index_line(note) for note in notes.values())])
    gated = _complete(paths, clients["check"], "FRAME_GATE", key, "frame_gate.md", gate_user,
                      gate_schema(list(candidates), list(notes)),
                      lambda out: _raise(gate_problems(out, list(candidates), list(notes))))
    verdicts = {item["ref"]: item for item in gated.data["frames"]}
    frames = {ref: {**frame, "gate": verdicts[ref], "accepted": passes_gate(verdicts[ref])}
              for ref, frame in candidates.items()}
    now = now or datetime.now(UTC)
    frame_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{sha256_text(key).split(':')[-1][:8]}"
    record = {"id": frame_id, "run_id": run_id, "created_at": now.isoformat(),
              "scan_file": str(file.relative_to(paths.root)),
              "gap": gap, "frames": frames, "accepted_ids": [ref for ref, frame in frames.items() if frame["accepted"]]}
    path = paths.quick / "_frames" / f"{frame_id}.json"
    atomic_write_text(path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return path, record


def load_selected_frame(paths: Paths, frames_file: str | Path, frame_id: str) -> dict[str, Any]:
    file, record = _read_record(paths, frames_file)
    if not file.resolve().is_relative_to((paths.quick / "_frames").resolve()):
        raise AbductionError("use a frame file written under build/quick/_frames")
    frame = (record.get("frames") or {}).get(frame_id)
    if not isinstance(frame, dict) or not frame.get("accepted") or not passes_gate(frame.get("gate") or {}):
        raise AbductionError(f"frame {frame_id} is missing or did not pass the frame gate")
    if record.get("workflow") == "research_v1":
        gate = frame["gate"]
        graph = record.get("state_graph") or {}
        ids = {node.get("id") for node in graph.get("nodes") or [] if isinstance(node, dict)}
        if not (gate.get("evidence_grounded") and gate.get("reasoning_consistent")
                and f"frame:{frame_id}" in ids):
            raise AbductionError(f"frame {frame_id} lacks research gate or state-graph proof")
    gap = record.get("gap") or {}
    if not frame.get("frame_sentence") or not gap.get("anomaly") or not gap.get("source_url"):
        raise AbductionError(f"frame {frame_id} has incomplete provenance")
    _, _, source_gap = load_gap(paths, record.get("scan_file") or "", gap.get("id") or "")
    if source_gap != gap:
        raise AbductionError(f"frame {frame_id} no longer matches its sourced gap")
    return {"id": frame_id, "sentence": frame["frame_sentence"], "anomaly": gap["anomaly"],
            "source_url": gap["source_url"], "frames_file": str(file.relative_to(paths.root))}


LENSES = ("abductive", "deductive", "inductive")


def lens_schema(note_ids: list[str]) -> dict[str, Any]:
    step = _obj({"claim": TEXT, "premise_ids": _arr({"type": "string", "enum": note_ids})})
    return _obj({"hypothesis": TEXT, "steps": _arr(step)})


def lens_problems(out: dict[str, Any], note_ids: list[str]) -> list[str]:
    steps = out.get("steps") or []
    problems = [] if str(out.get("hypothesis") or "").strip() and steps else ["give a hypothesis and reasoning steps"]
    for i, step in enumerate(steps):
        refs = step.get("premise_ids") or []
        if not str(step.get("claim") or "").strip() or not refs or any(ref not in note_ids for ref in refs):
            problems.append(f"steps[{i}]: cite indexed premises for a nonempty claim")
    return problems


def research_frames_schema() -> dict[str, Any]:
    frame = _obj({"frame_sentence": TEXT, "explanation": TEXT, "new_concept": TEXT,
                  "lens_refs": _arr({"type": "string", "enum": list(LENSES)})})
    return _obj({"frames": _arr(frame)})


def research_frame_problems(out: dict[str, Any], n: int) -> list[str]:
    problems = frame_problems(out, n)
    for i, frame in enumerate(out.get("frames") or []):
        refs = frame.get("lens_refs") or []
        if not refs or len(set(refs)) != len(refs) or any(ref not in LENSES for ref in refs):
            problems.append(f"frames[{i}].lens_refs: cite contributing reasoning lenses")
    return problems


def suspension_schema(refs: list[str]) -> dict[str, Any]:
    ref = {"type": "string", "enum": refs}
    comparison = _obj({"left": ref, "right": ref,
                       "relation": {"type": "string", "enum": ["tension", "compatible", "independent"]},
                       "reason": TEXT})
    synthesis = _obj({"frame_sentence": TEXT, "explanation": TEXT, "new_concept": TEXT,
                      "parents": _arr(ref)})
    return _obj({"comparisons": _arr(comparison), "syntheses": _arr(synthesis)})


def suspension_problems(out: dict[str, Any], refs: list[str]) -> list[str]:
    comparisons = out.get("comparisons") or []
    problems = [] if comparisons else ["compare the suspended candidates before gating"]
    tensions = {frozenset((item.get("left"), item.get("right"))) for item in comparisons
                if item.get("relation") == "tension"}
    for i, item in enumerate(comparisons):
        if item.get("left") == item.get("right") or not str(item.get("reason") or "").strip():
            problems.append(f"comparisons[{i}]: compare distinct frames and explain the relation")
    for i, item in enumerate(out.get("syntheses") or []):
        parents = item.get("parents") or []
        if len(set(parents)) < 2 or any(ref not in refs for ref in parents):
            problems.append(f"syntheses[{i}].parents: cite distinct suspended frames")
        if not any(tension.issubset(parents) for tension in tensions):
            problems.append(f"syntheses[{i}].parents: synthesize a compared tension")
        problems += [f"syntheses[{i}].{p}" for p in frame_problems({"frames": [item]}, 1)]
    return problems


def research_gate_schema(refs: list[str], note_ids: list[str]) -> dict[str, Any]:
    schema = gate_schema(refs, note_ids)
    item = schema["properties"]["frames"]["items"]
    item["properties"].update({"evidence_grounded": {"type": "boolean"},
                               "reasoning_consistent": {"type": "boolean"}})
    item["required"].extend(["evidence_grounded", "reasoning_consistent"])
    return schema


def passes_research_gate(verdict: dict[str, Any]) -> bool:
    return passes_gate(verdict) and bool(verdict.get("evidence_grounded") and verdict.get("reasoning_consistent"))


def controller_direction(frames: dict[str, dict[str, Any]]) -> str:
    rejected = [frame["gate"] for frame in frames.values() if not frame["accepted"]]
    directions = []
    if any(not gate["explains_gap"] for gate in rejected):
        directions.append("make the causal explanation account for the observed gap")
    if any(gate["fusion"] or not gate["parent_independent"] for gate in rejected):
        directions.append("remove parent-show recognition and familiar-part fusion")
    if any(not gate["anti_examples_valid"] for gate in rejected):
        directions.append("make the frame distinguishable from the indexed contrasts")
    if any(not gate["evidence_grounded"] or not gate["reasoning_consistent"] for gate in rejected):
        directions.append("ground each claim in the scan and cited note premises")
    return "; ".join(directions)


def _research_gate(paths: Paths, *, client: LLMClient, key: str, context: str,
                   candidates: dict[str, dict[str, Any]], notes: dict[str, dict[str, Any]],
                   lenses: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    user = "\n".join([context,
                       *(f"lens {mode}: {json.dumps(trace, ensure_ascii=False)}" for mode, trace in lenses.items()),
                       *(f"frame {ref}: {json.dumps(frame, ensure_ascii=False)}" for ref, frame in candidates.items()),
                       *(index_line(note) for note in notes.values())])
    done = _complete(paths, client, "RESEARCH_GATE", key, "research_gate.md", user,
                     research_gate_schema(list(candidates), list(notes)),
                     lambda out: _raise(gate_problems(out, list(candidates), list(notes))))
    return {item["ref"]: item for item in done.data["frames"]}


def _state_graph(gap: dict[str, Any], premises: dict[str, Any], lenses: dict[str, dict[str, Any]],
                 candidates: dict[str, dict[str, Any]], suspension: dict[str, Any],
                 frames: dict[str, dict[str, Any]], revised_from: dict[str, str]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = [{"id": "gap", "kind": "observation", "text": gap["anomaly"],
                                   "source_url": gap["source_url"]}]
    edges: list[dict[str, str]] = []
    for slug in premises["selected_note_ids"]:
        nodes.append({"id": f"premise:{slug}", "kind": "premise", "note_id": slug})
    for mode, trace in lenses.items():
        for i, step in enumerate(trace["steps"], start=1):
            node_id = f"reason:{mode}:{i}"
            nodes.append({"id": node_id, "kind": "reason", "mode": mode, "text": step["claim"]})
            edges.append({"from": "gap" if i == 1 else f"reason:{mode}:{i - 1}",
                          "to": node_id, "relation": "informs"})
            edges.extend({"from": f"premise:{slug}", "to": node_id, "relation": "cites"}
                         for slug in step["premise_ids"])
    for ref, frame in candidates.items():
        nodes.append({"id": f"frame:{ref}", "kind": "candidate", "text": frame["frame_sentence"]})
        edges.extend({"from": f"reason:{mode}:{len(lenses[mode]['steps'])}", "to": f"frame:{ref}",
                      "relation": "informs"} for mode in frame["lens_refs"])
    for i, comparison in enumerate(suspension["comparisons"], start=1):
        node_id = f"comparison:{i}"
        nodes.append({"id": node_id, "kind": "comparison", "text": comparison["reason"],
                      "relation": comparison["relation"]})
        edges.extend({"from": f"frame:{comparison[side]}", "to": node_id, "relation": "compares"}
                     for side in ("left", "right"))
    for ref, frame in frames.items():
        if ref not in candidates:
            nodes.append({"id": f"frame:{ref}", "kind": "revision" if ref in revised_from else "synthesis",
                          "text": frame["frame_sentence"]})
            if ref in revised_from:
                edges.append({"from": f"frame:{revised_from[ref]}", "to": f"frame:{ref}",
                              "relation": "revises"})
                edges.append({"from": f"gate:{revised_from[ref]}", "to": f"frame:{ref}",
                              "relation": "directs_revision"})
            else:
                parents = frame.get("parents") or []
                edges.extend({"from": f"frame:{parent}", "to": f"frame:{ref}",
                              "relation": "synthesizes"} for parent in parents)
                edges.extend({"from": f"comparison:{i}", "to": f"frame:{ref}",
                              "relation": "informs_synthesis"}
                             for i, comparison in enumerate(suspension["comparisons"], start=1)
                             if {comparison["left"], comparison["right"]}.issubset(parents))
        nodes.append({"id": f"gate:{ref}", "kind": "criticism", "text": frame["gate"]["reason"],
                      "accepted": frame["accepted"]})
        edges.append({"from": f"frame:{ref}", "to": f"gate:{ref}", "relation": "tests"})
    ids = [node["id"] for node in nodes]
    positions = {node_id: i for i, node_id in enumerate(ids)}
    if len(positions) != len(ids) or any(edge["from"] not in positions or edge["to"] not in positions
                                         or positions[edge["from"]] >= positions[edge["to"]] for edge in edges):
        raise AbductionError("research state graph has a missing or backward dependency")
    return {"nodes": nodes, "edges": edges}


def run_research_abduct(paths: Paths, *, scan_file: str | Path, gap_id: str, n: int,
                        clients: dict[str, LLMClient], run_id: str,
                        now: datetime | None = None) -> tuple[Path, dict[str, Any]]:
    """Sourced gap -> premise chain -> three independent lenses -> suspended frames -> gate -> revision."""
    file, scan, gap = load_gap(paths, scan_file, gap_id)
    notes = read_notes(paths)
    if len(notes) < 3:
        raise AbductionError("frame gate needs three indexed shows; run make ingest or make data-pull")
    if n < 2:
        raise AbductionError("research mode needs at least two frames to compare")
    key = f"research:{scan['id']}:{gap_id}:{n}"
    premises = retrieve_premises(gap, notes, count=n, seed=key)
    selected = premises["selected_note_ids"]
    context = "\n".join([f"genre: {gap['genre']}", f"expected: {gap['expected_pattern']}",
                         f"observed: {gap['observation']}", f"anomaly: {gap['anomaly']}",
                         f"discourse source: {gap['source_url']} (published {gap['source_date']})",
                         *(index_line(notes[slug]) for slug in selected)])
    lenses: dict[str, dict[str, Any]] = {}
    for mode in LENSES:
        user = f"reasoning mode: {mode}\n{context}"
        done = _complete(paths, clients["generate"], f"REASON_{mode.upper()}", f"{key}:{mode}",
                         "reason_lens.md", user, lens_schema(selected),
                         lambda out: _raise(lens_problems(out, selected)))
        lenses[mode] = done.data
    frame_user = "\n".join([context, f"frames: {n}",
                            *(f"{mode} hypothesis: {json.dumps(trace, ensure_ascii=False)}"
                              for mode, trace in lenses.items())])
    generated = _complete(paths, clients["generate"], "RESEARCH_FRAMES", key, "research_frames.md",
                          frame_user, research_frames_schema(),
                          lambda out: _raise(research_frame_problems(out, n)))
    candidates = {f"F{i}": frame for i, frame in enumerate(generated.data["frames"], start=1)}
    suspension_user = "\n".join([context,
                                 *(f"frame {ref}: {json.dumps(frame, ensure_ascii=False)}"
                                   for ref, frame in candidates.items())])
    suspended = _complete(paths, clients["generate"], "SUSPEND", key, "suspend.md", suspension_user,
                          suspension_schema(list(candidates)),
                          lambda out: _raise(suspension_problems(out, list(candidates))))
    suspension = suspended.data
    all_candidates = dict(candidates)
    for i, frame in enumerate(suspension["syntheses"], start=1):
        all_candidates[f"S{i}"] = frame
    verdicts = _research_gate(paths, client=clients["check"], key=f"{key}:initial", context=context,
                              candidates=all_candidates, notes=notes, lenses=lenses)
    frames = {ref: {**frame, "gate": verdicts[ref], "accepted": passes_research_gate(verdicts[ref])}
              for ref, frame in all_candidates.items()}
    direction = controller_direction(frames)
    revised_from: dict[str, str] = {}
    if direction:
        rejected = {ref: frame for ref, frame in frames.items() if not frame["accepted"]}
        user = "\n".join([context, f"controller direction: {direction}",
                          *(f"rejected {ref}: {json.dumps(frame, ensure_ascii=False)}"
                            for ref, frame in rejected.items()),
                          f"replacement frames: {len(rejected)}"])
        adapted = _complete(paths, clients["generate"], "ADAPT_FRAMES", key, "adapt_frames.md", user,
                            research_frames_schema(),
                            lambda out: _raise(research_frame_problems(out, len(rejected))))
        revisions = {f"R{i}": frame for i, frame in enumerate(adapted.data["frames"], start=1)}
        revised_from = dict(zip(revisions, rejected, strict=True))
        revised_verdicts = _research_gate(paths, client=clients["check"], key=f"{key}:adapt",
                                         context=context, candidates=revisions, notes=notes, lenses=lenses)
        frames.update({ref: {**frame, "gate": revised_verdicts[ref],
                             "accepted": passes_research_gate(revised_verdicts[ref])}
                       for ref, frame in revisions.items()})
    graph = _state_graph(gap, premises, lenses, candidates, suspension, frames, revised_from)
    now = now or datetime.now(UTC)
    record_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{sha256_text(key).split(':')[-1][:8]}"
    while (paths.quick / "_frames" / f"{record_id}.json").exists():
        record_id += "b"
    record = {"id": record_id, "workflow": "research_v1", "run_id": run_id,
              "created_at": now.isoformat(), "scan_file": str(file.relative_to(paths.root)),
              "gap": gap, "premise_retrieval": premises, "reasoning_graphs": lenses,
              "suspension": suspension, "controller": {"direction": direction or "stop: no rejected frames",
                                                 "revised_from": revised_from},
              "state_graph": graph, "frames": frames,
              "accepted_ids": [ref for ref, frame in frames.items() if frame["accepted"]]}
    path = paths.quick / "_frames" / f"{record_id}.json"
    atomic_write_text(path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    return path, record
