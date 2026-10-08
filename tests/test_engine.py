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


def test_playbook_is_clickable_and_in_plain_words():
    st = Engine(load_match(MATCH)).snapshot()
    pb = st.playbook("H06")
    assert pb["archetype"] == "Shield"
    assert 3 <= len(pb["looks_like"]) <= 6
    assert pb["main_points"], "the idol must have main points from the match"
    for p in pb["main_points"]:
        assert p["evidence"] and p["evidence"][0] in st.by_id   # every point jumps to a real event
        assert p["why"]
    assert all("_p90" not in w["friendly"] for w in pb["work_on"])
    assert all(w["drill"] for w in pb["work_on"])


def test_fact_packet_keeps_score_and_goal_under_truncation():
    st = Engine(load_match(MATCH)).snapshot()
    pk = st.fact_packet(max_facts=8)
    tags = [t for f in pk["facts"] for t in f["tags"]]
    assert "score" in tags and "goal" in tags


def test_ui_dictionary_is_complete():
    from shield.engine.i18n import LANGS
    from shield.engine.i18n_ui import ARCH, DRILLS, LOOKS, UI
    for k, v in UI.items():
        for lang in LANGS:
            assert v.get(lang), (k, lang)
    for k, v in LOOKS.items():
        for lang in LANGS:
            assert v.get(lang), (k, lang)
    for a, v in ARCH.items():
        for part in ("label", "blurb", "intro"):
            for lang in LANGS:
                assert v[part].get(lang), (a, part, lang)
    from shield.engine.playbook import METRIC_DRILLS
    for name, _ in METRIC_DRILLS.values():
        assert name in DRILLS, name
        for lang in ("es", "de", "fr"):
            assert len(DRILLS[name][lang]) == 2


def test_playbook_is_localised():
    st = Engine(load_match(MATCH)).snapshot()
    pb = st.playbook("H06")
    for l in pb["looks_like"]:
        assert set(l["i18n"]) >= {"en", "es", "de", "fr"} and l["i18n"]["es"] != l["i18n"]["en"]
    for p in pb["main_points"]:
        assert p["why_i18n"]["de"] != p["why_i18n"]["en"]
    assert pb["archetype_label_i18n"]["fr"] == "Le Bouclier"
