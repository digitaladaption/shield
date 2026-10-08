import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shield.engine.analysis import Engine  # noqa: E402
from shield.engine.match import load_match  # noqa: E402

MATCH = os.path.join(os.path.dirname(__file__), "..", "data", "match_7")


def test_engine_finds_the_shield_without_reading_ground_truth():
    data = load_match(MATCH)
    st = Engine(data).snapshot()
    # ground_truth.json is never opened by the engine; we only use it here to grade.
    import json
    gt = json.load(open(os.path.join(MATCH, "ground_truth.json")))
    top = max(st.fingerprints.values(), key=lambda f: f["metrics"]["threat_prevented_p90"])
    assert top["player"] == gt["shield_player"]
    assert st.fingerprints[gt["shield_player"]]["archetype"] == "Shield"


def test_every_fact_has_id_and_evidence_list():
    st = Engine(load_match(MATCH, with_frames=False)).snapshot()
    ids = [f.id for f in st.facts]
    assert len(ids) == len(set(ids))
    for f in st.facts:
        assert isinstance(f.evidence, list)
        for e in f.evidence:
            assert e in st.by_id


def test_live_snapshot_never_sees_the_future():
    st = Engine(load_match(MATCH, with_frames=False)).snapshot(1200)
    assert all(e["t"] <= 1200 for e in st.events)
    assert all(m["t"] <= 1200 for m in st.moments)
    assert st.score == {"home": 0, "away": 0}


def test_counterfactual_is_empirical():
    st = Engine(load_match(MATCH)).snapshot()
    stop = max((r for r in st.threat_prevented if r["type"] == "interception"), key=lambda r: r["danger_stopped"])
    cf = st.counterfactual(stop["event_id"])
    assert cf["sample_possessions"] > 0
    assert 0 <= cf["goal_rate_from_here"] <= cf["shot_rate_from_here"] <= 1
    assert "intended_pass" in cf
