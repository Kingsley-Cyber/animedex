"""Blind review page: localhost only, blind cards, keyboard page, ratings saved to eval/blind/."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest
import yaml

from animedex.ideate.review import serve

pytestmark = pytest.mark.unit


@pytest.fixture
def server(tmp_path):
    blind = tmp_path / "eval" / "blind"
    blind.mkdir(parents=True)
    cards = [{"id": f"C{i:02d}", "logline": f"Logline {i}", "premise": f"Premise {i}"} for i in (1, 2, 3)]
    (blind / "packet_2026-09-27.json").write_text(json.dumps({"date": "2026-09-27", "cards": cards}))
    srv = serve(blind, port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, blind
    srv.shutdown()
    srv.server_close()


def _url(srv, path):
    return f"http://127.0.0.1:{srv.server_address[1]}{path}"


def test_binds_localhost_and_serves_blind_cards(server):
    srv, _ = server
    assert srv.server_address[0] == "127.0.0.1"
    page = urllib.request.urlopen(_url(srv, "/")).read().decode()
    assert "Blind review" in page and "http" not in page.replace("http-equiv", "")  # nothing loads from the web
    data = json.loads(urllib.request.urlopen(_url(srv, "/api/packet")).read())
    assert [c["id"] for c in data["cards"]] == ["C01", "C02", "C03"]
    assert set(data["cards"][0]) == {"id", "logline", "premise"}  # no arm, no source


def test_ratings_save_to_eval_blind(server):
    srv, blind = server

    def post(change, cid="C02"):
        req = urllib.request.Request(_url(srv, "/api/rate"), data=json.dumps({"id": cid, "change": change}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        return json.loads(urllib.request.urlopen(req).read())

    post({"rating": 4})
    post({"greenlight": True})
    saved = post({"criteria": ["T3", "T1"]})
    assert saved == {"rating": 4, "greenlight": True, "criteria": ["T1", "T3"]}
    data = yaml.safe_load((blind / "ratings_2026-09-27.yaml").read_text())
    assert data["cards"]["C02"] == saved and data["cards"]["C01"]["rating"] is None
    with pytest.raises(urllib.error.HTTPError):
        post({"rating": 9})


# ---------------------------------------------------------------- review import: taste (statistics as gates, item 7)
def test_ratings_become_picks_higher_wins_ties_and_unrated_skipped():
    from animedex.ideate.review import rating_picks

    ratings = {"C01": {"rating": 5}, "C02": {"rating": 3}, "C03": {"rating": 3}, "C04": {"rating": None}}
    assert rating_picks(ratings) == [("C01", "C02"), ("C01", "C03")]  # C02 = C03 is a tie; C04 is unrated


DATE = "2026-09-27"


def idea(n: int, criteria: list[str], atoms: list[str]) -> dict:
    """A stored packet card of the heavy path, with just the fields the review report reads."""
    return {"idea_id": f"idea.run_test_001.{n:03d}", "status": "candidate",
            "logline": "A lighthouse keeper can see the debts every sailor owes the sea, and must choose who pays.",
            "premise": "The lead reads the measure of their own power, a secret the audience shares.",
            "engine": {"goal": "keep the harbor alive", "cost": "someone else drowns"},
            "transformation": {"operator": "transfer_cost"}, "atoms_used": atoms,
            "taste": {"criteria_met": criteria}, "gates": {"structural_jaccard_max": 0.3}}


def _review(repo, ratings):
    """A 4-card packet: two ANIMEDEX cards, one baseline-1 card, one baseline-2 card, and a panel file."""
    canonical = repo.root / "data" / "canonical"
    canonical.mkdir(parents=True, exist_ok=True)
    ideas = [idea(1, ["T2"], ["ironvale_circuit_2021.t.001"]), idea(2, ["T2", "T3"], ["ironvale_circuit_2021.t.001"])]
    (canonical / "ideas.jsonl").write_text("".join(json.dumps(i) + "\n" for i in ideas))
    transfer = {"transfer_id": "ironvale_circuit_2021.t.001", "source_atom_id": "ironvale_circuit_2021.m.001",
                "pattern": "Only the lead can read the measure of their own power, so the audience shares a secret."}
    (canonical / "transfers.jsonl").write_text(json.dumps(transfer) + "\n")
    loop = {**idea(1, [], []), "idea_id": "idea.run_test_001_bl.001", "arm": "baseline_loop"}
    f = repo.root / "data" / "blind" / "baseline_loop" / "ideas.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text(json.dumps(loop) + "\n")
    blind = repo.root / "eval" / "blind"
    blind.mkdir(parents=True)
    cards = [{"id": f"C0{i}", "logline": f"Logline {i}", "premise": f"Premise {i}"} for i in (1, 2, 3, 4)]
    (blind / f"packet_{DATE}.json").write_text(json.dumps({"date": DATE, "cards": cards}))
    lines = ["cards:"] + [f"  {cid}: {json.dumps({'rating': r, 'greenlight': None, 'criteria': []})}"
                          for cid, r in ratings.items()]
    (blind / f"ratings_{DATE}.yaml").write_text("\n".join(lines) + "\n")
    key = {"C01": {"arm": "animedex", "source": "idea.run_test_001.001"},
           "C02": {"arm": "baseline_loop", "source": "idea.run_test_001_bl.001"},
           "C03": {"arm": "baseline_single", "source": f"baseline_single.{DATE}.01"},
           "C04": {"arm": "animedex", "source": "idea.run_test_001.002"}}
    (repo.root / "data" / "blind" / f"key_{DATE}.json").write_text(json.dumps(key))  # beside baseline 1's store
    panel = repo.root / "eval" / "panel"
    panel.mkdir(parents=True)
    (panel / "panelist_1.json").write_text(json.dumps({"picks": [{"winner": "C02", "loser": "C03"},
                                                                 {"winner": "C09", "loser": "C01"}]}))


def test_review_report_ranks_cards_and_arms_and_scores_the_judge(repo):
    from typer.testing import CliRunner

    from animedex.cli import app

    _review(repo, {"C01": 5, "C02": 2, "C03": 3, "C04": 4})
    result = CliRunner().invoke(app, ["review", "--summary"])
    assert result.exit_code == 0, result.output
    stored = json.loads((repo.build / "stats" / "taste.json").read_text())
    assert stored["picks"] == {"kingsley": 6, "panel": 1, "panel_files": 1, "skipped": 1}  # C09 is not in the packet
    s = stored["card_strength"]
    assert s["C01"] > s["C04"] > max(s["C02"], s["C03"])
    arms = stored["arm_strength"]
    assert max(arms, key=arms.get) == "animedex" and stored["arm_record"]["animedex"] == [4, 0]  # C01 v C04 skipped
    # the judge orders C04 (2 taste criteria) > C01 (1) > C02 (0); the picks say C01 > C04 > C02: 2 of 3 pairs agree
    assert stored["judge_agreement"] == round(2 / 3, 4) and stored["judge_pairs"] == 3
    report = (repo.reports / "taste.md").read_text()
    assert "| animedex |" in report and "Agreement: 0.67 over 3 card pair(s)" in report
    assert "judge agreement 0.67" in result.output


def test_review_report_hides_the_arms_until_every_card_is_rated(repo):
    _review(repo, {"C01": 5, "C02": 2, "C03": 3, "C04": None})
    from animedex.ideate.review import taste_summary

    res = taste_summary(repo)
    report = (repo.reports / "taste.md").read_text()
    assert not res.complete and res.rated == 3 and res.card_strength == {} and res.arm_strength == {}
    assert "1 card(s) still unrated" in report and "animedex" not in report and "baseline" not in report


def test_provenance_of_winners_lists_greenlit_cards_after_the_review_only(repo):
    """Controls A6: arm, patterns and source titles, principles, and greenlit cards with no index material."""
    import yaml as _yaml

    from animedex.ideate.review import taste_summary

    _review(repo, {"C01": 5, "C02": 2, "C03": 3, "C04": 4})
    f = repo.root / "eval" / "blind" / f"ratings_{DATE}.yaml"
    data = _yaml.safe_load(f.read_text())
    data["cards"]["C01"]["greenlight"] = True   # ANIMEDEX
    data["cards"]["C03"]["greenlight"] = True   # baseline 2: no idea record, no patterns
    f.write_text(_yaml.safe_dump(data))
    res = taste_summary(repo)
    rows = {r["card"]: r for r in res.provenance}
    assert set(rows) == {"C01", "C03"}
    assert rows["C01"]["arm"] == "animedex" and rows["C01"]["patterns"]
    assert all(u["title_id"] == "ironvale_circuit_2021" for u in rows["C01"]["patterns"])
    assert rows["C03"] == {"card": "C03", "arm": "baseline_single", "operator": None, "patterns": [],
                           "index_material": False}
    report = (repo.reports / "taste.md").read_text()
    assert "## Provenance of winners (greenlit cards)" in report and "| C01 | animedex |" in report
    assert "used no index material in their text" in report
