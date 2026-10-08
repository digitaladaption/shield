"""
Precompute everything the web demo needs into web/data/bundle.json.

  python -m shield.engine.build_bundle --match data/match_7 --control data/match_7_control

Stories are generated through the agent workflow. With no model configured
they come from the local narrator (English only) and the bundle says so.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shield.agents.pipeline import MODES, NarrateRequest, build_workflow  # noqa: E402
from shield.engine.analysis import Engine  # noqa: E402
from shield.engine.match import load_match  # noqa: E402

DRILLS = {
    "Shield": [
        {"name": "Shadow the line", "how": "In a 4v4, one player may only move along the line between the ball and their own goal. Count passes they cut out."},
        {"name": "Scan and step", "how": "Coach points before each pass. Player must look over the shoulder, then step into the lane as the pass is played."},
        {"name": "Win and release", "how": "After every ball you win, your next action must come within 2 seconds. Reward forward passes."},
    ],
    "Metronome": [
        {"name": "Two-touch rondo", "how": "5v2 rondo, two touches max. Count consecutive completed passes."},
        {"name": "Switch on call", "how": "On the coach's whistle the ball must cross to the far side within three passes."},
    ],
    "Creator": [
        {"name": "Line-breaking pass", "how": "Three lines of cones. A pass only counts if it goes through a line into a teammate's feet."},
        {"name": "Third-man run", "how": "A gives to B, B sets to A, A plays C who has run beyond. Repeat both sides."},
    ],
    "Finisher": [
        {"name": "One-touch finish", "how": "Service from both wings, finish first time. Track shots on target, not goals."},
        {"name": "Find the pocket", "how": "Receive between two defenders on the edge of the box, turn and shoot inside 3 seconds."},
    ],
    "Engine": [
        {"name": "Box-to-box relay", "how": "Sprint to the far box, play a one-two, recover to your own box. 6 reps."},
    ],
    "Presser": [
        {"name": "Trigger press", "how": "Press only when the receiver's first touch goes backwards. Hold position otherwise."},
    ],
    "Wall": [
        {"name": "Block and clear", "how": "2v2 in the box. Defender must get a body part on every shot. Count blocks."},
    ],
    "Carrier": [
        {"name": "Drive the gate", "how": "Dribble through a 2 m gate under pressure, then release. Count clean gates."},
    ],
    "AllRounder": [
        {"name": "Position rotation", "how": "Play a different position every 10 minutes of a small-sided game and notice which felt natural."},
    ],
}


def compact_frames(data, step: int = 1) -> dict:
    ids = [p["id"] for p in data.meta["players"]]
    rows = []
    for i, fr in enumerate(data.frames):
        if i % step:
            continue
        row = [fr.t, round(fr.ball[0], 1), round(fr.ball[1], 1)]
        for pid in ids:
            x, y = fr.players.get(pid, (0.0, 0.0))
            row += [round(x, 1), round(y, 1)]
        rows.append(row)
    return {"ids": ids, "rows": rows, "layout": "t, ball_x, ball_y, then x,y per id"}


async def stories_for(match_path: str, st, data, players: list[str]) -> dict:
    wf, backend = build_workflow(match_path, use_mcp_tool=False)
    roster = [p["name"] for p in data.meta["players"]]
    out = {"backend": backend, "items": {}}
    langs = ["en", "es", "de", "fr"]          # template languages; a model adds free prose and more languages
    jobs = []
    for mode in ("analyst", "casual"):
        for lang in langs:
            jobs.append((mode, lang, None))
    for pid in players:
        for mode in ("player", "kid"):
            for lang in langs:
                jobs.append((mode, lang, pid))
    for mode, lang, pid in jobs:
        packet = st.fact_packet(player_focus=pid)
        req = NarrateRequest(packet=packet, mode=mode, language=lang, player_focus=pid, roster=roster)
        story = (await wf.run(req)).get_outputs()[-1]
        key = f"{mode}|{lang}|{pid or ''}"
        out["items"][key] = story.to_dict()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="data/match_7")
    ap.add_argument("--control", default=None)
    ap.add_argument("--out", default="web/data/bundle.json")
    ap.add_argument("--story-players", default="H06,H03,H04,H07,H10,A07")
    args = ap.parse_args()

    data = load_match(args.match)
    st = Engine(data).snapshot()
    bundle = st.to_bundle()
    bundle["events"] = st.events
    bundle["frames"] = compact_frames(data)
    bundle["drills"] = DRILLS
    bundle["archetypes"] = {k: {"label": v["label"], "blurb": v["blurb"], "metrics": v["metrics"]}
                            for k, v in st.ARCHETYPES.items()}
    if args.control:
        cd = load_match(args.control, with_frames=False)
        cs = Engine(cd).snapshot()
        bundle["control"] = {"teams": cs.team_stats, "score": cs.score,
                             "note": "Same seed, Shield plant switched off. A true counterfactual at match level."}
    from shield.agents.coach import build_coach_workflow, make_plan
    cwf, _ = build_coach_workflow()
    bundle["plans"] = {}
    for pid in st.fingerprints:
        bundle["plans"][pid] = asyncio.run(make_plan(bundle["playbooks"][pid], "u11", "you", workflow=cwf)).to_dict()
    players = [p for p in args.story_players.split(",") if p in st.fingerprints]
    bundle["stories"] = asyncio.run(stories_for(args.match, st, data, players))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(bundle, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {args.out} ({os.path.getsize(args.out)/1e6:.1f} MB), stories via {bundle['stories']['backend']}")


if __name__ == "__main__":
    main()
