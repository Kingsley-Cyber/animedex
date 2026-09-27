"""build/reports/ideas.md: the idea cards in plain language, champions first.

While the gold blind is pending, gold titles appear only as "[gold title]" (owner ruling
2026-09-27): no gold-title output is shown, only ideas. A card that leans on an atom now contested,
rejected or (M6) contradicted carries a visible evidence flag (controls A8), computed from the
current canonical state at every write. Each card shows the PMI of the key pair the novelty gate
judged it by (statistics as gates, item 4). Only ANIMEDEX cards are listed; baseline cards exist
only for the blind review.
"""

from __future__ import annotations

import re
from typing import Any

from animedex.gold import masked_titles
from animedex.guards import load_corpus
from animedex.ideate.flags import EvidenceFlags
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text
from animedex.store.canonical import CanonicalStore

OPERATOR_WORDS = {
    "reverse_incentive": "reversed incentive", "redistribute_knowledge": "moved the secret",
    "transfer_cost": "moved the cost onto someone else", "change_rule": "changed one rule",
    "combine_mechanisms": "combined two engines", "import_lane": "imported a pattern from another medium",
    "revive_execution_flop": "revived a flop's premise with a proven engine",
    "borrow_system": "borrowed an everyday system as a power",
}
CRITERIA = {"T1": "never done", "T2": "done, never this way", "T3": "two ideas that work together",
            "T4": "should have existed years ago", "T5": "a known story retold better"}


class Masker:
    def __init__(self, titles: dict[str, dict[str, Any]], hidden: set[str]):
        self.hidden = hidden
        names = []
        for tid in hidden:
            names.append(tid)
            if tid in titles:
                names.append(str(titles[tid]["title"]))
        self.pattern = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)), re.I) if names else None
        self.titles = titles

    def title(self, tid: str | None) -> str:
        if not tid:
            return ""
        if tid in self.hidden:
            return "[gold title]"
        return str(self.titles.get(tid, {}).get("title", tid))

    def text(self, value: Any) -> str:
        text = str(value or "")
        return self.pattern.sub("[gold title]", text) if self.pattern else text


def pair_words(item: str) -> str:
    """`power_combat.gate=contract` -> `gate contract`; `bridge:core_tension` -> `pattern core_tension`."""
    if item.startswith("bridge:"):
        return f"pattern {item[7:]}"
    path, _, value = item.partition("=")
    return f"{path.split('.')[-1].replace('_', ' ')} {value}"


def novelty_line(key: dict[str, Any]) -> str:
    a, b = (pair_words(x) for x in key["pair"])
    rows = "titles" if key["basis"] == "bridge" else "titles and census rows"
    return (f"**Novelty.** {a} with {b}: together {key['together']} time(s) in {key['n']} {rows} (PMI "
            f"{key['pmi']:+.2f}; -1 or lower means at most half as often as chance).")


def _fitness_key(card: dict[str, Any], archive: dict[str, dict[str, Any]]) -> tuple:
    rec = archive.get(card["grid_cell"])
    fit = rec["fitness"] if rec and rec["idea_id"] == card["idea_id"] else []
    return (card["status"] != "champion", [-x for x in fit], card["idea_id"])


def render(paths: Paths, limit: int = 60) -> str:
    state = CanonicalStore(paths).state()
    titles = {t["title_id"]: t for t in state.get("title", [])}
    corpus = load_corpus(paths)
    m = Masker(titles, masked_titles(paths, {t for t, e in corpus.items() if "gold" in e.role_tags}))
    archive = {a["cell_key"]: a for a in state.get("archive", [])}
    flags = EvidenceFlags(state)
    own = [i for i in state.get("idea", []) if i.get("arm", "animedex") == "animedex"]
    ideas = [i for i in own if i["status"] != "rejected"]
    ideas.sort(key=lambda c: _fitness_key(c, archive))
    rejected = sum(1 for i in own if i["status"] == "rejected")
    champions = sum(1 for i in ideas if i["status"] == "champion")
    lines = ["# ANIMEDEX idea cards", "",
             f"{champions} champions (the best card in each cell of the idea grid), {len(ideas) - champions} other "
             f"cards that passed every gate, {rejected} rejected. Built from {len(titles)} indexed titles.", ""]
    if m.hidden:
        lines += ["Gold titles show as [gold title] until you say \"annotations done\" or \"annotations waived\".", ""]
    if not ideas:
        lines += ["No cards yet. Run `make ideas` after the corpus has been through the full pipeline.", ""]
    for n, c in enumerate(ideas[:limit], start=1):
        e, q = c["engine"], c["consequences"]
        tag = "champion" if c["status"] == "champion" else "passed all gates"
        lines += [f"## {n}. {m.text(c['logline'])}", "", f"*{tag}; {c['grid_cell'].replace('|', ', ')}*", ""]
        flagged = flags.for_card(c)
        if flagged:
            lines += [f"**Evidence flag.** It leans on evidence that no longer stands: {m.text('; '.join(flagged))}. "
                      "Re-check it before developing this idea.", ""]
        lines += [f"**Premise.** {m.text(c['premise'])}", "",
                  f"**Engine.** Wants {m.text(e['goal'])}, but {m.text(e['constraint'])}. Chooses {m.text(e['strategy'])}; "
                  f"gains {m.text(e['benefit'])}, pays {m.text(e['cost'])}. Dilemma: {m.text(e['dilemma'])} "
                  f"*{m.text(e['dramatic_question'])}*", "",
                  f"**What's new.** {OPERATOR_WORDS.get(c['transformation']['operator'], c['transformation']['operator'])}: "
                  f"{m.text(c['transformation']['what_changed'])} Closest existing: {m.title(c['closest_existing'])}. "
                  f"{m.text(c['why_not_a_clone'])}", "",
                  f"**How it plays differently.** Choices: {m.text(q['choices'])} Relationships: "
                  f"{m.text(q['relationships'])} Outcomes: {m.text(q['outcomes'])}", ""]
        if c["gates"].get("pmi_key_pair"):
            lines += [novelty_line(c["gates"]["pmi_key_pair"]), ""]
        if c["taste"]["criteria_met"]:
            lines += ["**Taste.** " + " ".join(f"{t} ({CRITERIA[t]}): {m.text(c['taste']['evidence'].get(t))}."
                                               for t in c["taste"]["criteria_met"]), ""]
        if c.get("runway"):
            lines += [f"**Runway (does the cost still hurt by arc 5?).** {'Yes' if c['runway']['hurts_by_arc5'] else 'No'}: "
                      f"{m.text(c['runway']['reason'])}", ""]
        if c.get("premortem"):
            lines += ["**Pre-mortem.** " + " ".join(f"Risk: {m.text(p['risk'])} (like {m.title(p['source_title_id'])}); "
                                                    f"fix: {m.text(p['mitigation'])}." for p in c["premortem"]), ""]
        if c.get("revival_of"):
            lines += [f"**Revives.** {m.title(c['revival_of']['title_id'])}: {m.text(c['revival_of']['improvement'])}", ""]
    return "\n".join(lines) + "\n"


def write_report(paths: Paths) -> str:
    text = render(paths)
    atomic_write_text(paths.reports / "ideas.md", text)
    return text
