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
