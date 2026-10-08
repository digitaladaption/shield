import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shield.engine.analysis import Engine
from shield.engine.match import load_match

MATCH = os.path.join(os.path.dirname(__file__), "..", "data", "match_7")


def test_vision_explains_the_best_interception():
    st = Engine(load_match(MATCH)).snapshot()
    stop = max((r for r in st.threat_prevented if r["player"] == "H06" and r["type"] == "interception"),
               key=lambda r: r["danger_stopped"])
    ps = st.by_id[stop["pass_id"]]
    # the passer's view at the moment he chose: the lane he picked was not open
    v = st.see(ps["t_start"], ps["player"])
    assert v["view"] == "carrier"
    chosen = next(l for l in v["lanes"] if l["to"] == ps["receiver"])
    assert chosen["state"] in ("blocked", "contested")
    # the Shield's view just before: he is closing that lane
    d = st.see(ps["t_start"], "H06")
    assert d["view"] == "defender"
    assert any(c["to"] == ps["receiver"] for c in d["closing"])
    assert d["read"].startswith("Dario Okonkwo-Hale")


def test_vision_roles_are_consistent():
    st = Engine(load_match(MATCH)).snapshot()
    v = st.see(600.0, "H10")
    assert v["view"] in ("carrier", "defender", "attacker")
    assert "read" in v and v["read"]
