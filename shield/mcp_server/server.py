"""
Shield stats engine as an MCP server.

The agents never touch raw events or compute numbers themselves. They call
these tools, get facts with evidence IDs, and phrase from them. That is the
whole explainability story: the model can only say what the engine can prove.

Run:  python -m shield.mcp_server.server --match data/match_7          (stdio)
      python -m shield.mcp_server.server --match data/match_7 --http   (streamable HTTP on :8000)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shield.engine.analysis import Engine, MatchState  # noqa: E402
from shield.engine.match import load_match  # noqa: E402

MATCH_PATH = os.environ.get("SHIELD_MATCH", "data/match_7")
_engine: Engine | None = None
_cache: dict[float | None, MatchState] = {}

mcp = FastMCP("shield-stats-engine",
              instructions="Deterministic football match intelligence. Every tool returns facts with "
                           "event-ID evidence. Use get_fact_packet first, then drill down.")


def engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = Engine(load_match(MATCH_PATH))
    return _engine


def state(clock: float | None = None) -> MatchState:
    key = None if clock is None else round(clock, 1)
    if key not in _cache:
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = engine().snapshot(clock)
    return _cache[key]


@mcp.tool()
def get_match_state(clock_seconds: float | None = None) -> dict:
    """Score, team stats and clock at a point in the match (default: full time).
    Pass clock_seconds for a live view, e.g. 1500 for 25:00."""
    st = state(clock_seconds)
    return {"clock": st.t_end, "score": st.score, "teams": st.team_stats,
            "clubs": st.data.clubs}


@mcp.tool()
def get_fact_packet(clock_seconds: float | None = None, player_focus: str | None = None,
                    window_start: float | None = None, window_end: float | None = None,
                    max_facts: int = 40) -> dict:
    """The verified fact packet to narrate from. Every fact has an id (f1, f2...) and
    evidence event ids. player_focus (e.g. 'H06') puts that player's facts first.
    window_start/window_end (seconds) restrict timed facts to a period."""
    st = state(clock_seconds)
    window = (window_start, window_end) if window_start is not None and window_end is not None else None
    return st.fact_packet(player_focus=player_focus, window=window, max_facts=max_facts)


@mcp.tool()
def get_key_moments(clock_seconds: float | None = None, limit: int = 10, kind: str | None = None) -> list[dict]:
    """Ranked key moments (goal, chance, stop, momentum_shift, chaos) with evidence ids."""
    st = state(clock_seconds)
    ms = [m for m in st.moments if kind is None or m["kind"] == kind]
    for m in ms:
        m = dict(m)
    return [dict(m, player_name=st.data.name_of(m["player"]) if m["player"] else None) for m in ms[:limit]]


@mcp.tool()
def get_player_fingerprint(player_id: str, clock_seconds: float | None = None) -> dict:
    """Per-90 metrics, z-scores vs the other outfield players, archetype scores,
    strengths, weaknesses and 'how he thinks' decision patterns for one player."""
    st = state(clock_seconds)
    fp = st.fingerprints.get(player_id)
    if not fp:
        return {"error": f"unknown or goalkeeper player {player_id}", "players": list(st.fingerprints)}
    return fp


@mcp.tool()
def list_players() -> list[dict]:
    """All players with id, name, team, role, number and archetype."""
    st = state(None)
    return [{"id": pid, "name": p["name"], "team": p["team"], "role": p["role"], "number": p["number"],
             "archetype": st.fingerprints.get(pid, {}).get("archetype_label", "Goalkeeper")}
            for pid, p in st.data.players.items()]


@mcp.tool()
def get_threat_prevented(player_id: str | None = None, clock_seconds: float | None = None, limit: int = 20) -> dict:
    """Threat prevented: every defensive action credited with the danger the attack
    was heading towards. Explains the invisible work."""
    st = state(clock_seconds)
    rows = [r for r in st.threat_prevented if player_id is None or r["player"] == player_id]
    rows.sort(key=lambda r: -r["danger_stopped"])
    total = round(sum(r["danger_stopped"] for r in rows), 3)
    xg = round(sum(r["xg_prevented"] for r in rows), 3)
    return {"player": player_id, "total_danger_stopped": total, "total_xg_prevented": xg,
            "attacks_ended": sum(1 for p in st.possessions if player_id and p.ended_by == player_id),
            "actions": rows[:limit],
            "method": "danger = closeness to goal, boosted by attackers ahead of the ball, reduced by defenders goal-side. "
                      "xG prevented = what possessions reaching that danger produced in this match (empirical, blended with a prior)."}


@mcp.tool()
def get_counterfactual(event_id: str) -> dict:
    """What would likely have happened without this stop, from this match's own
    possessions: shot rate and goal rate of attacks that reached the same danger."""
    return state(None).counterfactual(event_id)


@mcp.tool()
def get_momentum(clock_seconds: float | None = None) -> list[dict]:
    """5-minute windows: danger by team, possession changes, chaos/control regime."""
    return state(clock_seconds).momentum


@mcp.tool()
def compare_players(player_a: str, player_b: str, metrics: list[str] | None = None) -> dict:
    """Side-by-side per-90 metrics and z-scores for two players."""
    st = state(None)
    a, b = st.fingerprints.get(player_a), st.fingerprints.get(player_b)
    if not a or not b:
        return {"error": "unknown player"}
    keys = metrics or ["passes_p90", "pass_accuracy", "progressive_passes_p90", "danger_created_p90",
                       "interceptions_p90", "tackles_won_p90", "threat_prevented_p90", "screening",
                       "pressures_p90", "shots_p90", "xg_p90", "distance_km", "sprints"]
    return {"a": {"id": player_a, "name": a["name"], "archetype": a["archetype_label"]},
            "b": {"id": player_b, "name": b["name"], "archetype": b["archetype_label"]},
            "rows": [{"metric": k, "a": a["metrics"].get(k), "b": b["metrics"].get(k),
                      "a_z": a["z"].get(k), "b_z": b["z"].get(k)} for k in keys]}


@mcp.tool()
def match_style(stats: dict) -> dict:
    """Play-like-your-idol: give a young player's simple per-match stats
    (passes, passes_complete, shots, goals, tackles_won, interceptions, minutes)
    and get the archetype they most resemble, with the closest players in this match.
    Comparison is on STYLE (shape of the profile), not level."""
    st = state(None)
    minutes = float(stats.get("minutes", 60)) or 60.0
    scale = 90.0 / minutes
    kid = {
        "passes_p90": stats.get("passes", 0) * scale,
        "pass_accuracy": (stats.get("passes_complete", 0) / stats["passes"]) if stats.get("passes") else 0.0,
        "shots_p90": stats.get("shots", 0) * scale,
        "goals_p90": stats.get("goals", 0) * scale,
        "tackles_won_p90": stats.get("tackles_won", 0) * scale,
        "interceptions_p90": stats.get("interceptions", 0) * scale,
    }
    keys = list(kid)

    def shape(v: dict) -> list[float]:
        vals = [float(v.get(k, 0.0)) for k in keys]
        mx = max(vals) or 1.0
        return [x / mx for x in vals]

    ks = shape(kid)
    rows = []
    for pid, fp in st.fingerprints.items():
        ps = shape(fp["metrics"])
        dist = sum((x - y) ** 2 for x, y in zip(ks, ps)) ** 0.5
        rows.append((dist, pid, fp))
    rows.sort(key=lambda r: r[0])
    best = rows[0][2]
    return {"closest_archetype": best["archetype_label"],
            "closest_players": [{"id": pid, "name": fp["name"], "archetype": fp["archetype_label"],
                                 "style_distance": round(d, 3)} for d, pid, fp in rows[:3]],
            "your_shape": dict(zip(keys, [round(x, 2) for x in ks])),
            "note": "Style match compares the shape of your numbers, not their size."}


@mcp.tool()
def get_overlay_items(clock_seconds: float | None = None) -> list[dict]:
    """Timed, machine-readable overlay items (t_start, t_end, kind, text, evidence)
    for rendering on a live feed."""
    return state(clock_seconds).overlay_items()


def main():
    global MATCH_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default=MATCH_PATH)
    ap.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    MATCH_PATH = args.match
    if args.http:
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
