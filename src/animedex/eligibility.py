"""Load-bearing eligibility (04), the same rule as the DuckDB view `v_load_bearing`:
P3 verdict `load_bearing` AND the latest CHECK on the atom is ACCEPT (directly or after one REVISE)
AND `explanation == settled` AND `support.status` in {profile_only, episode_backed}."""

from __future__ import annotations

from typing import Any

State = dict[str, list[dict[str, Any]]]
SUPPORT_OK = ("profile_only", "episode_backed")


def latest_checks(checks: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Latest check per (target_type, target_id), in canonical key order (run_id, then created_at)."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for c in sorted(checks, key=lambda c: (c["provenance"].get("run_id", ""), c["provenance"].get("created_at", ""))):
        out[(c["target_type"], c["target_id"])] = c
    return out


def eligible_atom_ids(state: State) -> set[str]:
    proofs = {p["atom_id"]: p for p in state.get("proof", [])}
    latest = latest_checks(state.get("check", []))
    out = set()
    for m in state.get("mechanism", []):
        aid = m["atom_id"]
        proof, check = proofs.get(aid), latest.get(("mechanism", aid))
        if (proof and proof["ablation"]["verdict"] == "load_bearing" and check and check["verdict"] == "ACCEPT"
                and m.get("explanation") == "settled" and (m.get("support") or {}).get("status") in SUPPORT_OK):
            out.add(aid)
    return out
