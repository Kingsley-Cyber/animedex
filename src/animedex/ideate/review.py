"""Blind review page (owner ruling 2026-09-27): a small local page, localhost only.

`animedex review` serves the latest packet on http://127.0.0.1:<port>. One card at a time,
logline + premise only (no source, no arm). Keyboard-driven:
  1-5 rating   y / n greenlight   t then 1-5 toggle T1-T5   right or j next, left or k back
Every change is saved at once to eval/blind/ratings_<date>.yaml. The server binds 127.0.0.1 only
and loads nothing from the internet.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import yaml

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
