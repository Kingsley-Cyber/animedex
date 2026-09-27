"""Blind review page (owner ruling 2026-09-27): a small local page, localhost only.

`animedex review` serves the latest packet on http://127.0.0.1:<port>. One card at a time,
logline + premise only (no source, no arm). Keyboard-driven:
  1-5 rating   y / n greenlight   t then 1-5 toggle T1-T5   right or j next, left or k back
Every change is saved at once to eval/blind/ratings_<date>.yaml. The server binds 127.0.0.1 only
and loads nothing from the internet.

`animedex review --summary` (`make review-report`) is the review import (statistics as gates, item 7):
Kingsley's 1-5 ratings become pairwise picks (the higher rating wins; ties and unrated cards are
skipped, D-017), joined by any panel pick files `eval/panel/*.json` (`{"picks": [{"winner", "loser"}]}`,
packet card ids). Bradley-Terry strengths come per card and per arm (the arms from the answer key in
data/blind/), and the judge's own ordering (each card's fitness without the human rating: gates
passed, taste criteria kept, lower structural overlap, from the idea records) is measured against
that ranking. Written to build/reports/taste.md and build/stats/taste.json. Until every card is
rated the report gives counts only, so no arm is revealed mid-review.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from animedex import stats
from animedex.paths import Paths
from animedex.store.atomic import atomic_write_text

CRITERIA = ["T1", "T2", "T3", "T4", "T5"]


def latest_packet(blind_dir: Path) -> Path:
    packets = sorted(blind_dir.glob("packet_*.json"))
    if not packets:
        raise FileNotFoundError("no blind packet yet: run `make packet` after `make ideas`")
    return packets[-1]


class Store:
    """Ratings for one packet, kept in eval/blind/ratings_<date>.yaml."""

    def __init__(self, packet_file: Path):
        self.packet = json.loads(packet_file.read_text(encoding="utf-8"))
        self.path = packet_file.with_name(f"ratings_{self.packet['date']}.yaml")
        self.lock = threading.Lock()
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) if self.path.is_file() else None
        cards = (data or {}).get("cards") or {}
        self.ratings = {c["id"]: {"rating": None, "greenlight": None, "criteria": []} | (cards.get(c["id"]) or {})
                        for c in self.packet["cards"]}

    def update(self, card_id: str, change: dict[str, Any]) -> dict[str, Any]:
        if card_id not in self.ratings:
            raise KeyError(card_id)
        r = dict(self.ratings[card_id])
        if "rating" in change:
            value = change["rating"]
            if value is not None and not (isinstance(value, int) and 1 <= value <= 5):
                raise ValueError("rating must be 1-5")
            r["rating"] = value
        if "greenlight" in change:
            if change["greenlight"] not in (True, False, None):
                raise ValueError("greenlight must be true or false")
            r["greenlight"] = change["greenlight"]
        if "criteria" in change:
            crit = sorted(set(change["criteria"] or []))
            if any(c not in CRITERIA for c in crit):
                raise ValueError("criteria must be T1-T5")
            r["criteria"] = crit
        with self.lock:
            self.ratings[card_id] = r
            lines = [f"# Ratings for packet_{self.packet['date']} (saved by the review page).", "cards:"]
            for cid in sorted(self.ratings):
                x = self.ratings[cid]
                lines.append(f"  {cid}: {json.dumps({'rating': x['rating'], 'greenlight': x['greenlight'], 'criteria': x['criteria']})}")
            atomic_write_text(self.path, "\n".join(lines) + "\n")
        return r


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Blind review</title>
<style>
:root { --bg:#f7f5f0; --fg:#1d1d1b; --muted:#6b6860; --card:#ffffff; --line:#e3dfd4; --accent:#b4441c; --on:#1f6f43; }
@media (prefers-color-scheme: dark) { :root { --bg:#161513; --fg:#ece9e1; --muted:#9c978b; --card:#201f1c; --line:#34322d; --accent:#e0703f; --on:#5cc28a; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:18px/1.55 -apple-system, "Segoe UI", system-ui, sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 32px 20px 80px; }
header { display:flex; justify-content:space-between; align-items:baseline; color:var(--muted); font-size:14px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:28px; margin-top:16px; }
.id { color:var(--muted); font-size:14px; letter-spacing:.04em; }
.logline { font-size:22px; font-weight:650; margin:8px 0 14px; }
.premise { margin:0; }
.row { display:flex; gap:10px; flex-wrap:wrap; margin-top:18px; align-items:center; }
.label { color:var(--muted); font-size:14px; min-width:92px; }
.pill { border:1px solid var(--line); border-radius:999px; padding:4px 12px; font-size:15px; cursor:pointer; user-select:none; }
.pill.on { background:var(--accent); border-color:var(--accent); color:#fff; }
.pill.yes.on { background:var(--on); border-color:var(--on); }
.help { color:var(--muted); font-size:14px; margin-top:22px; }
.bar { height:4px; background:var(--line); border-radius:4px; margin-top:10px; overflow:hidden; }
.bar i { display:block; height:100%; background:var(--accent); width:0; }
kbd { border:1px solid var(--line); border-bottom-width:2px; border-radius:5px; padding:0 5px; font-size:13px; }
.saved { color:var(--on); font-size:13px; }
</style></head>
<body><main>
<header><span id="pos"></span><span id="done"></span><span class="saved" id="saved"></span></header>
<div class="bar"><i id="bar"></i></div>
<section class="card" id="card"></section>
<p class="help"><kbd>1</kbd>-<kbd>5</kbd> rating &nbsp; <kbd>y</kbd>/<kbd>n</kbd> greenlight &nbsp; <kbd>t</kbd> then <kbd>1</kbd>-<kbd>5</kbd> toggle T1-T5 &nbsp;
<kbd>&rarr;</kbd>/<kbd>j</kbd> next, <kbd>&larr;</kbd>/<kbd>k</kbd> back. Saved as you go.<br>
T1 never done &middot; T2 done, never this way &middot; T3 two ideas that work together &middot; T4 should have existed years ago &middot; T5 a known story retold better</p>
</main>
<script>
let cards = [], ratings = {}, i = 0, tagMode = false;
const el = id => document.getElementById(id);
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function rated(r) { return r && r.rating && r.greenlight !== null && r.greenlight !== undefined; }
function render() {
  const c = cards[i], r = ratings[c.id] || {};
  el("pos").textContent = `Card ${i + 1} of ${cards.length}`;
  const n = cards.filter(x => rated(ratings[x.id])).length;
  el("done").textContent = `${n} rated`;
  el("bar").style.width = `${Math.round(100 * n / cards.length)}%`;
  const pills = [1,2,3,4,5].map(v => `<span class="pill ${r.rating === v ? "on" : ""}" data-rating="${v}">${v}</span>`).join("");
  const gl = `<span class="pill yes ${r.greenlight === true ? "on" : ""}" data-gl="1">yes</span><span class="pill ${r.greenlight === false ? "on" : ""}" data-gl="0">no</span>`;
  const tags = ["T1","T2","T3","T4","T5"].map(t => `<span class="pill ${(r.criteria || []).includes(t) ? "on" : ""}" data-tag="${t}">${t}</span>`).join("");
  el("card").innerHTML = `<div class="id">${esc(c.id)}</div><div class="logline">${esc(c.logline)}</div><p class="premise">${esc(c.premise)}</p>
    <div class="row"><span class="label">Rating</span>${pills}</div>
    <div class="row"><span class="label">Greenlight</span>${gl}</div>
    <div class="row"><span class="label">Taste${tagMode ? " (pick 1-5)" : ""}</span>${tags}</div>`;
}
async function save(change) {
  const c = cards[i];
  const res = await fetch("/api/rate", {method: "POST", headers: {"Content-Type": "application/json"},
                                        body: JSON.stringify({id: c.id, change})});
  if (res.ok) { ratings[c.id] = await res.json(); el("saved").textContent = "saved"; setTimeout(() => el("saved").textContent = "", 900); }
  render();
}
function toggle(t) { const cur = new Set((ratings[cards[i].id] || {}).criteria || []); cur.has(t) ? cur.delete(t) : cur.add(t); save({criteria: [...cur]}); }
document.addEventListener("keydown", e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key;
  if (tagMode && "12345".includes(k)) { tagMode = false; toggle("T" + k); return; }
  if (k === "t") { tagMode = !tagMode; render(); return; }
  tagMode = false;
  if ("12345".includes(k) && k.length === 1) save({rating: Number(k)});
  else if (k === "y") save({greenlight: true});
  else if (k === "n") save({greenlight: false});
  else if (k === "ArrowRight" || k === "j") { i = Math.min(cards.length - 1, i + 1); render(); }
  else if (k === "ArrowLeft" || k === "k") { i = Math.max(0, i - 1); render(); }
});
document.addEventListener("click", e => {
  const t = e.target;
  if (t.dataset.rating) save({rating: Number(t.dataset.rating)});
  else if (t.dataset.gl) save({greenlight: t.dataset.gl === "1"});
  else if (t.dataset.tag) toggle(t.dataset.tag);
});
fetch("/api/packet").then(r => r.json()).then(d => {
  cards = d.cards; ratings = d.ratings;
  const first = cards.findIndex(c => !rated(ratings[c.id])); i = first < 0 ? 0 : first; render();
});
</script></body></html>
"""


