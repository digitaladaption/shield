"""
Playbook: what playing like this player looks like, his main points from the
match, and what to work on. Written for a 9 to 14 year old and their coach.
Every line carries the evidence it came from. Deterministic, like the rest
of the engine.
"""
from __future__ import annotations

FRIENDLY = {
    "passes_p90": "passes made", "pass_accuracy": "passes that found a teammate", "pass_difficulty": "difficulty of passes attempted",
    "progressive_passes_p90": "passes that moved the team forward", "passes_into_danger_p90": "passes into dangerous areas",
    "danger_created_p90": "danger created by passing", "carries_p90": "runs with the ball", "progressive_carries_p90": "runs forward with the ball",
    "carry_m_p90": "metres carried", "shots_p90": "shots", "xg_p90": "quality of chances taken", "goals_p90": "goals",
    "interceptions_p90": "passes cut out", "tackles_won_p90": "tackles won", "tackle_success": "tackles that won the ball",
    "blocks_p90": "shots blocked", "pressures_p90": "times he closed down the ball carrier", "ball_recoveries_p90": "times he won the ball back",
    "threat_prevented_p90": "attacks stopped before they got dangerous", "xg_prevented_p90": "goals saved by stopping attacks",
    "screening": "time spent between the ball and his own goal", "distance_km": "distance covered", "sprints": "sprints",
    "top_speed_ms": "top speed", "time_to_release": "time on the ball before passing",
}

# a drill for each thing a player might need to work on
METRIC_DRILLS = {
    "passes_p90": ("Keep it moving", "5v2 rondo, two touches. Count how many passes in a row the group manages. Beat it next week."),
    "pass_accuracy": ("Find a shirt", "Pass against a wall or to a partner 50 times, inside of the foot, firm and along the floor. Count the ones that arrive clean."),
    "pass_difficulty": ("Brave passes", "In a small game, a pass that goes between two defenders scores a bonus point."),
    "progressive_passes_p90": ("Play forward first", "Receive, look forward before anything else. A sideways pass is allowed only if you looked forward first."),
    "passes_into_danger_p90": ("Into the box", "From the wing, play 20 passes into a teammate arriving in the box. Vary the weight."),
    "danger_created_p90": ("Line breakers", "Three lines of cones. A pass only counts if it goes through a line to a teammate's feet."),
    "carries_p90": ("Take it on", "After your first touch, take two more touches forward before passing. Then release."),
    "progressive_carries_p90": ("Drive the gate", "Dribble through a 2 m gate under pressure, then release. Count clean gates."),
    "shots_p90": ("Shoot on sight", "Inside the box, your first option is a shot. One touch to set, one to hit."),
    "xg_p90": ("Find the pocket", "Receive between two defenders on the edge of the box, turn and shoot inside 3 seconds."),
    "goals_p90": ("One-touch finish", "Service from both wings, finish first time. Track shots on target, not goals."),
    "interceptions_p90": ("Scan and step", "Coach points before each pass. Look over your shoulder, then step into the lane as the pass is played."),
    "tackles_won_p90": ("Stay on your feet", "1v1 in a 10 m channel. Defender wins a point only for a tackle that keeps the ball."),
    "tackle_success": ("Time it", "1v1 slow-to-fast. Only tackle when the attacker's touch is heavy. Count clean wins."),
    "blocks_p90": ("Get in the way", "2v2 in the box. Defender must get a body part on every shot."),
    "pressures_p90": ("Trigger press", "Press only when the receiver's first touch goes backwards. Hold position otherwise."),
    "ball_recoveries_p90": ("Second ball", "After every loose ball, race to it. First to three recoveries wins."),
    "threat_prevented_p90": ("Shadow the line", "In a 4v4, stay on the line between the ball and your own goal. Count passes you cut out."),
    "screening": ("Shield the keeper", "Defend without tackling: your only job is to stay between the ball and the goal for five minutes."),
    "distance_km": ("Box-to-box relay", "Sprint to the far box, play a one-two, recover to your own box. Six reps."),
    "sprints": ("Repeat sprints", "Six 20 m sprints with a jog back. Keep the last one as fast as the first."),
    "top_speed_ms": ("Flying 20s", "Build up over 10 m then sprint flat out for 20 m. Four reps, full rest."),
    "time_to_release": ("Picture first", "Before the ball arrives, say out loud where it is going next. Then play it in two touches."),
}

