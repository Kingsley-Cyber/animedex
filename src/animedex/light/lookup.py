"""Rebuildable ID lookup over the private scan, frame, note, and card records."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text

NODE_COLUMNS = ("id", "kind", "label", "file", "status", "source_url",
                "supporting_question", "falsifying_question")
EDGE_COLUMNS = ("from_id", "to_id", "relation")


def _records(directory: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not directory.is_dir():
        return []
    result = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"expected an object in {path}")
        result.append((path, data))
    return result


def build_lookup(paths: Paths) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    nodes: dict[str, dict[str, str]] = {}
    edges: list[dict[str, str]] = []
    edge_keys: set[tuple[str, str, str]] = set()

    def node(id_: str, kind: str, label: Any, path: Path, status: str = "", source_url: str = "",
             supporting_question: str = "", falsifying_question: str = "") -> None:
        nodes[id_] = {"id": id_, "kind": kind, "label": str(label or ""),
                      "file": str(path.relative_to(paths.root)), "status": status, "source_url": source_url,
                      "supporting_question": supporting_question, "falsifying_question": falsifying_question}

    def edge(from_id: str, to_id: str, relation: str) -> None:
        key = (from_id, to_id, relation)
        if key not in edge_keys:
            edge_keys.add(key)
            edges.append({"from_id": from_id, "to_id": to_id, "relation": relation})

    for path, data in _records(paths.notes):
        if data.get("slug"):
            node(f"note:{data['slug']}", "note", data.get("title") or data.get("premise"), path)

    for path, data in _records(paths.notes / "_scans"):
        scan_id = f"scan:{path.stem}"
        node(scan_id, "scan", data.get("as_of"), path)
        for gap in data.get("gaps") or []:
            gap_id = f"gap:{path.stem}:{gap['id']}"
            node(gap_id, "anomaly", gap.get("anomaly"), path, "candidate", str(gap.get("source_url") or ""))
            edge(scan_id, gap_id, "contains")

    for path, data in _records(paths.quick / "_frames"):
        record_id = path.stem
        scan_stem = Path(str(data.get("scan_file") or "")).stem
        gap = data.get("gap") or {}
        gap_id = f"gap:{scan_stem}:{gap.get('id')}"
        for mode, trace in (data.get("reasoning_graphs") or {}).items():
            reason_id = f"reason:{record_id}:{mode}"
            node(reason_id, "reasoning", trace.get("hypothesis"), path, "untested")
            edge(gap_id, reason_id, "asks")
            for step in trace.get("steps") or []:
                for slug in step.get("premise_ids") or []:
                    edge(f"note:{slug}", reason_id, "compares")
        for ref, hypothesis in (data.get("hypotheses") or {}).items():
            hypothesis_id = f"hypothesis:{record_id}:{ref}"
            node(hypothesis_id, "hypothesis", hypothesis.get("claim"), path,
                 str(hypothesis.get("status") or "untested"), str(gap.get("source_url") or ""),
                 str(hypothesis.get("supporting_question") or ""),
                 str(hypothesis.get("falsifying_question") or ""))
            edge(gap_id, hypothesis_id, "asks")
            edge(f"reason:{record_id}:{hypothesis['lens']}", hypothesis_id, "proposes")
            for slug in hypothesis.get("premise_ids") or []:
                edge(f"note:{slug}", hypothesis_id, "compares")
        for ref, frame in (data.get("frames") or {}).items():
            frame_id = f"frame:{record_id}:{ref}"
            node(frame_id, "frame", frame.get("frame_sentence"), path,
                 "accepted" if frame.get("accepted") else "rejected", str(gap.get("source_url") or ""))
            edge(gap_id, frame_id, "frames")
            for mode in frame.get("lens_refs") or []:
                edge(f"reason:{record_id}:{mode}", frame_id, "informs")
            for hypothesis_ref in frame.get("hypothesis_refs") or []:
                edge(f"hypothesis:{record_id}:{hypothesis_ref}", frame_id, "informs")
            gate = frame.get("gate") or {}
            gate_id = f"gate:{record_id}:{ref}"
            node(gate_id, "gate", gate.get("reason"), path,
                 "accepted" if frame.get("accepted") else "rejected")
            edge(frame_id, gate_id, "tests")

    for path, data in _records(paths.quick):
        selected = data.get("source_frame") or {}
        frame_file = Path(str(selected.get("frames_file") or ""))
        source_frame = f"frame:{frame_file.stem}:{selected.get('id')}" if selected else None
        for ref, card in (data.get("cards") or {}).items():
            card_id = f"card:{path.stem}:{ref}"
            node(card_id, "card", card.get("logline") or card.get("premise"), path,
                 "survived" if ref in (data.get("survivors") or []) else "dropped")
            if source_frame:
                edge(source_frame, card_id, "develops")
            for slug in data.get("picks") or []:
                edge(f"note:{slug}", card_id, "compares")
            check = (data.get("checks") or {}).get(ref)
            if check:
                verdict_id = f"verdict:{path.stem}:{ref}"
                node(verdict_id, "verdict", check.get("frame_reason") or check.get("explanation_reason")
                     or check.get("weakness"), path,
                     "survived" if ref in (data.get("survivors") or []) else "dropped")
                edge(card_id, verdict_id, "judged_by")

    # A missing source is visible in the lookup rather than silently lost.
    for item in edges:
        for id_ in (item["from_id"], item["to_id"]):
            if id_ not in nodes:
                nodes[id_] = {"id": id_, "kind": "missing", "label": "", "file": "",
                              "status": "missing", "source_url": "",
                              "supporting_question": "", "falsifying_question": ""}
    return nodes, sorted(edges, key=lambda item: (item["from_id"], item["to_id"], item["relation"]))


def _csv(columns: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def export_lookup(paths: Paths) -> list[Path]:
    nodes, edges = build_lookup(paths)
    outputs = [paths.exports / "ideation_nodes.csv", paths.exports / "ideation_edges.csv"]
    atomic_write_text(outputs[0], _csv(NODE_COLUMNS, [nodes[id_] for id_ in sorted(nodes)]))
    atomic_write_text(outputs[1], _csv(EDGE_COLUMNS, edges))
    return outputs


def lookup(paths: Paths, id_: str) -> dict[str, Any]:
    nodes, edges = build_lookup(paths)
    if id_ not in nodes:
        raise KeyError(id_)
    incoming: dict[str, list[dict[str, str]]] = {}
    for item in edges:
        incoming.setdefault(item["to_id"], []).append(item)
    ancestors: set[str] = set()
    pending = [id_]
    while pending:
        current = pending.pop()
        for item in incoming.get(current, []):
            parent = item["from_id"]
            if parent not in ancestors and parent != id_:
                ancestors.add(parent)
                pending.append(parent)
    connections = [item for item in edges if id_ in (item["from_id"], item["to_id"])]
    lineage_ids = ancestors | {id_}
    return {"record": nodes[id_], "connections": connections,
            "lineage": [nodes[parent] for parent in sorted(ancestors)],
            "lineage_edges": [item for item in edges if item["from_id"] in lineage_ids
                              and item["to_id"] in lineage_ids]}
