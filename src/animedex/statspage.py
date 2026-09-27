"""`animedex stats` / `make stats` (owner ruling 2026-09-27, statistics as gates): a read-only summary page,
`build/reports/stats.md`.

Each statistic replaced a check inside its own stage; this page only collects what those stages already
wrote, and never recomputes anything that depends on a model:
- reliability: `eval/agreement/reliability.json` (the AC-12 agreement eval);
- adequacy, gap ranking and field health: `build/stats/analysis.json` (`make analyze` / `make build`);
- novelty: the PMI of each champion's key pair, as recorded on the canonical idea cards (`make ideas`);
- calibration: `build/stats/calibration.json` (`make eval`);
- taste: `build/stats/taste.json` (`make review-report`);
- backtest: `build/stats/backtest.json` (`make backtest`).
A missing input says which command makes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from animedex.paths import Paths
from animedex.statgates import load_reliability, read_stage, reliability_file
from animedex.store.atomic import atomic_write_text
from animedex.store.canonical import CanonicalStore

TOP = 10


@dataclass
class StatsPage:
    path: str
    sections: dict[str, bool] = field(default_factory=dict)   # section -> has data


def _missing(what: str, command: str) -> list[str]:
    return [f"Not available yet: {what}. Run `{command}`.", ""]


def _reliability(paths: Paths) -> tuple[list[str], bool]:
    lines = ["## 1. Reliability (agreement eval)", "",
             "Cohen's kappa per enum field next to raw agreement. Grid fields need kappa of at least 0.8; a field "
             "under 0.6 is unreliable and leaves the gap reports and the novelty pairs.", ""]
    if not reliability_file(paths).is_file():
        return lines + _missing("eval/agreement/reliability.json", "make eval"), False
    fields = load_reliability(paths)
    lines += ["| Field | Pairs | Raw agreement | Kappa | Verdict |", "|---|---|---|---|---|"]
    for path, v in sorted(fields.items(), key=lambda x: (not x[1].get("unreliable"), x[1].get("pass", True), x[0])):
        verdict = "unreliable" if v.get("unreliable") else "pass" if v.get("pass") else "below the bar"
        lines.append(f"| `{path}` | {v.get('n')} | {v.get('raw')} | {v.get('kappa')} | {verdict} |")
    return lines + [""], True


def _analysis(paths: Paths) -> tuple[list[str], bool]:
    data = read_stage(paths, "analysis")
    lines = ["## 2. Adequacy (rule of three)", "",
             "A zero is open only when 3/n is below 0.02 over the subset it is counted in (n of at least 151).", ""]
    if data is None:
        empty = _missing("build/stats/analysis.json", "make analyze")
        return [*lines, *empty, "## 3. Gaps (expected count)", "", *empty, "## 4. Field health", "", *empty], False
    ad = data["adequacy"]
    lines += ["| Subset | n | 3/n | Zeros open |", "|---|---|---|---|"]
    for m, cov in ad["modules"].items():
        who = "all titles" if m == "core" else f"titles with {m}"
        lines.append(f"| {who} (good completion) | {cov['n_adequate_titles']} | {cov['rule_of_three']:.3f} | "
                     f"{'yes' if cov['adequate'] else 'no'} |")
    c = ad["census"]
    lines += [f"| census rows with a power system | {c['n_powered_census_rows']} | {c['rule_of_three']:.3f} | "
              f"{'yes' if c['adequate'] else 'no'} |", ""]
    lines += ["## 3. Gaps (expected count)", "",
              "Empty cells ranked by n × p(x) × p(y): a real gap is expected 3 or more times and never seen.", ""]
    for cq, g in sorted(data["gaps"].items()):
        if "excluded" in g:
            lines.append(f"- {cq}: excluded (unreliable: {'; '.join(g['excluded'])})")
            continue
        real = ", ".join(f"{x} × {y} ({e:.1f})" for x, y, e in g["real_gaps"][:TOP]) or "none"
        lines.append(f"- {cq} ({g['x'].split('.')[-1]} × {g['y'].split('.')[-1]}, {g['n']} {g['source']} rows, zeros "
                     f"{data['zeros_are'].get(cq)}): {len(g['real_gaps'])} real gap(s): {real}; "
                     f"{len(g['unsurprising'])} unsurprising")
    health = [h for h in data["field_health"] if h["n"]]
    low = [h["path"] for h in health if h["low_entropy"]]
    informative = sorted((h for h in health if h["mi_outcome"]), key=lambda h: (-h["mi_outcome"], h["path"]))[:5]
    lines += ["", "## 4. Field health", "",
              f"{len(health)} enum field(s) with values; {len(low)} low-entropy (normalized entropy under 0.5): "
              + (", ".join(f"`{p}`" for p in low) or "none") + ".",
              "Most informative about the outcome (mutual information, bits): "
              + (", ".join(f"`{h['path']}` {h['mi_outcome']:.3f}" for h in informative) or "none yet") + ".", ""]
    return lines, True


def _novelty(paths: Paths) -> tuple[list[str], bool]:
    lines = ["## 5. Novelty (PMI of each champion's key pair)", "",
             "A pair is novel when it co-occurs at most half as often as chance (PMI of -1 or lower) over more than "
             "150 rows (D-021).", ""]
    ideas = [i for i in CanonicalStore(paths).read("idea") if i["status"] == "champion"]
    keyed = [(i["idea_id"], i["gates"]["pmi_key_pair"]) for i in ideas if (i.get("gates") or {}).get("pmi_key_pair")]
    if not ideas:
        return lines + _missing("champion idea cards", "make ideas"), False
    lines += [f"{len(ideas)} champion(s), {len(keyed)} with a recorded key pair.", ""]
    if keyed:
        lines += ["| Idea | Key pair | PMI | Together | Rows |", "|---|---|---|---|---|"]
        for iid, k in sorted(keyed, key=lambda x: (x[1]["pmi"], x[0]))[:TOP]:
            lines.append(f"| {iid} | {' + '.join(k['pair'])} | {k['pmi']:+.2f} | {k['together']} | {k['n']} |")
        lines.append("")
    return lines, True


def _calibration(paths: Paths) -> tuple[list[str], bool]:
    lines = ["## 6. Calibration (VERIFY report)", "",
             "Brier score of the extraction's own confidence against verified correctness (D-022): 0 is perfect, a "
             "constant 0.5 scores 0.25.", ""]
    data = read_stage(paths, "calibration")
    if data is None:
        return lines + _missing("build/stats/calibration.json", "make eval"), False
    o = data["overall"]
    worst = sorted((f for f in data["fields"] if f["brier"] is not None), key=lambda f: (-f["brier"], f["path"]))[:5]
    lines += [f"Overall: Brier {o['brier'] if o['brier'] is not None else 'n/a'} over {o['checked']} checked field(s); "
              f"{o['floored']} floored confidence(s).",
              "Worst fields: " + (", ".join(f"`{f['path']}` {f['brier']:.3f} (n {f['n']})" for f in worst) or "none")
              + ".", ""]
    return lines, True


def _taste(paths: Paths) -> tuple[list[str], bool]:
    lines = ["## 7. Taste (review import)", "", "Bradley-Terry strengths from pairwise picks (your ratings and the "
             "panel's), and the judge's agreement with that ranking.", ""]
    data = read_stage(paths, "taste")
    if data is None:
        return lines + _missing("build/stats/taste.json", "make review-report"), False
    p = data["picks"]
    lines.append(f"Packet {data['date']}: {data['rated']} of {data['cards']} cards rated; picks {p['kingsley']} from "
                 f"your ratings, {p['panel']} from the panel.")
    if not data["complete"]:
        return lines + ["The arms stay hidden until every card is rated.", ""], True
    arms = ", ".join(f"{a} {v:.3f}" for a, v in sorted(data["arm_strength"].items(), key=lambda x: (-x[1], x[0])))
    agree = "n/a" if data["judge_agreement"] is None else f"{data['judge_agreement']:.2f}"
    lines += [f"Arm strengths: {arms or 'no picks across arms'}.",
              f"Judge agreement with the ranking: {agree} over {data['judge_pairs']} card pair(s).", ""]
    return lines, True


def _backtest(paths: Paths) -> tuple[list[str], bool]:
    lines = ["## 8. Backtest (retrodiction)", "",
             "The judge predicts held-out titles' outcomes with a blank brief and with the index brief; exact "
             "McNemar test on the titles only one brief got right (D-016).", ""]
    data = read_stage(paths, "backtest")
    if data is None:
        return lines + _missing("build/stats/backtest.json", "make backtest"), False
    if not data["n"]:
        return lines + [f"No title scored yet ({data['titles']} held out, {len(data['excluded'])} not scored).", ""], True
    need = data["sample_size_needed"]
    lines += [f"{data['n']} title(s) scored: accuracy {data['accuracy_blank']:.2f} blank, {data['accuracy_index']:.2f} "
              f"with the index ({data['difference']:+.2f}). Only one brief right on "
              f"{data['only_index'] + data['only_blank']} (index {data['only_index']}, blank {data['only_blank']}); "
              f"p = {data['p_value']:.4f}; sample size needed for p < 0.05: {need if need else 'n/a'}.", ""]
    return lines, True


def write_stats_page(paths: Paths) -> StatsPage:
    lines = ["# ANIMEDEX statistics", "",
             "A read-only summary. Each number is computed inside its own stage (agreement eval, analysis, novelty gate, "
             "VERIFY report, review import, backtest); this page only collects them.", ""]
    page = StatsPage(path="build/reports/stats.md")
    for name, part in (("reliability", _reliability), ("analysis", _analysis), ("novelty", _novelty),
                       ("calibration", _calibration), ("taste", _taste), ("backtest", _backtest)):
        body, have = part(paths)
        lines += body
        page.sections[name] = have
    atomic_write_text(paths.reports / "stats.md", "\n".join(lines).rstrip("\n") + "\n")
    return page


def summary_line(page: StatsPage) -> str:
    have = [k for k, v in page.sections.items() if v]
    missing = [k for k, v in page.sections.items() if not v]
    return (f"stats -> {page.path}: {len(have)} of {len(page.sections)} section(s) with data"
            + (f"; not yet: {', '.join(missing)}" if missing else ""))


__all__ = ["StatsPage", "summary_line", "write_stats_page"]
