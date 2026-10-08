import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shield.engine.analysis import Engine
from shield.engine.live import LiveTracker
from shield.engine.match import load_match

MATCH = os.path.join(os.path.dirname(__file__), "..", "data", "match_7")


def test_live_tracker_agrees_with_batch_engine():
    data = load_match(MATCH, with_frames=False)
    st = Engine(data).snapshot()
    lt = LiveTracker(data.clubs, data.players, st.xg_curve_table)
    for e in data.events:
        lt.ingest(e)
    assert lt.score == st.score
    for pid, s in st.player_stats.items():
        assert lt.per_player[pid]["interceptions"] == s["interceptions"]
        assert abs(lt.per_player[pid]["danger_stopped"] - s["danger_stopped"]) < 1e-6
    goals_live = [m for m in lt.moments if m["kind"] == "goal"]
    goals_batch = [m for m in st.moments if m["kind"] == "goal"]
    assert len(goals_live) == len(goals_batch)
    assert all(m["engine_latency_ms"] < 5 for m in lt.moments)
