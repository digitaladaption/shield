"""
What he sees: one player's view of the pitch at one instant.

Uses the same geometry the simulator uses to decide passes, so the picture
is the truth the match was played with, not an illustration.

  carrier    every lane to a teammate: open / contested / blocked, difficulty,
             danger now -> danger if it arrives; the best option
  defender   lanes he is closing (opposition carrier -> teammate), whether he
             is in the goal wedge, tackle range, who he is marking
  attacker   is the lane to him open, how much space he has, danger where he is

Everything here is mirrored in web/index.html (vision()) so the pitch can
draw it live without a round trip. Keep the two in step.
"""
from __future__ import annotations

import math

from .match import Frame, MatchData
from . import units

LANE_REACH = 3.0       # an opponent this close to the lane can cut it out
CONTEST_REACH = 5.0    # this close and the pass is risky
TACKLE_REACH = 2.2
POST = 3.66            # half goal width


def _seg(px, py, ax, ay, bx, by):
    abx, aby = bx - ax, by - ay
    ab2 = abx * abx + aby * aby
    if ab2 == 0:
        return math.hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * abx + (py - ay) * aby) / ab2
    tc = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + abx * tc), py - (ay + aby * tc)), t


def _in_tri(px, py, ax, ay, bx, by, cx, cy):
    def s(x1, y1, x2, y2, x3, y3):
        return (x1 - x3) * (y2 - y3) - (x2 - x3) * (y1 - y3)
    d1, d2, d3 = s(px, py, ax, ay, bx, by), s(px, py, bx, by, cx, cy), s(px, py, cx, cy, ax, ay)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


