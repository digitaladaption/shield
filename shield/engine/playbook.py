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
    "carry_m_p90": "ground covered on the ball", "shots_p90": "shots", "xg_p90": "quality of chances taken", "goals_p90": "goals",
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
    "progressive_carries_p90": ("Drive the gate", "Dribble through a two-yard gate under pressure, then release. Count clean gates."),
    "shots_p90": ("Shoot on sight", "Inside the box, your first option is a shot. One touch to set, one to hit."),
    "xg_p90": ("Find the pocket", "Receive between two defenders on the edge of the box, turn and shoot inside 3 seconds."),
    "goals_p90": ("One-touch finish", "Service from both wings, finish first time. Track shots on target, not goals."),
    "interceptions_p90": ("Scan and step", "Coach points before each pass. Look over your shoulder, then step into the lane as the pass is played."),
    "tackles_won_p90": ("Stay on your feet", "1v1 in a ten-yard channel. Defender wins a point only for a tackle that keeps the ball."),
    "tackle_success": ("Time it", "1v1 slow-to-fast. Only tackle when the attacker's touch is heavy. Count clean wins."),
    "blocks_p90": ("Get in the way", "2v2 in the box. Defender must get a body part on every shot."),
    "pressures_p90": ("Trigger press", "Press only when the receiver's first touch goes backwards. Hold position otherwise."),
    "ball_recoveries_p90": ("Second ball", "After every loose ball, race to it. First to three recoveries wins."),
    "threat_prevented_p90": ("Shadow the line", "In a 4v4, stay on the line between the ball and your own goal. Count passes you cut out."),
    "screening": ("Shield the keeper", "Defend without tackling: your only job is to stay between the ball and the goal for five minutes."),
    "distance_km": ("Box-to-box relay", "Sprint to the far box, play a one-two, recover to your own box. Six reps."),
    "sprints": ("Repeat sprints", "Six 20-yard sprints with a jog back. Keep the last one as fast as the first."),
    "top_speed_ms": ("Flying 20s", "Build up over ten yards then sprint flat out for 20 yards. Four reps, full rest."),
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
    from . import i18n, units
    from .i18n_ui import ARCH, LOOKS, TEMPO, VERB, WHY, ZONE, drill as drill_i18n
    LANGS = i18n.LANGS

    def tr(key, **params):
        """Render a playbook line in every language."""
        out = {}
        for lang in LANGS:
            tpl = LOOKS[key].get(lang) or LOOKS[key]["en"]
            out[lang] = tpl.format(**{k: (v.get(lang) if isinstance(v, dict) else v) for k, v in params.items()})
        return out

    def add(key, params, evidence=(), value=None, tag=None, diagram=None):
        texts = tr(key, **params)
        looks.append({"text": texts["en"], "i18n": texts, "evidence": list(evidence)[:10], "value": value, "tag": tag, "diagram": diagram})

    def think(key, params, evidence=(), value=None, diagram=None):
        texts = tr(key, **params)
        thinking.append({"text": texts["en"], "i18n": texts, "evidence": list(evidence)[:10], "value": value, "tag": "thinking", "diagram": diagram})

    def dg(kind, ids=None, **kw):
        return {"kind": kind, "ids": list(ids or [])[:40], **kw}

    # archetype-specific first, so the top of the list is the point
    if arche == "Shield" or m["screening"] >= 0.3:
        add("screen", dict(pct=_pct(m["screening"])), value=m["screening"], tag="Shield", diagram=dg("heat_defending", screen=True))
    if s["interceptions"] >= 3:
        add("reads", dict(n=s["interceptions"]), ev["interceptions"], s["interceptions"], tag="Shield", diagram=dg("intercepts", ev["interceptions"]))
    n_ended = sum(1 for p in st.possessions if p.ended_by == pid)
    if n_ended >= 5:
        ends = [p.end_event_id for p in st.possessions if p.ended_by == pid]
        add("ended", dict(n=n_ended), ends, n_ended, tag="Shield", diagram=dg("dots", ends))
    if arche in ("Metronome",) or (s["passes"] >= 50 and m["pass_accuracy"] >= 0.88):
        add("metronome", dict(passes=s["passes"], pct=_pct(m["pass_accuracy"])), ev["progressive_passes"], s["passes"], tag="Metronome", diagram=dg("arrows", ev["progressive_passes"]))
    if arche in ("Creator",) or s["danger_created"] >= 1.5:
        add("creator", dict(n=s["progressive_passes"]), ev["progressive_passes"], s["progressive_passes"], tag="Creator", diagram=dg("arrows", ev["progressive_passes"]))
    if s["passes_into_danger"] >= 3:
        add("into_danger", dict(n=s["passes_into_danger"]), ev["passes_into_danger"], s["passes_into_danger"], tag="Creator", diagram=dg("arrows", ev["passes_into_danger"]))
    if arche == "Finisher" or s["shots"] >= 3:
        goals = {lang: (LOOKS["shots_goals"][lang].format(n=s["goals"]) if s["goals"] else "") for lang in LANGS}
        add("shots", dict(shots=s["shots"], xg=round(s["xg"], 2), goals=goals), ev["shots"], s["shots"], tag="Finisher", diagram=dg("shots", ev["shots"]))
    if arche == "Engine" or s.get("distance_km", 0) >= 13:
        sprints = {lang: (LOOKS["runs_sprints"][lang].format(n=s["sprints"]) if s["sprints"] else "") for lang in LANGS}
        add("runs", dict(km=s["distance_km"], sprints=sprints), value=s["distance_km"], tag="Engine", diagram=dg("heat_all"))
    if arche == "Presser" or s["pressures"] >= 60:
        add("presses", dict(n=s["pressures"]), value=s["pressures"], tag="Presser", diagram=dg("heat_defending"))
    if arche == "Wall" or s["blocks"] >= 2:
        add("wall", dict(blocks=s["blocks"], tackles=s["tackles_won"]), ev["blocks"] + ev["tackles_won"], s["blocks"], tag="Wall", diagram=dg("dots", ev["blocks"] + ev["tackles_won"]))
    if arche == "Carrier" or s["progressive_carries"] >= 4:
        add("carries", dict(n=s["progressive_carries"]), ev["progressive_carries"], s["progressive_carries"], tag="Carrier", diagram=dg("arrows", ev["progressive_carries"]))
    # how he thinks, in plain words
    faw_counts = dict(s.get("first_action_after_win") or {})
    total_faw = sum(faw_counts.values())
    if total_faw >= 3:
        top_k, top_n = max(faw_counts.items(), key=lambda kv: kv[1])
        think("win_then", dict(verb={lang: VERB[lang][top_k] for lang in LANGS}, n=top_n, total=total_faw),
              ev["interceptions"][:5] + ev["tackles_won"][:5], round(top_n / total_faw, 2),
              diagram=dg("win_then", ev["interceptions"] + ev["tackles_won"]))
    rz = hht.get("receives_in") or {}
    if rz:
        top = max(rz.items(), key=lambda kv: kv[1])
        think("receives", dict(zone={lang: ZONE[lang].get(top[0], top[0]) for lang in LANGS}, pct=_pct(top[1])), value=top[1], diagram=dg("thirds", shares=rz))
    ttr = hht.get("time_to_release_s")
    if ttr is not None:
        tk = "fast" if ttr < 2.0 else ("mid" if ttr < 3.5 else "slow")
        think("release", dict(tempo={lang: TEMPO[lang][tk] for lang in LANGS}, s=round(ttr, 1)), value=ttr)

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
        why = {}
        for lang in LANGS:
            if mm["kind"] == "goal":
                why[lang] = WHY["goal"][lang].format(where=units.shot_where(d["distance"], mm["x"], mm["y"], lang), xg=d["xg"])
            elif mm["kind"] == "chance":
                why[lang] = WHY["chance"][lang].format(where=units.shot_where(d["distance"], mm["x"], mm["y"], lang), xg=d["xg"],
                                                       outcome=i18n.word(d["outcome"], lang))
            elif mm["kind"] == "stop":
                cf = st.counterfactual(mm["evidence"][0])
                why[lang] = WHY["stop"][lang].format(did=WHY["did"][lang][d["action"]], d=d["danger_stopped"],
                                                     pct=round(cf.get("shot_rate_from_here", 0) * 100))
            else:
                why[lang] = WHY["key_pass"][lang].format(dist=units.dist_prose(d["distance"], lang), receiver=st.data.name_of(d["receiver"]).split()[-1],
                                                         d0=d["danger_before"], d1=d["danger_after"], diff=d["difficulty"])
        points.append({"kind": mm["kind"], "t": mm["t"], "minute": mm["minute"], "rank": mm["rank"], "why": why["en"], "why_i18n": why,
                       "evidence": mm["evidence"], "x": mm["x"], "y": mm["y"], "detail": d, "team": mm.get("team"), "player": pid,
                       "possession_id": mm.get("possession_id")})

    # work on: two weakest metrics with a drill each, skipping things that make no sense for the role
    def drill_entry(metric, value=None):
        name, how = METRIC_DRILLS[metric]
        return {"metric": metric, "friendly": FRIENDLY.get(metric, metric),
                "friendly_i18n": {lang: i18n.metric(metric, lang) for lang in LANGS},
                "value": value, "drill": name, "how": how,
                "drill_i18n": {lang: (drill_i18n(name, lang).get("name") or name) for lang in LANGS},
                "how_i18n": {lang: (drill_i18n(name, lang).get("how") or how) for lang in LANGS}}

    skip = {"goals_p90", "xg_p90", "shots_p90"} if fp["role"] in ("LCB", "RCB", "CDM", "LB", "RB") else set()
    work = []
    for w in fp["weaknesses"]:
        k = w["metric"]
        if k in skip or k not in METRIC_DRILLS or k == "time_to_release_inv":
            continue
        work.append(drill_entry(k, w["value"]))
        if len(work) == 2:
            break
    best = [{"metric": b["metric"], "friendly": FRIENDLY.get(b["metric"], b["metric"]),
             "friendly_i18n": {lang: i18n.metric(b["metric"], lang) for lang in LANGS}, "value": b["value"]} for b in fp["strengths"]]
    train = [drill_entry(b["metric"]) for b in fp["strengths"][:2] if b["metric"] in METRIC_DRILLS]
    a = ARCH.get(arche, {})

    return {
        "player": pid, "name": nm, "first_name": first, "archetype": arche, "archetype_label": fp["archetype_label"],
        "intro": ARCHETYPE_INTRO.get(arche, ""),
        "intro_i18n": a.get("intro", {}), "archetype_label_i18n": a.get("label", {}), "blurb_i18n": a.get("blurb", {}),
        "looks_like": (sorted(looks, key=lambda l: 0 if l["tag"] == arche else 1)[:3] + thinking[:3]),
        "main_points": points,
        "best_at": best,
        "train_like_him": train,
        "work_on": work,
    }
