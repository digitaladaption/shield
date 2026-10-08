"""
Deterministic stats engine.

Everything here is computed from events (and optionally frames). No model is
involved, so every number is reproducible and every fact carries the event
IDs that support it. The agents phrase; this layer decides what is true.

Main entry point: Engine(data).snapshot(t) -> MatchState up to time t.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from .match import MatchData

OUTFIELD = {"LB", "LCB", "RCB", "RB", "CDM", "LCM", "RCM", "LM", "RM", "LW", "RW", "ST", "LS", "RS"}
DEFENSIVE_ACTIONS = {"interception", "tackle", "block"}


# --------------------------------------------------------------------------- data
@dataclass
class Possession:
    id: int
    team: str
    start_t: float
    end_t: float
    events: list[dict] = field(default_factory=list)
    peak_danger: float = 0.0
    peak_event_id: str | None = None
    outcome: str = "ongoing"      # goal | shot | turnover | ongoing
    ended_by: str | None = None   # player id who ended it (defensive action)
    end_event_id: str | None = None
    xg: float = 0.0
    passes: int = 0

    @property
    def duration(self) -> float:
        return max(0.0, self.end_t - self.start_t)


@dataclass
class Fact:
    id: str
    text: str
    value: float | int | str | None
    evidence: list[str]
    tags: list[str] = field(default_factory=list)
    player: str | None = None
    team: str | None = None
    t: float | None = None

    def to_dict(self) -> dict:
        return {"id": self.id, "text": self.text, "value": self.value, "evidence": self.evidence,
                "tags": self.tags, "player": self.player, "team": self.team, "t": self.t}


# --------------------------------------------------------------------------- helpers
def per90(v: float, minutes: float) -> float:
    return round(v * 90.0 / max(minutes, 1.0), 2)


def z(values: dict[str, float]) -> dict[str, float]:
    vals = list(values.values())
    if len(vals) < 2:
        return {k: 0.0 for k in values}
    mu = statistics.mean(vals)
    sd = statistics.pstdev(vals) or 1.0
    return {k: (v - mu) / sd for k, v in values.items()}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


# --------------------------------------------------------------------------- engine
class Engine:
    def __init__(self, data: MatchData):
        self.data = data
        self.L, self.W = data.pitch
        self.players = data.players
        self.teams = ("home", "away")
        self.outfield = [pid for pid, p in self.players.items() if p["role"] in OUTFIELD]

    # ---------------------------------------------------------------- snapshot
    def snapshot(self, t: float | None = None) -> "MatchState":
        """Full analysis of everything that happened up to time t (seconds)."""
        events = self.data.events if t is None else [e for e in self.data.events if e["t"] <= t]
        t_end = t if t is not None else (events[-1]["t"] if events else 0.0)
        state = MatchState(self, events, t_end)
        state.compute()
        return state


class MatchState:
    def __init__(self, engine: Engine, events: list[dict], t_end: float):
        self.eng = engine
        self.data = engine.data
        self.events = events
        self.t_end = t_end
        self.minutes = max(1.0, t_end / 60.0)
        self.by_id = {e["id"]: e for e in events}
        self.possessions: list[Possession] = []
        self.poss_by_id: dict[int, Possession] = {}
        self.score = {"home": 0, "away": 0}
        self.player_stats: dict[str, dict] = {}
        self.team_stats: dict[str, dict] = {}
        self.threat_prevented: list[dict] = []
        self.momentum: list[dict] = []
        self.moments: list[dict] = []
        self.fingerprints: dict[str, dict] = {}
        self.facts: list[Fact] = []
        self._fact_n = 0

    # ---------------------------------------------------------------- compute
    def compute(self):
        self._build_possessions()
        self._player_stats()
        self._threat_prevented()
        self._positional()
        self._momentum()
        self._fingerprints()
        self._key_moments()
        self._team_stats()
        self._facts()

    # ---------------------------------------------------------------- possessions
    def _build_possessions(self):
        cur: Possession | None = None
        for e in self.events:
            pid = e["possession_id"]
            if cur is None or pid != cur.id:
                if cur is not None:
                    cur.end_t = e["t"]
                cur = Possession(id=pid, team=e.get("team", ""), start_t=e["t"], end_t=e["t"])
                if e["type"] == "possession_change":
                    cur.team = e["team"]
                self.possessions.append(cur)
                self.poss_by_id[pid] = cur
            cur.events.append(e)
            cur.end_t = e["t"]
            d = None
            if e["type"] == "pass":
                cur.passes += 1
                d = e["danger_before"]
                if e["outcome"] == "complete":
                    d = max(d, e["danger_intended"])
            elif e["type"] == "shot":
                d = e["danger"]
                cur.xg += e["xg"]
                cur.outcome = "goal" if e["outcome"] == "goal" else "shot"
            elif e["type"] in ("carry", "tackle"):
                d = e.get("danger")
            if d is not None and d > cur.peak_danger:
                cur.peak_danger, cur.peak_event_id = d, e["id"]
        # which defensive action ended each possession: the first event of the
        # next possession is a possession_change with a reason, and the
        # defensive event (interception/tackle) sits just before it.
        for i, p in enumerate(self.possessions):
            if p.outcome in ("goal", "shot") and p.outcome == "goal":
                self.score[p.team] += 1
            if i + 1 < len(self.possessions):
                nxt = self.possessions[i + 1]
                first = nxt.events[0]
                if first["type"] == "possession_change" and first.get("reason") in ("interception", "tackle", "block"):
                    # find the defensive event in this possession's tail
                    for e in reversed(p.events):
                        if e["type"] in DEFENSIVE_ACTIONS and e.get("team") == nxt.team:
                            p.ended_by, p.end_event_id = e["player"], e["id"]
                            break
                if p.outcome == "ongoing":
                    p.outcome = "turnover"
        # Defensive events are emitted with the *defender's* possession_id?
        # No: they are emitted before give_ball, so they carry the attacking
        # possession id. The loop above relies on that.

    # ---------------------------------------------------------------- player stats
    def _player_stats(self):
        S = {}
        for pid, p in self.data.players.items():
            S[pid] = {
                "name": p["name"], "team": p["team"], "role": p["role"], "number": p["number"],
                "passes": 0, "passes_complete": 0, "progressive_passes": 0, "pass_difficulty": [],
                "passes_into_danger": 0, "danger_created": 0.0,
                "carries": 0, "progressive_carries": 0, "carry_m": 0.0,
                "shots": 0, "goals": 0, "xg": 0.0,
                "interceptions": 0, "tackles_won": 0, "tackles_lost": 0, "blocks": 0, "pressures": 0,
                "danger_stopped": 0.0, "threat_prevented": 0.0, "xg_prevented": 0.0,
                "ball_recoveries": 0, "first_action_after_win": defaultdict(int),
                "receive_zone": defaultdict(int), "time_to_release": [],
                "evidence": defaultdict(list),
            }
        last_recovery: dict[str, dict] = {}
        last_receive: dict[str, float] = {}
        for e in self.events:
            pid = e.get("player")
            if pid not in S:
                continue
            s = S[pid]
            t = e["type"]
            if t == "pass":
                s["passes"] += 1
                s["pass_difficulty"].append(e["difficulty"])
                if e["outcome"] == "complete":
                    s["passes_complete"] += 1
                    gain = e["danger_intended"] - e["danger_before"]
                    if gain > 0:
                        s["danger_created"] += gain
                    if e["danger_intended"] >= 0.25:
                        s["passes_into_danger"] += 1
                        s["evidence"]["passes_into_danger"].append(e["id"])
                if e["progressive"]:
                    s["progressive_passes"] += 1
                    s["evidence"]["progressive_passes"].append(e["id"])
                if pid in last_receive:
                    s["time_to_release"].append(max(0.0, e["t_start"] - last_receive.pop(pid)))
                if pid in last_recovery:
                    rec = last_recovery.pop(pid)
                    d = self._pass_direction(e)
                    s["first_action_after_win"][d] += 1
                rcv = e.get("receiver")
                if e["outcome"] == "complete" and rcv in S:
                    last_receive[rcv] = e["t"]
                    S[rcv]["receive_zone"][self._zone(S[rcv]["team"], e["end_x"])] += 1
            elif t == "carry":
                s["carries"] += 1
                s["carry_m"] += e["distance"]
                if e["progressive_m"] >= 5:
                    s["progressive_carries"] += 1
                    s["evidence"]["progressive_carries"].append(e["id"])
                if pid in last_recovery:
                    last_recovery.pop(pid)
                    s["first_action_after_win"]["carry"] += 1
            elif t == "shot":
                s["shots"] += 1
                s["xg"] += e["xg"]
                s["evidence"]["shots"].append(e["id"])
                if e["outcome"] == "goal":
                    s["goals"] += 1
                    s["evidence"]["goals"].append(e["id"])
                if pid in last_recovery:
                    last_recovery.pop(pid)
                    s["first_action_after_win"]["shot"] += 1
            elif t == "interception":
                s["interceptions"] += 1
                s["ball_recoveries"] += 1
                s["evidence"]["interceptions"].append(e["id"])
                last_recovery[pid] = e
            elif t == "tackle":
                if e["outcome"] == "won":
                    s["tackles_won"] += 1
                    s["ball_recoveries"] += 1
                    s["evidence"]["tackles_won"].append(e["id"])
                    last_recovery[pid] = e
                else:
                    s["tackles_lost"] += 1
            elif t == "block":
                s["blocks"] += 1
                s["evidence"]["blocks"].append(e["id"])
            elif t == "pressure":
                s["pressures"] += 1
        self.player_stats = S

    def _pass_direction(self, e: dict) -> str:
        d = 1 if e["team"] == "home" else -1
        dx = (e["end_x"] - e["x"]) * d
        if dx >= 8:
            return "forward"
        if dx <= -8:
            return "backward"
        return "sideways"

    def _zone(self, team: str, x: float) -> str:
        u = x / self.eng.L if team == "home" else 1 - x / self.eng.L
        return "defensive third" if u < 1 / 3 else ("middle third" if u < 2 / 3 else "attacking third")

    # ---------------------------------------------------------------- threat prevented
    def _xg_curve(self):
        """Empirical: for possessions whose peak danger reached >= d, how much xG
        did they go on to produce? Bucketed by danger, blended with a prior so
        small samples don't blow up. Returns a function d -> expected xG."""
        done = [p for p in self.possessions if p.outcome != "ongoing"]
        buckets = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.35), (0.35, 0.5), (0.5, 0.7), (0.7, 1.01)]
        table = []
        for lo, hi in buckets:
            ps = [p for p in done if p.peak_danger >= lo]
            n = len(ps)
            emp = (sum(p.xg for p in ps) / n) if n else 0.0
            prior = 0.3 * ((lo + min(hi, 1.0)) / 2)
            w = n / (n + 8.0)
            table.append((lo, hi, round(w * emp + (1 - w) * prior, 4), n))
        self.xg_curve_table = table

        def f(d: float) -> float:
            for lo, hi, v, _ in table:
                if lo <= d < hi:
                    return v
            return table[-1][2]
        return f

    def _threat_prevented(self):
        curve = self._xg_curve()
        out = []
        for e in self.events:
            if e["type"] not in DEFENSIVE_ACTIONS:
                continue
            if e["type"] == "tackle" and e["outcome"] != "won":
                continue
            if e["type"] == "interception":
                d = e["danger_intended"]
                basis = "the pass was heading into a zone with danger"
            elif e["type"] == "tackle":
                d = e["danger"]
                basis = "the carrier was in a zone with danger"
            else:  # block
                shot = self._shot_for_block(e)
                d = shot["danger"] if shot else 0.3
                basis = "the shot had xG"
            xg = curve(d)
            if e["type"] == "block" and shot:
                xg = shot["xg"]
            rec = {"event_id": e["id"], "t": e["t"], "type": e["type"], "player": e["player"],
                   "team": e["team"], "danger_stopped": round(d, 3), "xg_prevented": round(xg, 3),
                   "basis": basis, "x": e["x"], "y": e["y"]}
            if e["type"] == "interception":
                rec["pass_id"] = e["pass_id"]
                rec["passer"] = e.get("passer")
            out.append(rec)
            s = self.player_stats[e["player"]]
            s["danger_stopped"] += d
            s["xg_prevented"] += xg
            s["threat_prevented"] += d  # headline number: sum of danger stopped
        self.threat_prevented = out

    def _shot_for_block(self, block: dict) -> dict | None:
        # the shot is the event immediately before the block with the shooter
        idx = self.events.index(block)
        for j in range(idx - 1, max(-1, idx - 4), -1):
            e = self.events[j]
            if e["type"] == "shot" and e["player"] == block.get("shooter"):
                return e
        return None

    # ---------------------------------------------------------------- positional (frames)
    def _positional(self):
        """Screening score and movement from frames, if available."""
        frames = self.data.frames
        for pid, s in self.player_stats.items():
            s.update({"distance_km": 0.0, "sprints": 0, "top_speed_ms": 0.0, "screening": 0.0,
                      "avg_x": 0.0, "avg_y": 0.0, "defending_ticks": 0})
        if not frames:
            return
        tick = self.data.meta["tick_seconds"]
        n = min(len(frames), int(self.t_end / tick) + 1)
        # which team has the ball at each tick: from possession list
        poss_team_at = self._possession_team_lookup()
        L, W = self.eng.L, self.eng.W
        acc = {pid: {"dist": 0.0, "sprints": 0, "sprinting": False, "top": 0.0, "screen": 0, "deft": 0,
                     "sx": 0.0, "sy": 0.0, "km_flag": 0} for pid in self.player_stats}
        prev = None
        match_top = 7.5          # a new match-high sprint above this is a milestone
        self.milestones = []
        for i in range(n):
            fr = frames[i]
            pt = poss_team_at(fr.t)
            bx, by = fr.ball
            for pid, (x, y) in fr.players.items():
                a = acc[pid]
                a["sx"] += x
                a["sy"] += y
                if prev is not None and pid in prev.players:
                    px, py = prev.players[pid]
                    step = math.hypot(x - px, y - py)
                    a["dist"] += step
                    sp = step / tick
                    if sp > match_top and sp >= 8.0 and sp < 12.0:
                        match_top = sp
                        self.milestones.append({"t": fr.t, "player": pid, "kind": "top_speed", "value": round(sp, 1),
                                                "x": x, "y": y})
                    a["top"] = max(a["top"], sp)
                    km = int(a["dist"] // 1000)
                    if km == 10 and km > a["km_flag"]:
                        a["km_flag"] = km
                        self.milestones.append({"t": fr.t, "player": pid, "kind": "distance", "value": km, "x": x, "y": y})
                    a["fast"] = a.get("fast", 0) + 1 if sp >= 7.0 else 0
                    if a["fast"] >= 3 and not a["sprinting"]:   # 1.5 s above 7 m/s counts as a sprint
                        a["sprints"] += 1
                        a["sprinting"] = True
                    elif sp < 5.5:
                        a["sprinting"] = False
                team = self.player_stats[pid]["team"]
                if pt and pt != team and self.player_stats[pid]["role"] != "GK":
                    a["deft"] += 1
                    gx = 0.0 if team == "home" else L
                    gy = W / 2
                    # distance from player to the ball->own goal line, and goal-side check
                    dseg, tproj = _dist_to_segment(x, y, bx, by, gx, gy)
                    if dseg <= 6.0 and 0.05 < tproj < 0.95:
                        a["screen"] += 1
            prev = fr
        for pid, a in acc.items():
            s = self.player_stats[pid]
            s["distance_km"] = round(a["dist"] / 1000, 2)
            s["sprints"] = a["sprints"]
            s["top_speed_ms"] = round(a["top"], 2)
            s["screening"] = round(a["screen"] / a["deft"], 3) if a["deft"] else 0.0
            s["defending_ticks"] = a["deft"]
            s["avg_x"] = round(a["sx"] / n, 1)
            s["avg_y"] = round(a["sy"] / n, 1)

    def _possession_team_lookup(self):
        bounds = [(p.start_t, p.end_t, p.team) for p in self.possessions]

        def f(t: float) -> str | None:
            # binary search would be nicer; linear with cache is fine for 10k frames
            lo, hi = 0, len(bounds) - 1
            while lo <= hi:
                mid = (lo + hi) // 2
                s, e, team = bounds[mid]
                if t < s:
                    hi = mid - 1
                elif t > e and mid + 1 < len(bounds) and t >= bounds[mid + 1][0]:
                    lo = mid + 1
                else:
                    return team
            return None
        return f

    # ---------------------------------------------------------------- momentum
    def _momentum(self):
        """5-minute windows: danger generated, possession changes (chaos), pressures."""
        win = 300.0
        n = int(math.ceil(self.t_end / win)) or 1
        rows = []
        for i in range(n):
            a, b = i * win, min((i + 1) * win, self.t_end)
            evs = [e for e in self.events if a <= e["t"] < b or (b == self.t_end and e["t"] == b)]
            danger = {"home": 0.0, "away": 0.0}
            shots = {"home": 0, "away": 0}
            changes = 0
            pressures = {"home": 0, "away": 0}
            for e in evs:
                tm = e.get("team")
                if e["type"] == "pass" and e["outcome"] == "complete" and tm:
                    danger[tm] += max(0.0, e["danger_intended"] - e["danger_before"])
                elif e["type"] == "shot" and tm:
                    shots[tm] += 1
                    danger[tm] += e["xg"]
                elif e["type"] == "possession_change":
                    changes += 1
                elif e["type"] == "pressure" and tm:
                    pressures[tm] += 1
            tot = danger["home"] + danger["away"]
            share = danger["home"] / tot if tot else 0.5
            rows.append({"window": i, "start": a, "end": b, "label": f"{mmss(a)}-{mmss(b)}",
                         "danger": {k: round(v, 3) for k, v in danger.items()},
                         "home_share": round(share, 3), "shots": shots,
                         "possession_changes": changes,
                         "chaos": round(changes / max(1.0, (b - a) / 60.0), 2),  # changes per minute
                         "pressures": pressures,
                         "evidence": [e["id"] for e in evs if e["type"] in ("shot", "possession_change")][:40]})
        self.momentum = rows
        if rows:
            ch = [r["chaos"] for r in rows]
            mu = statistics.mean(ch)
            for r in rows:
                r["regime"] = "chaos" if r["chaos"] > mu * 1.15 else ("control" if r["chaos"] < mu * 0.85 else "balanced")

    # ---------------------------------------------------------------- fingerprints
    ARCHETYPES = {
        "AllRounder": {"label": "The All-Rounder", "blurb": "No single standout number. Does a bit of everything.", "metrics": {}},
        "Shield": {"label": "The Shield", "blurb": "Ends attacks before they start. Screens the back line, reads passes, wins the ball.",
                   "metrics": {"interceptions_p90": 1.0, "threat_prevented_p90": 1.2, "screening": 1.0, "ball_recoveries_p90": 0.6}},
        "Metronome": {"label": "The Metronome", "blurb": "Keeps the ball moving. High volume, high accuracy, sets the tempo.",
                      "metrics": {"passes_p90": 1.2, "pass_accuracy": 1.0, "time_to_release_inv": 0.6}},
        "Creator": {"label": "The Creator", "blurb": "Moves the ball into danger. Progressive passes and passes that unlock defences.",
                    "metrics": {"danger_created_p90": 1.2, "progressive_passes_p90": 1.0, "passes_into_danger_p90": 0.8}},
        "Finisher": {"label": "The Finisher", "blurb": "Gets into scoring positions and takes the chances.",
                     "metrics": {"xg_p90": 1.2, "shots_p90": 1.0, "goals_p90": 0.6}},
        "Engine": {"label": "The Engine", "blurb": "Covers the ground. Distance, sprints, always available.",
                   "metrics": {"distance_km": 1.0, "sprints": 1.0, "carries_p90": 0.5}},
        "Presser": {"label": "The Presser", "blurb": "Hunts the ball. Pressures the carrier and forces mistakes.",
                    "metrics": {"pressures_p90": 1.3, "tackles_won_p90": 0.5}},
        "Wall": {"label": "The Wall", "blurb": "Last line. Blocks, tackles and clears up in the box.",
                 "metrics": {"blocks_p90": 1.0, "tackles_won_p90": 0.8, "tackle_success": 0.5}},
        "Carrier": {"label": "The Carrier", "blurb": "Drives forward with the ball at feet.",
                    "metrics": {"progressive_carries_p90": 1.2, "carry_m_p90": 1.0}},
    }

    def _fingerprints(self):
        m = self.minutes
        raw: dict[str, dict] = {}
        for pid in self.eng.outfield:
            s = self.player_stats[pid]
            ttr = statistics.mean(s["time_to_release"]) if s["time_to_release"] else 3.0
            raw[pid] = {
                "passes_p90": per90(s["passes"], m),
                "pass_accuracy": round(s["passes_complete"] / s["passes"], 3) if s["passes"] else 0.0,
                "pass_difficulty": round(statistics.mean(s["pass_difficulty"]), 1) if s["pass_difficulty"] else 0.0,
                "progressive_passes_p90": per90(s["progressive_passes"], m),
                "passes_into_danger_p90": per90(s["passes_into_danger"], m),
                "danger_created_p90": per90(s["danger_created"], m),
                "carries_p90": per90(s["carries"], m),
                "progressive_carries_p90": per90(s["progressive_carries"], m),
                "carry_m_p90": per90(s["carry_m"], m),
                "shots_p90": per90(s["shots"], m),
                "xg_p90": per90(s["xg"], m),
                "goals_p90": per90(s["goals"], m),
                "interceptions_p90": per90(s["interceptions"], m),
                "tackles_won_p90": per90(s["tackles_won"], m),
                "tackle_success": round(s["tackles_won"] / (s["tackles_won"] + s["tackles_lost"]), 3)
                if (s["tackles_won"] + s["tackles_lost"]) else 0.0,
                "blocks_p90": per90(s["blocks"], m),
                "pressures_p90": per90(s["pressures"], m),
                "ball_recoveries_p90": per90(s["ball_recoveries"], m),
                "threat_prevented_p90": per90(s["threat_prevented"], m),
                "xg_prevented_p90": per90(s["xg_prevented"], m),
                "screening": s["screening"],
                "distance_km": s["distance_km"],
                "sprints": s["sprints"],
                "top_speed_ms": s["top_speed_ms"],
                "time_to_release": round(ttr, 2),
                "time_to_release_inv": round(1.0 / (ttr + 0.5), 3),
            }
        # z-scores per metric across outfield players
        metrics = list(next(iter(raw.values())).keys()) if raw else []
        zs = {k: z({pid: raw[pid][k] for pid in raw}) for k in metrics}
        for pid in raw:
            scores = {}
            for name, spec in self.ARCHETYPES.items():
                if not spec["metrics"]:
                    continue
                tot = sum(zs[k][pid] * w for k, w in spec["metrics"].items())
                wsum = sum(spec["metrics"].values())
                scores[name] = round(clamp(50 + 20 * tot / wsum, 0, 100), 1)
            top = sorted(scores.items(), key=lambda kv: -kv[1])
            if top[0][1] < 52.0:
                top = [("AllRounder", top[0][1])] + top
            s = self.player_stats[pid]
            faw = s["first_action_after_win"]
            faw_total = sum(faw.values())
            rz = s["receive_zone"]
            rz_total = sum(rz.values())
            strengths = sorted(((k, zs[k][pid]) for k in metrics if k not in ("time_to_release_inv",)),
                               key=lambda kv: -kv[1])[:3]
            weaknesses = sorted(((k, zs[k][pid]) for k in metrics if k not in ("time_to_release_inv",)),
                                key=lambda kv: kv[1])[:3]
            self.fingerprints[pid] = {
                "player": pid, "name": s["name"], "team": s["team"], "role": s["role"],
                "metrics": raw[pid],
                "z": {k: round(zs[k][pid], 2) for k in metrics},
                "archetype": top[0][0], "archetype_label": self.ARCHETYPES[top[0][0]]["label"],
                "archetype_scores": scores,
                "strengths": [{"metric": k, "z": round(v, 2), "value": raw[pid][k]} for k, v in strengths],
                "weaknesses": [{"metric": k, "z": round(v, 2), "value": raw[pid][k]} for k, v in weaknesses],
                "how_he_thinks": {
                    "first_action_after_winning_ball": {k: round(v / faw_total, 2) for k, v in faw.items()} if faw_total else {},
                    "receives_in": {k: round(v / rz_total, 2) for k, v in rz.items()} if rz_total else {},
                    "time_to_release_s": raw[pid]["time_to_release"],
                    "screening_share": s["screening"],
                },
                "evidence": {k: v[:12] for k, v in s["evidence"].items()},
            }

    # ---------------------------------------------------------------- key moments
    def _key_moments(self):
        moments = []
        tp_by_event = {r["event_id"]: r for r in self.threat_prevented}
        for e in self.events:
            t = e["type"]
            if t == "shot":
                score = 5.0 + e["xg"] if e["outcome"] == "goal" else e["xg"] * 4.0
                kind = "goal" if e["outcome"] == "goal" else "chance"
                if kind == "goal" or e["xg"] >= 0.12:
                    moments.append(self._moment(kind, e, score, [e["id"]],
                                                {"xg": e["xg"], "outcome": e["outcome"], "distance": e["distance"],
                                                 "shot_speed": e["speed"]}))
            elif t == "pass" and e["outcome"] == "complete":
                gain = e["danger_intended"] - e["danger_before"]
                if gain >= 0.3 or (e["difficulty"] >= 65 and e["progressive"] and gain >= 0.15):
                    score = gain * 1.6 + e["difficulty"] / 250.0
                    moments.append(self._moment("key_pass", e, score, [e["id"]],
                                                {"danger_gain": round(gain, 3), "danger_before": e["danger_before"],
                                                 "danger_after": e["danger_intended"], "receiver": e["receiver"],
                                                 "distance": e["distance"], "pass_speed": e["speed"],
                                                 "difficulty": e["difficulty"], "end_x": e["end_x"], "end_y": e["end_y"]}))
            elif e["id"] in tp_by_event:
                r = tp_by_event[e["id"]]
                score = r["danger_stopped"] * 1.6 + r["xg_prevented"] * 6.0
                if r["danger_stopped"] >= 0.2:
                    ev = [e["id"]] + ([e["pass_id"]] if t == "interception" else [])
                    moments.append(self._moment("stop", e, score, ev,
                                                {"danger_stopped": r["danger_stopped"], "xg_prevented": r["xg_prevented"],
                                                 "action": t, "basis": r["basis"]}))
        for ms in getattr(self, "milestones", []):
            if ms["t"] > self.t_end:
                continue
            moments.append({"kind": "milestone", "t": ms["t"], "minute": int(ms["t"] // 60), "team": self.data.team_of(ms["player"]),
                            "player": ms["player"], "score": 0.3, "evidence": [],
                            "detail": {"milestone": ms["kind"], "value": ms["value"]}, "x": ms["x"], "y": ms["y"]})
        # momentum shifts
        prev = None
        for r in self.momentum:
            if prev is not None and abs(r["home_share"] - prev["home_share"]) >= 0.35 and (r["danger"]["home"] + r["danger"]["away"]) > 0.4:
                team = "home" if r["home_share"] > prev["home_share"] else "away"
                moments.append({"kind": "momentum_shift", "t": r["start"], "minute": int(r["start"] // 60),
                                "team": team, "player": None, "score": 0.8,
                                "evidence": r["evidence"][:12],
                                "detail": {"window": r["label"], "home_share": r["home_share"],
                                           "previous_home_share": prev["home_share"], "regime": r["regime"]}})
            if r["regime"] == "chaos" and r["possession_changes"] >= 12:
                moments.append({"kind": "chaos", "t": r["start"], "minute": int(r["start"] // 60), "team": None,
                                "player": None, "score": 0.5, "evidence": r["evidence"][:12],
                                "detail": {"window": r["label"], "possession_changes": r["possession_changes"],
                                           "chaos_per_min": r["chaos"]}})
            prev = r
        moments.sort(key=lambda m: -m["score"])
        for i, m in enumerate(moments):
            m["rank"] = i + 1
        self.moments = moments

    def _moment(self, kind, e, score, evidence, detail):
        return {"kind": kind, "t": e["t"], "minute": e["minute"], "team": e.get("team"),
                "player": e.get("player"), "score": round(score, 3), "evidence": evidence,
                "detail": detail, "x": e.get("x"), "y": e.get("y"), "possession_id": e["possession_id"]}

    # ---------------------------------------------------------------- team stats
    def _team_stats(self):
        for team in self.eng.teams:
            ps = [s for s in self.player_stats.values() if s["team"] == team]
            tot = lambda k: sum(s[k] for s in ps)
            poss = [p for p in self.possessions if p.team == team]
            dur = sum(p.duration for p in poss)
            all_dur = sum(p.duration for p in self.possessions) or 1.0
            self.team_stats[team] = {
                "club": self.data.clubs[team], "goals": self.score[team],
                "shots": tot("shots"), "xg": round(tot("xg"), 2),
                "passes": tot("passes"), "pass_accuracy": round(tot("passes_complete") / tot("passes"), 3) if tot("passes") else 0,
                "possession": round(dur / all_dur, 3),
                "possessions": len(poss),
                "interceptions": tot("interceptions"), "tackles_won": tot("tackles_won"), "blocks": tot("blocks"),
                "pressures": tot("pressures"),
                "threat_prevented": round(tot("threat_prevented"), 2),
                "xg_prevented": round(tot("xg_prevented"), 2),
                "danger_created": round(tot("danger_created"), 2),
                "attacks_ended_by": self._attacks_ended_by(team),
            }

    def _attacks_ended_by(self, team: str) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for p in self.possessions:
            if p.team != team and p.ended_by:
                out[p.ended_by] += 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    # ---------------------------------------------------------------- facts
    def _fact(self, text, value, evidence, tags=(), player=None, team=None, t=None) -> Fact:
        self._fact_n += 1
        f = Fact(id=f"f{self._fact_n}", text=text, value=value, evidence=list(evidence)[:20],
                 tags=list(tags), player=player, team=team, t=t)
        self.facts.append(f)
        return f

    def _facts(self):
        clubs = self.data.clubs
        h, a = self.team_stats["home"], self.team_stats["away"]
        goals_ev = [e["id"] for e in self.events if e["type"] == "shot" and e["outcome"] == "goal"]
        self._fact(f"Score at {mmss(self.t_end)}: {clubs['home']} {h['goals']}, {clubs['away']} {a['goals']}",
                   f"{h['goals']}-{a['goals']}", goals_ev, ["score"])
        for team, ts in (("home", h), ("away", a)):
            shots_ev = [e["id"] for e in self.events if e["type"] == "shot" and e["team"] == team]
            self._fact(f"{ts['club']}: {ts['shots']} shots, {ts['xg']} xG", ts["xg"], shots_ev, ["shots"], team=team)
            self._fact(f"{ts['club']}: {round(ts['possession']*100)}% possession, {ts['passes']} passes at {round(ts['pass_accuracy']*100)}% accuracy",
                       round(ts["possession"] * 100), [], ["possession"], team=team)
        # top performers
        for pid, s in self.player_stats.items():
            if s["role"] == "GK":
                continue
            nm = s["name"]
            if s["interceptions"] >= 3:
                self._fact(f"{nm} made {s['interceptions']} interceptions", s["interceptions"],
                           s["evidence"]["interceptions"], ["defence", "interceptions"], player=pid, team=s["team"])
            if s["threat_prevented"] >= 0.8:
                tp_ev = [r["event_id"] for r in self.threat_prevented if r["player"] == pid]
                self._fact(f"{nm} prevented {round(s['threat_prevented'], 2)} threat (sum of danger stopped) and about {round(s['xg_prevented'], 2)} xG",
                           round(s["threat_prevented"], 2), tp_ev, ["defence", "threat_prevented"], player=pid, team=s["team"])
                ended = self.team_stats["away" if s["team"] == "home" else "home"]  # not used
                n_ended = sum(1 for p in self.possessions if p.ended_by == pid)
                if n_ended:
                    self._fact(f"{nm} ended {n_ended} opposition attacks", n_ended,
                               [p.end_event_id for p in self.possessions if p.ended_by == pid][:20],
                               ["defence", "attacks_ended"], player=pid, team=s["team"])
            if s["goals"]:
                self._fact(f"{nm} scored {s['goals']}", s["goals"], s["evidence"]["goals"], ["attack", "goals"], player=pid, team=s["team"])
            if s["xg"] >= 0.4:
                self._fact(f"{nm}: {s['shots']} shots worth {round(s['xg'], 2)} xG", round(s["xg"], 2),
                           s["evidence"]["shots"], ["attack", "shots"], player=pid, team=s["team"])
            if s["danger_created"] >= 1.0:
                self._fact(f"{nm} created {round(s['danger_created'], 2)} danger with his passing ({s['progressive_passes']} progressive passes)",
                           round(s["danger_created"], 2), s["evidence"]["progressive_passes"], ["attack", "creation"], player=pid, team=s["team"])
            if s["passes"] >= 25 and s["pass_difficulty"]:
                diff = round(statistics.mean(s["pass_difficulty"]), 0)
                acc = round(100 * s["passes_complete"] / s["passes"])
                if diff >= 38 or acc >= 90:
                    self._fact(f"{nm} completed {acc}% of {s['passes']} passes at an average difficulty of {int(diff)} out of 100",
                               acc, s["evidence"]["progressive_passes"][:10], ["attack", "pass_quality"], player=pid, team=s["team"])
            if s.get("distance_km", 0) >= 11.5:
                self._fact(f"{nm} covered {s['distance_km']} km with {s['sprints']} sprints", s["distance_km"], [],
                           ["physical"], player=pid, team=s["team"])
            if s.get("screening", 0) >= 0.3 and s["role"] in ("CDM", "LCM", "RCM"):
                self._fact(f"{nm} was screening the line between ball and his own goal for {round(s['screening']*100)}% of defending time",
                           round(s["screening"] * 100), [], ["defence", "positioning"], player=pid, team=s["team"])
        # moments
        for m in self.moments[:12]:
            d = m["detail"]
            nm = self.data.name_of(m["player"]) if m["player"] else None
            if m["kind"] == "goal":
                self._fact(f"GOAL {mmss(m['t'])}: {nm} ({clubs[m['team']]}) scored from {d['distance']} m, xG {d['xg']}",
                           d["xg"], m["evidence"], ["moment", "goal"], player=m["player"], team=m["team"], t=m["t"])
            elif m["kind"] == "chance":
                self._fact(f"Chance {mmss(m['t'])}: {nm} shot from {d['distance']} m, xG {d['xg']}, {d['outcome'].replace('_', ' ')}",
                           d["xg"], m["evidence"], ["moment", "chance"], player=m["player"], team=m["team"], t=m["t"])
            elif m["kind"] == "key_pass":
                self._fact(f"Key pass {mmss(m['t'])}: {nm} found {self.data.name_of(d['receiver'])} with a {d['distance']} m pass, danger {d['danger_before']} to {d['danger_after']}, difficulty {d['difficulty']}",
                           d["danger_gain"], m["evidence"], ["moment", "key_pass"], player=m["player"], team=m["team"], t=m["t"])
            elif m["kind"] == "milestone":
                what = f"hit {d['value']} m/s, the fastest sprint of the match so far" if d["milestone"] == "top_speed" else f"passed {d['value']} km covered"
                self._fact(f"{mmss(m['t'])}: {nm} {what}", d["value"], [], ["moment", "physical"], player=m["player"], team=m["team"], t=m["t"])
            elif m["kind"] == "stop":
                self._fact(f"Stop {mmss(m['t'])}: {nm} {d['action']} with danger {d['danger_stopped']} stopped, about {d['xg_prevented']} xG prevented",
                           d["danger_stopped"], m["evidence"], ["moment", "stop"], player=m["player"], team=m["team"], t=m["t"])
            elif m["kind"] == "momentum_shift":
                self._fact(f"Momentum shift in {d['window']}: {clubs[m['team']]} took over, home danger share {d['previous_home_share']} to {d['home_share']}",
                           d["home_share"], m["evidence"], ["moment", "momentum"], team=m["team"], t=m["t"])
            elif m["kind"] == "chaos":
                self._fact(f"Chaos spell {d['window']}: {d['possession_changes']} possession changes, {d['chaos_per_min']} per minute",
                           d["possession_changes"], m["evidence"], ["moment", "chaos"], t=m["t"])
        # regimes
        regimes = [r["regime"] for r in self.momentum]
        if regimes:
            self._fact(f"Match rhythm: {regimes.count('control')} control windows, {regimes.count('chaos')} chaos windows, "
                       f"{regimes.count('balanced')} balanced (5-minute windows)", regimes.count("chaos"), [], ["rhythm"])

    # ---------------------------------------------------------------- packets
    def fact_packet(self, player_focus: str | None = None, window: tuple[float, float] | None = None,
                    max_facts: int = 40) -> dict:
        facts = self.facts
        if window:
            a, b = window
            facts = [f for f in facts if f.t is None or a <= f.t <= b]
        # order by importance so truncation never drops the score or the big moments
        prio = {"score": 0, "goal": 1, "moment": 2, "shots": 3, "possession": 3, "threat_prevented": 4, "attacks_ended": 4,
                "creation": 5, "interceptions": 5, "pass_quality": 6, "positioning": 6, "rhythm": 7, "physical": 9}
        def rank(f):
            r = min((prio.get(t, 8) for t in f.tags), default=8)
            if "moment" in f.tags and "goal" not in f.tags:
                r = 2 + min(0.9, self.facts.index(f) / 1000)  # keep moment order
            return r
        facts = sorted(facts, key=rank)
        if player_focus:
            focus = [f for f in facts if f.player == player_focus]
            rest = [f for f in facts if f.player != player_focus and ("moment" in f.tags or "score" in f.tags)]
            facts = focus + rest
        facts = facts[:max_facts]
        clubs = self.data.clubs
        return {
            "match": {"home": clubs["home"], "away": clubs["away"], "score": self.score,
                      "clock": mmss(self.t_end), "minute": int(self.t_end // 60)},
            "teams": self.team_stats,
            "facts": [f.to_dict() for f in facts],
            "player_focus": self.fingerprints.get(player_focus) if player_focus else None,
            "rules": "Only state things supported by a fact. Cite fact ids like [f3]. Never invent numbers.",
        }

    # ---------------------------------------------------------------- replay / counterfactual
    def replay(self, possession_id: int, pad: float = 2.0) -> dict:
        p = self.poss_by_id.get(possession_id)
        if not p:
            return {"error": f"no possession {possession_id}"}
        frames = [fr for fr in self.data.frames if p.start_t - pad <= fr.t <= p.end_t + pad]
        return {"possession": {"id": p.id, "team": p.team, "start_t": p.start_t, "end_t": p.end_t,
                               "peak_danger": p.peak_danger, "outcome": p.outcome, "ended_by": p.ended_by,
                               "end_event_id": p.end_event_id, "xg": round(p.xg, 3)},
                "events": p.events,
                "frames": [{"t": fr.t, "ball": fr.ball, "players": fr.players} for fr in frames]}

    def counterfactual(self, event_id: str) -> dict:
        """What would likely have happened if this stop had not happened. Built
        from the match's own possessions, not a scripted animation."""
        e = self.by_id.get(event_id)
        if not e or e["type"] not in DEFENSIVE_ACTIONS:
            return {"error": "not a defensive event"}
        rec = next((r for r in self.threat_prevented if r["event_id"] == event_id), None)
        d = rec["danger_stopped"] if rec else 0.0
        done = [p for p in self.possessions if p.outcome != "ongoing"]
        reached = [p for p in done if p.peak_danger >= d]
        n = len(reached)
        shot_rate = sum(1 for p in reached if p.outcome in ("shot", "goal")) / n if n else 0.0
        goal_rate = sum(1 for p in reached if p.outcome == "goal") / n if n else 0.0
        mean_xg = sum(p.xg for p in reached) / n if n else 0.0
        out = {"event_id": event_id, "type": e["type"], "player": e["player"], "t": e["t"],
               "danger_stopped": d, "sample_possessions": n,
               "shot_rate_from_here": round(shot_rate, 3), "goal_rate_from_here": round(goal_rate, 3),
               "mean_xg_from_here": round(mean_xg, 3),
               "explanation": f"In this match, {n} possessions reached danger {d} or higher. "
                              f"{round(shot_rate*100)}% of them produced a shot and {round(goal_rate*100)}% a goal.",
               "evidence": [p.peak_event_id for p in reached if p.peak_event_id][:20]}
        if e["type"] == "interception":
            ps = self.by_id.get(e["pass_id"])
            if ps:
                out["intended_pass"] = {"from": (ps["x"], ps["y"]), "to": (ps["end_x"], ps["end_y"]),
                                        "receiver": ps["receiver"], "passer": ps["player"],
                                        "danger_before": ps["danger_before"], "danger_intended": ps["danger_intended"]}
                fr = self.data.frame_at(e["t"])
                if fr:
                    out["frame"] = {"t": fr.t, "ball": fr.ball, "players": fr.players}
        return out

    def overlay_items(self, lang_texts: dict[str, dict[str, str]] | None = None) -> list[dict]:
        """Timed, machine-readable overlay items from key moments."""
        items = []
        for m in self.moments:
            nm = self.data.name_of(m["player"]) if m["player"] else None
            d = m["detail"]
            if m["kind"] == "goal":
                text = f"GOAL {nm} (xG {d['xg']})"
            elif m["kind"] == "chance":
                text = f"{nm} shot, xG {d['xg']}, {d['shot_speed']} m/s"
            elif m["kind"] == "key_pass":
                text = f"{nm} key pass to {self.data.name_of(d['receiver'])}: {d['distance']} m at {d['pass_speed']} m/s, difficulty {d['difficulty']}"
            elif m["kind"] == "milestone":
                text = f"{nm} {d['value']} m/s, fastest of the match" if d["milestone"] == "top_speed" else f"{nm} {d['value']} km covered"
            elif m["kind"] == "stop":
                text = f"{nm} {d['action']}: danger {d['danger_stopped']} stopped"
            elif m["kind"] == "momentum_shift":
                text = f"Momentum: {self.data.clubs[m['team']]}"
            else:
                text = f"Chaos: {d['possession_changes']} turnovers in 5 min"
            items.append({"t_start": round(m["t"], 1), "t_end": round(m["t"] + 6.0, 1), "kind": m["kind"],
                          "player": m["player"], "team": m["team"], "rank": m["rank"],
                          "text": {"en": text, **((lang_texts or {}).get(str(m["rank"]), {}))},
                          "evidence": m["evidence"], "x": m.get("x"), "y": m.get("y")})
        items.sort(key=lambda i: i["t_start"])
        return items

    def to_bundle(self) -> dict:
        """Everything the web demo needs, precomputed."""
        return {
            "meta": self.data.meta,
            "clock": self.t_end,
            "score": self.score,
            "teams": self.team_stats,
            "players": {pid: {**{k: v for k, v in s.items() if k not in ("pass_difficulty", "time_to_release", "evidence",
                                                                         "first_action_after_win", "receive_zone")},
                              "pass_difficulty_avg": round(statistics.mean(s["pass_difficulty"]), 1) if s["pass_difficulty"] else 0.0}
                        for pid, s in self.player_stats.items()},
            "fingerprints": self.fingerprints,
            "threat_prevented": self.threat_prevented,
            "momentum": self.momentum,
            "moments": self.moments[:80],
            "facts": [f.to_dict() for f in self.facts],
            "xg_curve": self.xg_curve_table,
            "possessions": [{"id": p.id, "team": p.team, "start_t": p.start_t, "end_t": p.end_t,
                             "peak_danger": round(p.peak_danger, 3), "outcome": p.outcome, "ended_by": p.ended_by,
                             "end_event_id": p.end_event_id, "xg": round(p.xg, 3), "passes": p.passes}
                            for p in self.possessions],
            "overlay": self.overlay_items(),
            "playbooks": {pid: self.playbook(pid) for pid in self.fingerprints},
        }

    def playbook(self, pid: str) -> dict:
        from .playbook import build_playbook
        return build_playbook(self, pid)


def _dist_to_segment(px, py, ax, ay, bx, by):
    abx, aby = bx - ax, by - ay
    ab2 = abx * abx + aby * aby
    if ab2 == 0:
        return math.hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * abx + (py - ay) * aby) / ab2
    tc = max(0.0, min(1.0, t))
    cx, cy = ax + abx * tc, ay + aby * tc
    return math.hypot(px - cx, py - cy), t