class VisionEngine:
    def __init__(self, data: MatchData, possessions: list):
        self.data = data
        self.L, self.W = data.pitch
        self.players = data.players
        self.poss = [(p.start_t, p.end_t, p.team) for p in possessions]

    # ------------------------------------------------------------ helpers
    def team_in_possession(self, t: float) -> str | None:
        for s, e, team in self.poss:
            if s <= t <= e:
                return team
        return None

    def goal_of(self, team):
        return (self.L if team == "home" else 0.0, self.W / 2)

    def own_goal(self, team):
        return (0.0 if team == "home" else self.L, self.W / 2)

    def dirn(self, team):
        return 1 if team == "home" else -1

    def danger(self, team, x, y, fr: Frame) -> float:
        d = self.dirn(team)
        gx, gy = self.goal_of(team)
        dist = math.hypot(gx - x, gy - y)
        base = math.exp(-dist / 20.0)
        att = sum(1 for pid, (px, py) in fr.players.items()
                  if self.players[pid]["team"] == team and self.players[pid]["role"] != "GK"
                  and (px - x) * d > 0 and math.hypot(px - x, py - y) < 25)
        de = sum(1 for pid, (px, py) in fr.players.items()
                 if self.players[pid]["team"] != team and (px - x) * d > 0 and abs(py - y) < 20 and (px - x) * d < 30)
        return round(min(1.0, base * (1 + 0.08 * att) / (1 + 0.18 * de)), 3)

    def carrier(self, fr: Frame, team: str) -> str | None:
        bx, by = fr.ball
        best, bd = None, 99.0
        for pid, (x, y) in fr.players.items():
            if self.players[pid]["team"] != team:
                continue
            dd = math.hypot(x - bx, y - by)
            if dd < bd:
                best, bd = pid, dd
        return best if bd <= 6.0 else None

    def lane(self, fr: Frame, frm: str, to: str) -> dict:
        """One passing lane, judged the way the simulator judges it."""
        team = self.players[frm]["team"]
        ax, ay = fr.players[frm]
        bx, by = fr.players[to]
        dist = math.hypot(bx - ax, by - ay)
        closest, closer, lane_p = None, 99.0, 0.0
        for pid, (x, y) in fr.players.items():
            if self.players[pid]["team"] == team or self.players[pid]["role"] == "GK":
                continue
            dseg, tproj = _seg(x, y, ax, ay, bx, by)
            if 0.1 < tproj < 0.95 and dseg < closer:
                closest, closer = pid, dseg
            if 0.1 < tproj < 0.95 and dseg < LANE_REACH:
                lane_p += 0.07 * (1 - dseg / LANE_REACH)
        opp_near = min((math.hypot(x - bx, y - by) for pid, (x, y) in fr.players.items()
                        if self.players[pid]["team"] != team), default=99.0)
        difficulty = round(100 * min(1.0, 0.45 * min(dist / 45, 1) + 0.3 * (1 - min(opp_near, 12) / 12)
                                     + 0.25 * min(1.0, lane_p * 3)))
        state = "blocked" if closer < LANE_REACH else ("contested" if closer < CONTEST_REACH else "open")
        d0 = self.danger(team, ax, ay, fr)
        d1 = self.danger(team, bx, by, fr)
        return {"to": to, "to_name": self.players[to]["name"], "distance": round(dist, 1), "state": state,
                "closest_opponent": closest, "closest_m": round(closer, 1) if closest else None,
                "receiver_space_m": round(opp_near, 1), "difficulty": difficulty,
                "danger_now": d0, "danger_if_arrives": d1, "gain": round(d1 - d0, 3),
                "progressive": (bx - ax) * self.dirn(team) >= 10,
                "from_xy": (ax, ay), "to_xy": (bx, by)}

    # ------------------------------------------------------------ main
    def see(self, t: float, pid: str) -> dict:
        fr = self.data.frame_at(t)
        if fr is None or pid not in fr.players:
            return {"error": "no frame"}
        p = self.players[pid]
        team = p["team"]
        poss = self.team_in_possession(t)
        x, y = fr.players[pid]
        bx, by = fr.ball
        out = {"t": fr.t, "player": pid, "name": p["name"], "team": team, "role": p["role"],
               "xy": (x, y), "ball": (bx, by), "in_possession": poss == team,
               "dist_to_ball": round(math.hypot(x - bx, y - by), 1)}
        carrier = self.carrier(fr, poss) if poss else None

        if poss == team and carrier == pid:
            lanes = []
            own_gx, _ = self.own_goal(team)
            for q in fr.players:
                if q == pid or self.players[q]["team"] != team:
                    continue
                qx, qy = fr.players[q]
                dist = math.hypot(qx - x, qy - y)
                if dist < 4 or dist > (65 if p["role"] == "GK" else 42):
                    continue
                if self.players[q]["role"] == "GK" and abs(x - own_gx) > 35:
                    continue
                lanes.append(self.lane(fr, pid, q))
            lanes.sort(key=lambda l: -l["gain"])
            open_lanes = [l for l in lanes if l["state"] == "open"]
            best = max(open_lanes, key=lambda l: l["gain"], default=None)
            safe = max(open_lanes, key=lambda l: -l["difficulty"], default=None)
            pressure = [q for q, (qx, qy) in fr.players.items()
                        if self.players[q]["team"] != team and self.players[q]["role"] != "GK"
                        and math.hypot(qx - x, qy - y) < 3.5]
            out.update({"view": "carrier", "lanes": lanes,
                        "options": len(lanes), "open": len(open_lanes),
                        "blocked": sum(1 for l in lanes if l["state"] == "blocked"),
                        "best": best, "safest": safe, "under_pressure_from": pressure,
                        "danger_here": self.danger(team, x, y, fr)})
            if best:
                out["read"] = (f"{p['name']} has {len(lanes)} options and {len(open_lanes)} open. "
                               f"Best: {best['to_name']}, danger {best['danger_now']} to {best['danger_if_arrives']}, "
                               f"difficulty {best['difficulty']}.")
            else:
                out["read"] = f"{p['name']} has {len(lanes)} options and none of them open. Keep it or carry."
            if pressure:
                out["read"] += f" Pressed by {', '.join(self.players[q]['name'].split()[-1] for q in pressure)}."
            return out

        if poss and poss != team:
            # defender: which opposition lanes is he sitting in, is he in the goal wedge
            closing = []
            if carrier:
                cx, cy = fr.players[carrier]
                for q, (qx, qy) in fr.players.items():
                    if q == carrier or self.players[q]["team"] != poss:
                        continue
                    if math.hypot(qx - cx, qy - cy) < 4:
                        continue
                    dseg, tproj = _seg(x, y, cx, cy, qx, qy)
                    if 0.1 < tproj < 0.95 and dseg < CONTEST_REACH:
                        closing.append({"to": q, "to_name": self.players[q]["name"], "from_xy": (cx, cy), "to_xy": (qx, qy),
                                        "my_distance_to_lane": round(dseg, 1),
                                        "state": "closed" if dseg < LANE_REACH else "contested",
                                        "danger_if_arrives": self.danger(poss, qx, qy, fr)})
            gx, gy = self.own_goal(team)
            in_wedge = _in_tri(x, y, bx, by, gx, gy - POST, gx, gy + POST)
            dline, _ = _seg(x, y, bx, by, gx, gy)
            marking = min(((math.hypot(qx - x, qy - y), q) for q, (qx, qy) in fr.players.items()
                           if self.players[q]["team"] == poss and self.players[q]["role"] != "GK"), default=(None, None))
            closing.sort(key=lambda c: -c["danger_if_arrives"])
            out.update({"view": "defender", "carrier": carrier, "closing": closing,
                        "in_goal_wedge": in_wedge, "distance_to_ball_goal_line": round(dline, 1),
                        "tackle_range": TACKLE_REACH, "can_tackle": math.hypot(x - bx, y - by) <= TACKLE_REACH,
                        "marking": marking[1], "marking_m": round(marking[0], 1) if marking[0] is not None else None,
                        "wedge": {"ball": (bx, by), "posts": [(gx, gy - POST), (gx, gy + POST)]}})
            closed = [c for c in closing if c["state"] == "closed"]
            bits = []
            if closed:
                bits.append(f"closing {len(closed)} lane{'s' if len(closed) != 1 else ''}" +
                            (f" (most dangerous: to {closed[0]['to_name'].split()[-1]}, danger {closed[0]['danger_if_arrives']})" if closed else ""))
            bits.append("between the ball and his goal" if in_wedge else f"{units.dist_prose(dline, 'en')} off the ball-to-goal line")
            if out["can_tackle"]:
                bits.append("in tackling range")
            elif out["dist_to_ball"] < 8:
                bits.append(f"{units.dist_prose(out['dist_to_ball'], 'en')} from the ball")
            out["read"] = f"{p['name']}: " + ", ".join(bits) + "."
            return out

        # attacker without the ball (or nobody has it)
        info = {"view": "attacker"}
        if carrier and carrier != pid and self.players[carrier]["team"] == team:
            ln = self.lane(fr, carrier, pid)
            info.update({"lane_from_carrier": ln, "carrier": carrier})
        space = min((math.hypot(qx - x, qy - y) for q, (qx, qy) in fr.players.items()
                     if self.players[q]["team"] != team), default=99.0)
        info.update({"space_m": round(space, 1), "danger_here": self.danger(team, x, y, fr)})
        out.update(info)
        if "lane_from_carrier" in info:
            ln = info["lane_from_carrier"]
            out["read"] = (f"{p['name']} is {ln['state']} for a pass from {self.players[carrier]['name'].split()[-1]}, "
                           f"{units.dist_prose(space, 'en')} of space, danger here {info['danger_here']}.")
        else:
            out["read"] = f"{p['name']} has {units.dist_prose(space, 'en')} of space, danger here {info['danger_here']}."
        return out
