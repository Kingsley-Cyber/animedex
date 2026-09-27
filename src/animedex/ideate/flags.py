"""Contested-evidence flags on idea cards (controls A8, M5).

A card leans on the atoms behind its `atoms_used` transfers. It carries a visible flag when any of
them is now contested or gone: the atom's latest CHECK verdict is CONTESTED or REJECT, its
explanation is `contested`, its transfer or source atom has left the index, or (from M6) episodes
contradict it (`support.status: contradicted`, the hook below). Flags are computed from the current
canonical state each time a report is written, so a status change shows at once. They are never
shown in the blind packet, where they would reveal the arm.
"""

from __future__ import annotations

from typing import Any

from animedex.eligibility import latest_checks

FLAG_VERDICTS = ("CONTESTED", "REJECT")


def episode_contradicted(atom: dict[str, Any]) -> bool:
    """M6 hook: ROLLUP sets `support.status: contradicted` (>=2 contradicting episodes, no support)."""
    return (atom.get("support") or {}).get("status") == "contradicted"


class EvidenceFlags:
    def __init__(self, state: dict[str, list[dict[str, Any]]]):
        self.transfers = {t["transfer_id"]: t for t in state.get("transfer", [])}
        self.atoms = {m["atom_id"]: m for m in state.get("mechanism", [])}
        self.latest = latest_checks(state.get("check", []))

    def atom_reasons(self, transfer_id: str) -> tuple[str, list[str]]:
        """(source atom id, reasons it is flagged); no reasons means the atom stands."""
        t = self.transfers.get(transfer_id)
        if t is None:
            return transfer_id, ["no longer in the index"]
        aid = t["source_atom_id"]
        atom = self.atoms.get(aid)
        if atom is None:
            return aid, ["source atom no longer in the index"]
        reasons = []
        check = self.latest.get(("mechanism", aid))
        if check and check["verdict"] in FLAG_VERDICTS:
            reasons.append(f"latest CHECK {check['verdict']}")
        if atom.get("explanation") == "contested":
            reasons.append("explanation contested")
        if episode_contradicted(atom):
            reasons.append("contradicted by episodes")
        return aid, reasons

    def for_card(self, card: dict[str, Any]) -> list[str]:
        out = []
        for tid in card.get("atoms_used") or []:
            aid, reasons = self.atom_reasons(tid)
            if reasons:
                out.append(f"{aid} ({'; '.join(reasons)})")
        return out