ARCHETYPE_INTRO = {
    "Shield": "The player who ends attacks before they start. He stands between the ball and his own goal, reads the pass, and steps in.",
    "Metronome": "The player who keeps the team ticking. Lots of passes, nearly all of them arrive, and the tempo is his.",
    "Creator": "The player who makes danger. His passes move the ball into places the defence does not want it.",
    "Finisher": "The player who gets into scoring positions and takes the chance.",
    "Engine": "The player who covers the ground. Always available, always running.",
    "Presser": "The player who hunts the ball and forces the mistake.",
    "Wall": "The last line. Blocks, tackles and tidies up in the box.",
    "Carrier": "The player who drives forward with the ball at his feet.",
    "AllRounder": "No single standout number, a bit of everything. The team shape would miss him.",
}


def _pct(v):
    return f"{round(v * 100)}%"


def build_playbook(st, pid: str) -> dict:
    fp = st.fingerprints.get(pid)
    if not fp:
        return {"error": f"no fingerprint for {pid}"}
    s = st.player_stats[pid]
    m = fp["metrics"]
    hht = fp["how_he_thinks"]
    nm = fp["name"]
    first = nm.split()[0]
    ev = s["evidence"]
    arche = fp["archetype"]
    looks = []

    thinking = []

    def add(text, evidence=(), value=None, tag=None):
        looks.append({"text": text, "evidence": list(evidence)[:10], "value": value, "tag": tag})

    def think(text, evidence=(), value=None):
        thinking.append({"text": text, "evidence": list(evidence)[:10], "value": value, "tag": "thinking"})

    # archetype-specific first, so the top of the list is the point
    if arche == "Shield" or m["screening"] >= 0.3:
        add(f"He stays between the ball and his own goal. Today that was {_pct(m['screening'])} of the time the other team had it.",
            value=m["screening"], tag="Shield")
    if s["interceptions"] >= 3:
        add(f"He reads passes before they happen and steps in: {s['interceptions']} cut out today.", ev["interceptions"], s["interceptions"], tag="Shield")
    n_ended = sum(1 for p in st.possessions if p.ended_by == pid)
    if n_ended >= 5:
        add(f"He ended {n_ended} of the other team's attacks before they got to the box.",
            [p.end_event_id for p in st.possessions if p.ended_by == pid], n_ended, tag="Shield")
    if arche in ("Metronome",) or (s["passes"] >= 50 and m["pass_accuracy"] >= 0.88):
        add(f"He keeps the ball moving: {s['passes']} passes, {_pct(m['pass_accuracy'])} found a teammate.", ev["progressive_passes"], s["passes"], tag="Metronome")
    if arche in ("Creator",) or s["danger_created"] >= 1.5:
        add(f"He makes things happen with his passing: {s['progressive_passes']} passes that moved the team forward today.",
            ev["progressive_passes"], s["progressive_passes"], tag="Creator")
    if s["passes_into_danger"] >= 3:
        add(f"He plays passes into the dangerous zone, {s['passes_into_danger']} of them today.", ev["passes_into_danger"], s["passes_into_danger"], tag="Creator")
    if arche == "Finisher" or s["shots"] >= 3:
        add(f"He gets shots off: {s['shots']} today, worth {round(s['xg'], 2)} expected goals{', and ' + str(s['goals']) + ' went in' if s['goals'] else ''}.",
            ev["shots"], s["shots"], tag="Finisher")
    if arche == "Engine" or s.get("distance_km", 0) >= 13:
        add(f"He runs: {s['distance_km']} km covered" + (f" and {s['sprints']} sprints." if s["sprints"] else "."), value=s["distance_km"], tag="Engine")
    if arche == "Presser" or s["pressures"] >= 60:
        add(f"He closes people down: {s['pressures']} times he pressed the player on the ball.", value=s["pressures"], tag="Presser")
    if arche == "Wall" or s["blocks"] >= 2:
        add(f"He puts his body in the way: {s['blocks']} shots blocked and {s['tackles_won']} tackles won.", ev["blocks"] + ev["tackles_won"], s["blocks"], tag="Wall")
    if arche == "Carrier" or s["progressive_carries"] >= 4:
        add(f"He drives forward with the ball: {s['progressive_carries']} runs that took the team up the pitch.", ev["progressive_carries"], s["progressive_carries"], tag="Carrier")
    # how he thinks, in plain words
    faw_counts = dict(s.get("first_action_after_win") or {})
    total_faw = sum(faw_counts.values())
    if total_faw >= 3:
        top_k, top_n = max(faw_counts.items(), key=lambda kv: kv[1])
        verb = {"carry": "runs with it", "forward": "plays it forward", "sideways": "plays it sideways to keep it",
                "backward": "plays it back to keep it safe", "shot": "shoots"}[top_k]
        think(f"When he wins the ball, he usually {verb}: {top_n} of {total_faw} times today.",
              ev["interceptions"][:5] + ev["tackles_won"][:5], round(top_n / total_faw, 2))
    rz = hht.get("receives_in") or {}
    if rz:
        top = max(rz.items(), key=lambda kv: kv[1])
        think(f"He asks for the ball in the {top[0]}, {_pct(top[1])} of the time.", value=top[1])
    ttr = hht.get("time_to_release_s")
    if ttr is not None:
        tempo = "quickly, one or two touches" if ttr < 2.0 else ("in a couple of seconds" if ttr < 3.5 else "without rushing, he takes his time")
        think(f"He moves the ball on {tempo}: about {ttr} seconds on the ball before each pass.", value=ttr)

    # main points: his moments, ranked
    mine = [mm for mm in st.moments if mm["player"] == pid and mm["kind"] in ("goal", "chance", "stop", "key_pass")]
    signature = {"Shield": ("stop",), "Wall": ("stop",), "Presser": ("stop",), "Finisher": ("goal", "chance"),
                 "Creator": ("key_pass",), "Metronome": ("key_pass",), "Carrier": ("key_pass",), "Engine": ("stop", "key_pass")}
    sig = signature.get(arche, ("goal", "chance", "stop", "key_pass"))
    sig_points = sorted([mm for mm in mine if mm["kind"] in sig or mm["kind"] == "goal"], key=lambda mm: -mm["score"])[:4]
    rest = sorted([mm for mm in mine if mm not in sig_points], key=lambda mm: -mm["score"])[:2]
    chosen = sorted(sig_points + rest, key=lambda mm: mm["t"])
    points = []
    for mm in chosen:
        d = mm["detail"]
        if mm["kind"] == "goal":
            why = f"Goal, from {d['distance']} m. Chance quality {d['xg']}."
        elif mm["kind"] == "chance":
            why = f"A shot worth {d['xg']} expected goals from {d['distance']} m, {d['outcome'].replace('_', ' ')}."
        elif mm["kind"] == "stop":
            cf = st.counterfactual(mm["evidence"][0])
            why = (f"He {d['action']}ed with the attack at danger {d['danger_stopped']}. In this match, "
                   f"{round(cf.get('shot_rate_from_here', 0) * 100)}% of attacks that got this far ended in a shot.")
            if d["action"] == "interception":
                why = why.replace("interceptioned", "cut out the pass")
            elif d["action"] == "tackle":
                why = why.replace("tackleed", "won the tackle")
            else:
                why = why.replace("blocked", "blocked the shot")
        else:
            why = (f"A {d['distance']} m pass to {st.data.name_of(d['receiver'])} that moved the danger from "
                   f"{d['danger_before']} to {d['danger_after']}. Difficulty {d['difficulty']} out of 100.")
        points.append({"kind": mm["kind"], "t": mm["t"], "minute": mm["minute"], "rank": mm["rank"], "why": why,
                       "evidence": mm["evidence"], "x": mm["x"], "y": mm["y"], "detail": d})

    # work on: two weakest metrics with a drill each, skipping things that make no sense for the role
    skip = {"goals_p90", "xg_p90", "shots_p90"} if fp["role"] in ("LCB", "RCB", "CDM", "LB", "RB") else set()
    work = []
    for w in fp["weaknesses"]:
        k = w["metric"]
        if k in skip or k not in METRIC_DRILLS or k == "time_to_release_inv":
            continue
        name, how = METRIC_DRILLS[k]
        work.append({"metric": k, "friendly": FRIENDLY.get(k, k), "value": w["value"], "drill": name, "how": how})
        if len(work) == 2:
            break
    best = [{"metric": b["metric"], "friendly": FRIENDLY.get(b["metric"], b["metric"]), "value": b["value"]} for b in fp["strengths"]]
    train = []
    for b in fp["strengths"][:2]:
        if b["metric"] in METRIC_DRILLS:
            name, how = METRIC_DRILLS[b["metric"]]
            train.append({"metric": b["metric"], "friendly": FRIENDLY.get(b["metric"]), "drill": name, "how": how})

    return {
        "player": pid, "name": nm, "first_name": first, "archetype": arche, "archetype_label": fp["archetype_label"],
        "intro": ARCHETYPE_INTRO.get(arche, ""),
        "looks_like": (sorted(looks, key=lambda l: 0 if l["tag"] == arche else 1)[:3] + thinking[:3]),
        "main_points": points,
        "best_at": best,
        "train_like_him": train,
        "work_on": work,
    }