def make_handler(store: Store) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # quiet
            return

        def _send(self, code: int, body: bytes, kind: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path in ("/", "/index.html"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif self.path == "/api/packet":
                body = {"date": store.packet["date"], "cards": store.packet["cards"], "ratings": store.ratings}
                self._send(200, json.dumps(body).encode("utf-8"), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/rate":
                self._send(404, b"not found", "text/plain")
                return
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                saved = store.update(str(data["id"]), dict(data.get("change") or {}))
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                self._send(400, str(exc).encode("utf-8"), "text/plain")
                return
            self._send(200, json.dumps(saved).encode("utf-8"), "application/json")

    return Handler


def serve(blind_dir: Path, port: int = 8765) -> ThreadingHTTPServer:
    store = Store(latest_packet(blind_dir))
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))  # localhost only


# ---------------------------------------------------------------- review import: taste (statistics as gates, item 7)
ARM_ORDER = ("animedex", "baseline_loop", "baseline_single")


def load_ratings(blind_dir: Path, date: str) -> dict[str, dict[str, Any]]:
    f = blind_dir / f"ratings_{date}.yaml"
    data = yaml.safe_load(f.read_text(encoding="utf-8")) if f.is_file() else None
    cards = data.get("cards") if isinstance(data, dict) else None
    return {str(k): dict(v) for k, v in (cards or {}).items() if isinstance(v, dict)}


def rating_picks(ratings: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    """Every pair of rated cards with different ratings is one pick: the higher rating wins (D-017)."""
    rated = sorted((cid, r["rating"]) for cid, r in ratings.items() if isinstance(r.get("rating"), int))
    return [(a, b) if ra > rb else (b, a) for (a, ra), (b, rb) in combinations(rated, 2) if ra != rb]


def panel_picks(panel_dir: Path, card_ids: set[str]) -> tuple[list[tuple[str, str]], int, int]:
    """(picks, files read, picks skipped) from `eval/panel/*.json`; a pick naming a card outside the packet, or
    a card against itself, is skipped."""
    picks: list[tuple[str, str]] = []
    files = skipped = 0
    for f in sorted(panel_dir.glob("*.json")) if panel_dir.is_dir() else []:
        files += 1
        data = json.loads(f.read_text(encoding="utf-8"))
        for p in (data.get("picks") if isinstance(data, dict) else None) or []:
            w, lo = (str(p.get("winner")), str(p.get("loser"))) if isinstance(p, dict) else ("", "")
            if w in card_ids and lo in card_ids and w != lo:
                picks.append((w, lo))
            else:
                skipped += 1
    return picks, files, skipped


def judge_fitness(card: dict[str, Any]) -> list[float]:
    """The heavy pipeline's own ordering of a packet card, from its stored record (without Kingsley's rating):
    gates passed, evidenced taste criteria, lower max structural overlap."""
    return [1.0 if card.get("status") != "rejected" else 0.0,
            float(len((card.get("taste") or {}).get("criteria_met") or [])), 0.0,
            -float((card.get("gates") or {}).get("structural_jaccard_max") or 0.0)]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def judge_scores(key: dict[str, dict[str, Any]], ideas: dict[str, dict[str, Any]]) -> dict[str, float]:
    """Per packet card with an idea record (baseline 2 has none): its rank by judge fitness; equal fitness,
    equal score (ties are skipped when agreement is measured)."""
    fit = {cid: tuple(judge_fitness(ideas[k["source"]])) for cid, k in key.items() if k.get("source") in ideas}
    order = {f: float(i) for i, f in enumerate(sorted(set(fit.values())))}
    return {cid: order[f] for cid, f in sorted(fit.items())}


def compared_pairs(reference: dict[str, float], other: dict[str, float]) -> int:
    common = sorted(set(reference) & set(other))
    return sum(1 for a, b in combinations(common, 2) if reference[a] != reference[b] and other[a] != other[b])


@dataclass
class TasteResult:
    date: str
    cards: int
    rated: int
    complete: bool
    picks: dict[str, int] = field(default_factory=dict)
    card_strength: dict[str, float] = field(default_factory=dict)
    arm_strength: dict[str, float] = field(default_factory=dict)
    arm_record: dict[str, list[int]] = field(default_factory=dict)   # arm -> [wins, losses] against other arms
    judge_agreement: float | None = None
    judge_pairs: int = 0
    provenance: list[dict[str, Any]] = field(default_factory=list)   # A6: greenlit cards, after the review only
    report: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.date, "cards": self.cards, "rated": self.rated, "complete": self.complete,
                "picks": self.picks, "card_strength": self.card_strength, "arm_strength": self.arm_strength,
                "arm_record": self.arm_record, "judge_agreement": self.judge_agreement,
                "judge_pairs": self.judge_pairs, "provenance": self.provenance}


def taste_summary(paths: Paths, date: str | None = None) -> TasteResult:
    """The review import: picks -> Bradley-Terry strengths per card and per arm -> the judge's agreement."""
    blind = paths.root / "eval" / "blind"
    canonical = paths.root / "data" / "canonical"   # the heavy path's packet cards (the blind review predates the notes)
    packet_file = blind / f"packet_{date}.json" if date else latest_packet(blind)
    if not packet_file.is_file():
        raise FileNotFoundError(f"no blind packet {packet_file.name}")
    packet = json.loads(packet_file.read_text(encoding="utf-8"))
    date = str(packet["date"])
    ids = [c["id"] for c in packet["cards"]]
    ratings = {cid: r for cid, r in load_ratings(blind, date).items() if cid in ids}
    rated = sum(1 for cid in ids if isinstance((ratings.get(cid) or {}).get("rating"), int))
    res = TasteResult(date=date, cards=len(ids), rated=rated, complete=rated == len(ids) and bool(ids))
    own = rating_picks(ratings)
    panel, files, skipped = panel_picks(paths.root / "eval" / "panel", set(ids))
    res.picks = {"kingsley": len(own), "panel": len(panel), "panel_files": files, "skipped": skipped}
    if res.complete:
        key_file = paths.root / "data" / "blind" / f"key_{date}.json"
        key = json.loads(key_file.read_text(encoding="utf-8")) if key_file.is_file() else {}
        picks = own + panel
        res.card_strength = {str(k): v for k, v in stats.bradley_terry(picks).items()}
        arm_picks = [(key[w]["arm"], key[lo]["arm"]) for w, lo in picks
                     if w in key and lo in key and key[w]["arm"] != key[lo]["arm"]]
        res.arm_strength = {str(k): v for k, v in stats.bradley_terry(arm_picks).items()}
        res.arm_record = {arm: [sum(1 for w, _ in arm_picks if w == arm), sum(1 for _, lo in arm_picks if lo == arm)]
                          for arm in ARM_ORDER if any(arm in p for p in arm_picks)}
        ideas = {i["idea_id"]: i for i in _read_jsonl(canonical / "ideas.jsonl")}
        ideas.update({i["idea_id"]: i for i in _read_jsonl(paths.root / "data" / "blind" / "baseline_loop" / "ideas.jsonl")})
        judge = judge_scores(key, ideas)
        res.judge_agreement = stats.ranking_agreement(res.card_strength, judge)
        res.judge_pairs = compared_pairs(res.card_strength, judge)
        transfers = {t["transfer_id"]: t for t in _read_jsonl(canonical / "transfers.jsonl")}
        res.provenance = winners_provenance(key, ratings, ideas, transfers)
        text = _taste_md(res, key, ratings, judge, res.provenance)
    else:
        text = _taste_md(res, {}, {}, {})
    out = paths.reports / "taste.md"
    atomic_write_text(out, text)
    atomic_write_text(paths.build / "stats" / "taste.json",
                      json.dumps(res.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    res.report = str(out.relative_to(paths.root))
    return res


REACH_MIN_WORDS = 3   # a pattern reached a card's text when they share this many content words (A6)
_STOP = frozenset("that this with from into their them they have when what which while where because every "
                  "each only more than then over under about after before".split())


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in _STOP}


def card_text(idea: dict[str, Any]) -> str:
    e = idea.get("engine") or {}
    return " ".join([str(idea.get("logline") or ""), str(idea.get("premise") or ""), *(str(v) for v in e.values())])


def winners_provenance(key: dict[str, dict[str, Any]], ratings: dict[str, dict[str, Any]],
                       ideas: dict[str, dict[str, Any]], transfers: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Controls A6: for each greenlit card, its arm, the patterns it drew on with their source titles and
    principles, and whether any of them reached the card's text (REACH_MIN_WORDS shared content words)."""
    out = []
    for cid in sorted(c for c, r in ratings.items() if r.get("greenlight") is True):
        k = key.get(cid) or {}
        idea = ideas.get(str(k.get("source"))) or {}
        text = _content_words(card_text(idea))
        used = []
        for tid in idea.get("atoms_used") or []:
            t = transfers.get(tid) or {}
            shared = len(text & _content_words(str(t.get("pattern") or "")))
            used.append({"transfer_id": tid, "title_id": str(t.get("source_atom_id") or tid).split(".")[0],
                         "principle": t.get("principle"), "reached": shared >= REACH_MIN_WORDS})
        out.append({"card": cid, "arm": k.get("arm", "?"), "operator": (idea.get("transformation") or {}).get("operator"),
                    "patterns": used, "index_material": any(u["reached"] for u in used)})
    return out


def _provenance_md(rows: list[dict[str, Any]]) -> list[str]:
    lines = ["## Provenance of winners (greenlit cards)", ""]
    if not rows:
        return [*lines, "No card was greenlit.", ""]
    lines += ["| Card | Arm | Operator | Patterns drawn on (source title; in the text?) | Principles |", "|---|---|---|---|---|"]
    for r in rows:
        pats = "; ".join(f"{u['transfer_id']} ({u['title_id']}; {'yes' if u['reached'] else 'no'})"
                         for u in r["patterns"]) or "none"
        principles = "; ".join(str(u["principle"]) for u in r["patterns"] if u.get("principle")) or "none"
        lines.append(f"| {r['card']} | {r['arm']} | {r['operator'] or 'n/a'} | {pats} | {principles} |")
    none = [r["card"] for r in rows if not r["index_material"]]
    lines += ["", f"{len(none)} of {len(rows)} greenlit card(s) used no index material in their text "
              f"({', '.join(none) or 'none'}): the baseline cards, plus any ANIMEDEX card whose patterns share fewer "
              f"than {REACH_MIN_WORDS} content words with its logline, premise and engine.", ""]
    return lines


def _taste_md(res: TasteResult, key: dict[str, dict[str, Any]], ratings: dict[str, dict[str, Any]],
              judge: dict[str, float], provenance: list[dict[str, Any]] | None = None) -> str:
    p = res.picks
    lines = ["# Taste: Bradley-Terry strengths from pairwise picks", "",
             f"Packet {res.date}: {res.cards} cards, {res.rated} rated. Picks: {p['kingsley']} from Kingsley's ratings "
             f"(a higher rating wins; equal ratings are skipped), {p['panel']} from {p['panel_files']} panel file(s), "
             f"{p['skipped']} skipped (a card outside the packet, or a card against itself).", ""]
    if not res.complete:
        return "\n".join([*lines, f"{res.cards - res.rated} card(s) still unrated. The arms stay hidden until every "
                           "card is rated; run `make review-report` again then.", ""]) + "\n"
    lines += ["Strengths are Bradley-Terry (MM, 0.5 pseudo-picks against an average opponent, D-017), normalized to a "
              "geometric mean of 1: a card twice as strong as another is picked two times in three.", "",
              "## Arms", "", "| Arm | Strength | Wins | Losses |", "|---|---|---|---|"]
    for arm in sorted(res.arm_strength, key=lambda a: (-res.arm_strength[a], a)):
        w, lo = res.arm_record.get(arm, [0, 0])
        lines.append(f"| {arm} | {res.arm_strength[arm]:.3f} | {w} | {lo} |")
    lines += ["", "Only picks between cards of different arms count here.", "",
              "## Cards, strongest first", "", "| Card | Arm | Strength | Rating | Judge rank |", "|---|---|---|---|---|"]
    for cid in sorted(res.card_strength, key=lambda c: (-res.card_strength[c], c)):
        rank = "n/a" if cid not in judge else f"{judge[cid]:.0f}"
        lines.append(f"| {cid} | {(key.get(cid) or {}).get('arm', '?')} | {res.card_strength[cid]:.3f} | "
                     f"{(ratings.get(cid) or {}).get('rating')} | {rank} |")
    agree = "n/a" if res.judge_agreement is None else f"{res.judge_agreement:.2f}"
    lines += ["", "## The judge against this ranking", "",
              f"Agreement: {agree} over {res.judge_pairs} card pair(s): the share of pairs the judge's own ordering "
              "puts the same way as the strengths (ties in either are skipped). The judge's ordering is each card's "
              "fitness without the human rating (gates passed, taste criteria kept, lower structural overlap), from "
              "the idea records; baseline 2 cards have none. Judge rank: higher is better.", ""]
    lines += _provenance_md(provenance or [])
    return "\n".join(lines) + "\n"
