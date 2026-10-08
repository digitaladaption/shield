#!/usr/bin/env python3
"""
Synthetic football match generator (hackathon scaffold).

Produces a football-realistic but entirely invented match, with a planted
"Shield" (a destroyer-type defensive midfielder) on the home team, so that
downstream engines have a known storyline to find.

Outputs (in --out):
  meta.json          teams, rosters, pitch size, tick rate, schema notes
  events.jsonl       one JSON event per line, sorted by time
  frames.csv         t, entity, team, x, y   (players + ball, every tick)
  summary.json       per-player and per-team totals (for sanity checks only)
  ground_truth.json  what was planted. An engine must NOT read this; it is
                     for validating the engine's output afterwards.

Coordinates: metres. Pitch is 105 x 68. Home attacks towards x=105,
away attacks towards x=0. y runs 0..68.

Event types:
  kickoff, possession_change, pass, interception, tackle, block, shot,
  pressure, carry

Every event has: id, t (seconds), minute, period, type, possession_id.
Most have team, player, x, y. Key extras:
  pass          receiver, end_x, end_y, distance, speed, outcome
                (complete | intercepted | misplaced), difficulty (0-100),
                danger_before, danger_intended, progressive, t_start
  interception  pass_id, danger_intended, danger_origin (what the pass was
                heading towards, i.e. the threat that did not happen)
  tackle        outcome (won | lost), danger
  shot          xg, outcome (goal | saved | blocked | off_target), speed
  carry         end_x, end_y, distance, progressive_m

"danger" is a crude 0-1 score: closeness to goal, boosted by attackers
ahead of the ball, reduced by defenders goal-side. Deliberately simple so it
is explainable. Swap it for something cleverer later.

Usage:
  python3 synthetic_match_generator.py --seed 7 --out out
  python3 synthetic_match_generator.py --seed 7 --no-shield --out out_control
  python3 synthetic_match_generator.py --compare 6      # Shield vs control
"""
import argparse
import csv
import json
import math
import os
import random

L, W = 105.0, 68.0
DT = 0.5  # seconds per tick (2 Hz)
HOME, AWAY = "home", "away"
CLUBS = {HOME: "Northbridge FC", AWAY: "Eastvale United"}

# (role, u, v): u = depth in own attacking direction (0 own goal .. 1 opp goal)
F433 = [("GK", .04, .50), ("LB", .25, .12), ("LCB", .20, .37), ("RCB", .20, .63),
        ("RB", .25, .88), ("CDM", .38, .50), ("LCM", .50, .30), ("RCM", .50, .70),
        ("LW", .72, .12), ("ST", .80, .50), ("RW", .72, .88)]
F442 = [("GK", .04, .50), ("LB", .25, .12), ("LCB", .20, .37), ("RCB", .20, .63),
        ("RB", .25, .88), ("LM", .52, .12), ("LCM", .45, .38), ("RCM", .45, .62),
        ("RM", .52, .88), ("LS", .75, .40), ("RS", .75, .60)]
ROLE_W = {"GK": .05, "LB": .55, "LCB": .45, "RCB": .45, "RB": .55, "CDM": .8,
          "LCM": .95, "RCM": .95, "LM": 1., "RM": 1., "LW": 1., "RW": 1.,
          "ST": 1., "LS": 1., "RS": 1.}

FIRST = ["Tomas", "Rafael", "Jonas", "Mateo", "Elias", "Luca", "Niko", "Anders",
         "Piers", "Callum", "Joel", "Marek", "Teo", "Felix", "Ruben", "Kasper",
         "Idris", "Samir", "Oleg", "Bram", "Dylan", "Hugo", "Leif", "Amos",
         "Ewan", "Casper", "Yusuf", "Milo", "Stellan", "Arvid"]
LAST = ["Varga", "Lindqvist", "Brennan", "Okafor", "Moreau", "Tanaka", "Haugen",
        "Delacroix", "Whitlock", "Marsh", "Novak", "Reyes", "Sandoval", "Kerrigan",
        "Falk", "Ashdown", "Petrov", "Calloway", "Bianchi", "Strand", "Osei",
        "Hartmann", "Quill", "Ferreira", "Lund", "Maddox", "Ibarra", "Thorne",
        "Vasko", "Renner"]

SHIELD_NAME = "Dario Okonkwo-Hale"


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def seg_info(px, py, ax, ay, bx, by):
    """Distance from point to segment, projection fraction, closest point."""
    abx, aby = bx - ax, by - ay
    ab2 = abx * abx + aby * aby
    if ab2 == 0:
        return math.hypot(px - ax, py - ay), 0.0, (ax, ay)
    t = ((px - ax) * abx + (py - ay) * aby) / ab2
    tc = clamp(t, 0.0, 1.0)
    cx, cy = ax + abx * tc, ay + aby * tc
    return math.hypot(px - cx, py - cy), t, (cx, cy)


class Player:
    def __init__(self, pid, team, role, name, number, au, av, top):
        self.pid, self.team, self.role = pid, team, role
        self.name, self.number = name, number
        self.au, self.av, self.top = au, av, top
        self.x = self.y = 0.0
        self.ox = self.oy = 0.0       # wander offset (off-ball movement texture)
        self.speed = 0.0
        self.dist = 0.0
        self.sprints = 0
        self.sprinting = False
        self.max_speed = 0.0
        self.int_mult = 1.0
        self.tackle_mult = 1.0
        self.lane_reach = 3.0
        self.tackle_reach = 2.2
        self.last_pressure = -99.0
        self.is_shield = False
        self.hold = 0
        self.mode = "hold"
        self.carry_start = None


class Match:
    def __init__(self, seed, minutes=90, shield_on=True):
        self.rng = random.Random(seed)
        self.seed = seed
        self.minutes = minutes
        self.shield_on = shield_on
        self.n_ticks = int(minutes * 60 / DT)
        self.half_tick = self.n_ticks // 2
        self.events, self.frames = [], []
        self.seq = 0
        self.tick = 0
        self.t = 0.0
        self.score = {HOME: 0, AWAY: 0}
        self.poss_id = 0
        self.poss_team = None
        self.carrier = None
        self.flight = None
        self.ball = (L / 2, W / 2)
        self.poss_ticks = {HOME: 0, AWAY: 0}
        self.players = []
        self.team_players = {HOME: [], AWAY: []}
        self.shield = None
        self._build_squads()

    # ------------------------------------------------------------ setup
    def _build_squads(self):
        used = set()

        def fresh_name():
            while True:
                n = f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"
                if n not in used:
                    used.add(n)
                    return n

        for team, formation in ((HOME, F433), (AWAY, F442)):
            for i, (role, u, v) in enumerate(formation):
                name = SHIELD_NAME if (team == HOME and role == "CDM") else fresh_name()
                top = self.rng.uniform(6.8, 8.6)
                p = Player(f"{team[0].upper()}{i + 1:02d}", team, role, name,
                           i + 1 if role != "CDM" else 6, u, v, top)
                if team == HOME and role == "CDM":
                    p.is_shield = True
                    p.top = 7.3  # reads the game, not a sprinter
                    self.shield = p
                    if self.shield_on:
                        p.int_mult, p.tackle_mult = 1.6, 2.2
                        p.lane_reach, p.tackle_reach = 5.0, 3.0
                self.players.append(p)
                self.team_players[team].append(p)

    # ------------------------------------------------------------ geometry
    @staticmethod
    def other(team):
        return AWAY if team == HOME else HOME

    @staticmethod
    def dir(team):
        return 1 if team == HOME else -1

    def goal_of(self, team):  # the goal this team attacks
        return (L if team == HOME else 0.0, W / 2)

    def own_goal(self, team):
        return (0.0 if team == HOME else L, W / 2)

    def to_world(self, team, u, v):
        if team == HOME:
            return u * L, v * W
        return (1 - u) * L, (1 - v) * W

    def to_team_frame(self, team, x, y):
        if team == HOME:
            return x / L, y / W
        return 1 - x / L, 1 - y / W

    def danger(self, team, bx, by):
        d = self.dir(team)
        gx, gy = self.goal_of(team)
        dist = math.hypot(gx - bx, gy - by)
        base = math.exp(-dist / 20.0)
        att = sum(1 for p in self.team_players[team]
                  if p.role != "GK" and (p.x - bx) * d > 0 and math.hypot(p.x - bx, p.y - by) < 25)
        de = sum(1 for p in self.team_players[self.other(team)]
                 if (p.x - bx) * d > 0 and abs(p.y - by) < 20 and (p.x - bx) * d < 30)
        return round(min(1.0, base * (1 + 0.08 * att) / (1 + 0.18 * de)), 3)

    # ------------------------------------------------------------ events
    def emit(self, etype, t=None, **kw):
        self.seq += 1
        t = self.t if t is None else t
        ev = {"id": f"e{self.seq:05d}", "t": round(t, 1), "minute": int(t // 60),
              "period": 1 if self.tick < self.half_tick else 2,
              "type": etype, "possession_id": self.poss_id}
        for k, v in kw.items():
            ev[k] = round(v, 2) if isinstance(v, float) else v
        self.events.append(ev)
        return ev

    def give_ball(self, p, reason):
        if self.carrier is not None and self.carrier is not p:
            self.finish_carry(self.carrier)
        if p.team != self.poss_team or reason == "kickoff":
            self.poss_id += 1
            self.poss_team = p.team
            self.emit("possession_change", team=p.team, player=p.pid, reason=reason,
                      x=p.x, y=p.y)
        self.carrier, self.flight = p, None
        near = any(math.hypot(o.x - p.x, o.y - p.y) < 2.5
                   for o in self.team_players[self.other(p.team)] if o.role != "GK")
        if near:
            p.hold = self.rng.randint(0, 2)
        elif p.role == "GK":
            p.hold = self.rng.randint(4, 8)
        else:
            p.hold = self.rng.randint(2, 6)
        p.mode = "hold"
        p.carry_start = (p.x, p.y)
        self.ball = (p.x, p.y)

    def finish_carry(self, p):
        if p.carry_start is None:
            return
        sx, sy = p.carry_start
        d = math.hypot(p.x - sx, p.y - sy)
        if d >= 5:
            prog = (p.x - sx) * self.dir(p.team)
            self.emit("carry", team=p.team, player=p.pid, x=sx, y=sy,
                      end_x=p.x, end_y=p.y, distance=d, progressive_m=prog)
        p.carry_start = None

    # ------------------------------------------------------------ movement
    def _standard_target(self, p, in_poss):
        bx, by = self.ball
        bu, bv = self.to_team_frame(p.team, bx, by)
        w = ROLE_W[p.role]
        shift = (bu - 0.5) * 0.55 * w
        u = p.au + shift + (0.04 * w if in_poss else -0.03 * w)
        v = p.av + (bv - p.av) * 0.18
        u = clamp(u, 0.03, 0.92)
        x, y = self.to_world(p.team, u, v)
        x += p.ox
        if in_poss and self.carrier is not p and hasattr(self, "_off"):
            d = self.dir(p.team)
            lim = self._off[p.team] - d * 1.0   # stay a metre onside
            if (x - lim) * d > 0:
                x = lim
        return x, y + p.oy

    def _shield_target(self, p):
        gx, gy = self.own_goal(p.team)
        bx, by = self.ball
        vx, vy = bx - gx, by - gy
        d = math.hypot(vx, vy) or 1.0
        s = clamp(d * 0.6, 17.0, 38.0)
        return gx + vx / d * s, gy + vy / d * s

    def _move(self, p, tx, ty, urgency):
        dx, dy = tx - p.x, ty - p.y
        dist = math.hypot(dx, dy)
        if dist < 0.3:
            step = 0.0
        else:
            desired = min(p.top * urgency, 1.5 + dist * 0.9)
            step = min(desired * DT, dist)
            nx = p.x + dx / dist * step + self.rng.gauss(0, 0.05)
            ny = p.y + dy / dist * step + self.rng.gauss(0, 0.05)
            p.x, p.y = clamp(nx, 0, L), clamp(ny, 0, W)
        p.speed = step / DT
        p.dist += step
        p.max_speed = max(p.max_speed, p.speed)
        if p.speed >= 7.0 and not p.sprinting:
            p.sprints += 1
            p.sprinting = True
        elif p.speed < 6.0:
            p.sprinting = False

    def offside_line(self, team):
        """x beyond which an attacker of `team` would be offside: the second-last opponent."""
        d = self.dir(team)
        xs = sorted((o.x for o in self.team_players[self.other(team)]), key=lambda x: -x * d)
        line = xs[1] if len(xs) > 1 else xs[0]
        bx = self.ball[0]
        return max(line * d, bx * d) * d   # never behind the ball

    def update_players(self):
        poss_team = self.carrier.team if self.carrier else self.flight["team"]
        bx, by = self.ball
        self._off = {HOME: self.offside_line(HOME), AWAY: self.offside_line(AWAY)}
        chasers = set()
        for team in (HOME, AWAY):
            if team == poss_team:
                continue
            field = [p for p in self.team_players[team] if p.role != "GK"]
            field.sort(key=lambda p: math.hypot(p.x - bx, p.y - by))
            for p in field:
                if p.is_shield and self.shield_on and math.hypot(p.x - bx, p.y - by) > 7:
                    continue
                chasers.add(p.pid)
                if len(chasers) % 2 == 0 and len([c for c in chasers if c[0] == team[0].upper()]) >= 2:
                    break
        for p in self.players:
            p.ox = clamp(p.ox + self.rng.gauss(0, 0.4), -6, 6)
            p.oy = clamp(p.oy + self.rng.gauss(0, 0.4), -6, 6)
            in_poss = p.team == poss_team
            if self.carrier is p:
                if p.mode == "dribble":
                    d = self.dir(p.team)
                    self._move(p, p.x + d * 8, p.y + (W / 2 - p.y) * 0.1, 0.55)
                else:
                    self._move(p, p.x, p.y, 0.2)
            elif self.flight and self.flight["receiver"] is p:
                self._move(p, *self.flight["end"], 0.6)
            elif self.flight and self.flight.get("interceptor") is p:
                self._move(p, *self.flight["end"], 0.8)
            elif p.pid in chasers and math.hypot(p.x - bx, p.y - by) < 30:
                self._move(p, bx, by, 0.95)
            elif p.is_shield and self.shield_on and not in_poss:
                sx, sy = self._shield_target(p)
                tx, ty = self._standard_target(p, in_poss)
                disc = 0.9
                self._move(p, tx + (sx - tx) * disc, ty + (sy - ty) * disc, 0.45)
            else:
                tx, ty = self._standard_target(p, in_poss)
                self._move(p, tx, ty, 0.35)

    # ------------------------------------------------------------ actions
    def choose_pass(self, c):
        d = self.dir(c.team)
        opps = [o for o in self.team_players[self.other(c.team)]]
        cands, weights = [], []
        own_gx, _ = self.own_goal(c.team)
        for t in self.team_players[c.team]:
            if t is c:
                continue
            dist = math.hypot(t.x - c.x, t.y - c.y)
            if dist < 4 or dist > (65 if c.role == "GK" else 42):
                continue
            if t.role == "GK" and abs(c.x - own_gx) > 35:
                continue
            progress = (t.x - c.x) * d
            opp_near = min(math.hypot(o.x - t.x, o.y - t.y) for o in opps)
            openness = min(opp_near, 12.0) / 12.0
            w = math.exp(0.035 * progress) * (0.35 + openness) * (1.0 if dist < 28 else 0.55)
            if t.role == "GK":
                w *= 0.3
            cands.append(t)
            weights.append(w)
        if not cands:
            return None
        return self.rng.choices(cands, weights=weights, k=1)[0]

    def do_pass(self, c):
        r = self.choose_pass(c)
        if r is None:
            c.mode, c.hold = "dribble", self.rng.randint(2, 3)
            return
        self.finish_carry(c)
        opps = self.team_players[self.other(c.team)]
        dist = math.hypot(r.x - c.x, r.y - c.y)
        d = self.dir(c.team)
        progress = (r.x - c.x) * d

        # lane: who can cut it out
        lane = []
        for o in opps:
            if o.role == "GK":
                continue
            dseg, tproj, pt = seg_info(o.x, o.y, c.x, c.y, r.x, r.y)
            if tproj < 0.1 or tproj > 0.95 or dseg >= o.lane_reach:
                continue
            p = 0.07 * (1 - dseg / o.lane_reach) * o.int_mult
            if o.is_shield and self.shield_on and progress >= 8:
                p *= 1.8  # reads forward passes through his zone
            lane.append((tproj, o, p, pt))
        lane.sort(key=lambda z: z[0])
        interceptor, ipt = None, None
        for tproj, o, p, pt in lane:
            if self.rng.random() < p:
                interceptor, ipt = o, pt
                break

        press_recv = sum(1 for o in opps if o.role != "GK"
                         and math.hypot(o.x - r.x, o.y - r.y) < 3.5)
        press_car = any(math.hypot(o.x - c.x, o.y - c.y) < 2.5 for o in opps if o.role != "GK")
        pc = clamp(1.0 - 0.0035 * dist - 0.12 * min(press_recv, 2)
                   - (0.06 if press_car else 0), 0.45, 0.97)

        if interceptor is not None:
            outcome, end = "intercepted", ipt
        elif self.rng.random() < pc:
            outcome, end = "complete", (r.x, r.y)
        else:
            outcome = "misplaced"
            end = (clamp(r.x + self.rng.gauss(0, 4), 0, L), clamp(r.y + self.rng.gauss(0, 4), 0, W))

        opp_near = min(math.hypot(o.x - r.x, o.y - r.y) for o in opps)
        lane_p = sum(z[2] for z in lane)
        difficulty = round(100 * min(1.0, 0.45 * min(dist / 45, 1) + 0.3 * (1 - min(opp_near, 12) / 12)
                                     + 0.25 * min(1.0, lane_p * 3)))
        speed = self.rng.uniform(11, 22) if dist < 30 else self.rng.uniform(17, 26)
        seg = math.hypot(end[0] - c.x, end[1] - c.y)
        flight_ticks = max(1, round(seg / speed / DT))
        self.flight = {
            "team": c.team, "passer": c, "receiver": r, "interceptor": interceptor,
            "start": (c.x, c.y), "end": end, "t0": self.tick, "arrive": self.tick + flight_ticks,
            "outcome": outcome,
            "payload": {
                "team": c.team, "player": c.pid, "receiver": r.pid, "x": c.x, "y": c.y,
                "end_x": end[0], "end_y": end[1], "distance": seg, "speed": speed,
                "outcome": outcome, "difficulty": difficulty,
                "danger_before": self.danger(c.team, c.x, c.y),
                "danger_intended": self.danger(c.team, r.x, r.y),
                "progressive": progress >= 10, "t_start": round(self.t, 1),
            },
        }
        self.carrier = None

    def resolve_arrival(self):
        f = self.flight
        pay = f["payload"]
        pev = self.emit("pass", **pay)
        r, o = f["receiver"], f["interceptor"]
        if f["outcome"] == "complete":
            r.x, r.y = f["end"]
            self.give_ball(r, "pass_received")
        elif f["outcome"] == "intercepted":
            o.x, o.y = f["end"]
            self.emit("interception", team=o.team, player=o.pid, x=o.x, y=o.y,
                      pass_id=pev["id"], passer=pay["player"],
                      danger_intended=pay["danger_intended"],
                      danger_origin=pay["danger_before"])
            self.give_ball(o, "interception")
        else:
            ex, ey = f["end"]
            cand = min((q for q in self.team_players[self.other(f["team"])]),
                       key=lambda q: math.hypot(q.x - ex, q.y - ey))
            cand.x, cand.y = ex, ey
            self.give_ball(cand, "misplaced_pass")

    def do_shot(self, c):
        self.finish_carry(c)
        gx, gy = self.goal_of(c.team)
        dist = math.hypot(gx - c.x, gy - c.y)
        opps = [o for o in self.team_players[self.other(c.team)] if o.role != "GK"]
        pressure = sum(1 for o in opps if math.hypot(o.x - c.x, o.y - c.y) < 2.5)
        xg = clamp((0.02 + 0.5 * math.exp(-dist / 9.0)) * (0.6 ** min(pressure, 2)), 0.01, 0.6)
        speed = self.rng.uniform(20, 32)
        gk = next(p for p in self.team_players[self.other(c.team)] if p.role == "GK")
        if self.rng.random() < xg:
            outcome = "goal"
        else:
            z = self.rng.random()
            outcome = "blocked" if z < 0.30 else ("saved" if z < 0.55 else "off_target")
        self.emit("shot", team=c.team, player=c.pid, x=c.x, y=c.y, xg=xg, outcome=outcome,
                  speed=speed, distance=dist, danger=self.danger(c.team, c.x, c.y))
        if outcome == "goal":
            self.score[c.team] += 1
            self.kickoff(self.other(c.team))
        elif outcome == "blocked":
            b = min(opps, key=lambda o: math.hypot(o.x - c.x, o.y - c.y))
            self.emit("block", team=b.team, player=b.pid, x=b.x, y=b.y, shooter=c.pid)
            self.give_ball(b, "block")
        else:
            gk.x, gk.y = self.own_goal(gk.team)[0] + (3 if gk.team == HOME else -3), W / 2
            self.give_ball(gk, "save" if outcome == "saved" else "goal_kick")

    def check_tackles(self, c):
        opps = [o for o in self.team_players[self.other(c.team)] if o.role != "GK"]
        self.rng.shuffle(opps)
        for o in opps:
            if math.hypot(o.x - c.x, o.y - c.y) >= o.tackle_reach:
                continue
            p = (0.02 if c.mode == "dribble" else 0.01) * o.tackle_mult
            if self.rng.random() >= p:
                continue
            won = self.rng.random() < 0.6
            self.emit("tackle", team=o.team, player=o.pid, x=c.x, y=c.y,
                      outcome="won" if won else "lost", victim=c.pid,
                      danger=self.danger(c.team, c.x, c.y))
            if won:
                self.finish_carry(c)
                o.x, o.y = c.x, c.y
                self.give_ball(o, "tackle")
                return True
        return False

    def pressure_events(self, c):
        for o in self.team_players[self.other(c.team)]:
            if o.role == "GK" or o.speed < 4.5 or self.t - o.last_pressure < 12.0:
                continue
            if math.hypot(o.x - c.x, o.y - c.y) < 3.0:
                o.last_pressure = self.t
                self.emit("pressure", team=o.team, player=o.pid, x=o.x, y=o.y, target=c.pid)

    def carrier_logic(self):
        c = self.carrier
        self.pressure_events(c)
        if self.check_tackles(c):
            return
        if c.hold > 0:
            c.hold -= 1
            return
        gx, gy = self.goal_of(c.team)
        dist_goal = math.hypot(gx - c.x, gy - c.y)
        tu, _ = self.to_team_frame(c.team, c.x, c.y)
        if c.role != "GK" and 5.5 <= dist_goal < 27 and tu > 0.68 and \
                self.rng.random() < (0.07 if dist_goal < 20 else 0.015):
            self.do_shot(c)
        elif c.role != "GK" and self.rng.random() < 0.27:
            c.mode, c.hold = "dribble", self.rng.randint(2, 4)
        else:
            self.do_pass(c)

    # ------------------------------------------------------------ flow
    def kickoff(self, team):
        for p in self.players:
            u = min(p.au, 0.47)
            p.x, p.y = self.to_world(p.team, u, p.av)
            p.ox = p.oy = 0.0
        kicker = next(p for p in self.team_players[team] if p.role in ("ST", "LS"))
        kicker.x, kicker.y = L / 2, W / 2
        self.carrier, self.flight = None, None
        self.emit("kickoff", team=team, player=kicker.pid, x=L / 2, y=W / 2)
        self.give_ball(kicker, "kickoff")

    def run(self):
        self.kickoff(HOME)
        for k in range(self.n_ticks):
            self.tick, self.t = k, k * DT
            if k == self.half_tick:
                self.kickoff(AWAY)
            if self.flight and k >= self.flight["arrive"]:
                self.resolve_arrival()
            self.update_players()
            if self.carrier:
                self.ball = (self.carrier.x, self.carrier.y)
            elif self.flight:
                f = self.flight
                fr = (k - f["t0"]) / max(1, f["arrive"] - f["t0"])
                self.ball = (f["start"][0] + (f["end"][0] - f["start"][0]) * fr,
                             f["start"][1] + (f["end"][1] - f["start"][1]) * fr)
            if self.carrier:
                self.carrier_logic()
                if self.carrier:
                    self.ball = (self.carrier.x, self.carrier.y)
            pt = self.carrier.team if self.carrier else (self.flight["team"] if self.flight else None)
            if pt:
                self.poss_ticks[pt] += 1
            self.record_frame()
        self.events.sort(key=lambda e: (e["t"], e["id"]))
        return self

    def record_frame(self):
        t = round(self.t, 1)
        for p in self.players:
            self.frames.append((t, p.pid, p.team, round(p.x, 2), round(p.y, 2)))
        self.frames.append((t, "ball", "", round(self.ball[0], 2), round(self.ball[1], 2)))

    # ------------------------------------------------------------ outputs
    def summary(self):
        stats = {p.pid: {"name": p.name, "team": p.team, "role": p.role,
                         "passes": 0, "passes_complete": 0, "shots": 0, "goals": 0, "xg": 0.0,
                         "tackles_won": 0, "tackles_lost": 0, "interceptions": 0, "blocks": 0,
                         "pressures": 0, "carries": 0, "progressive_carries": 0,
                         "danger_intercepted": 0.0,
                         "distance_km": round(p.dist / 1000, 2), "sprints": p.sprints,
                         "top_speed_ms": round(p.max_speed, 2)} for p in self.players}
        for e in self.events:
            s = stats.get(e.get("player"))
            if not s:
                continue
            t = e["type"]
            if t == "pass":
                s["passes"] += 1
                s["passes_complete"] += e["outcome"] == "complete"
            elif t == "shot":
                s["shots"] += 1
                s["goals"] += e["outcome"] == "goal"
                s["xg"] = round(s["xg"] + e["xg"], 2)
            elif t == "tackle":
                s["tackles_won" if e["outcome"] == "won" else "tackles_lost"] += 1
            elif t == "interception":
                s["interceptions"] += 1
                s["danger_intercepted"] = round(s["danger_intercepted"] + e["danger_intended"], 3)
            elif t == "block":
                s["blocks"] += 1
            elif t == "pressure":
                s["pressures"] += 1
            elif t == "carry":
                s["carries"] += 1
                s["progressive_carries"] += e["progressive_m"] >= 5
        teams = {}
        for team in (HOME, AWAY):
            ps = [v for v in stats.values() if v["team"] == team]
            tot = lambda k: sum(v[k] for v in ps)
            teams[team] = {
                "club": CLUBS[team], "goals": self.score[team],
                "passes": tot("passes"),
                "pass_accuracy": round(tot("passes_complete") / max(1, tot("passes")), 3),
                "shots": tot("shots"), "xg": round(tot("xg"), 2),
                "possession": round(self.poss_ticks[team] / max(1, sum(self.poss_ticks.values())), 3),
                "interceptions": tot("interceptions"), "tackles_won": tot("tackles_won"),
            }
        return {"seed": self.seed, "minutes": self.minutes, "shield_on": self.shield_on,
                "teams": teams, "players": stats}

    def write(self, out):
        os.makedirs(out, exist_ok=True)
        meta = {
            "synthetic": True, "pitch": {"length": L, "width": W}, "tick_seconds": DT,
            "clubs": CLUBS, "formations": {HOME: "4-3-3", AWAY: "4-4-2"},
            "players": [{"id": p.pid, "name": p.name, "team": p.team, "role": p.role,
                         "number": p.number} for p in self.players],
            "notes": "All data is invented. No real match or player data is used.",
        }
        with open(os.path.join(out, "meta.json"), "w") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        with open(os.path.join(out, "events.jsonl"), "w") as f:
            for e in self.events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        with open(os.path.join(out, "frames.csv"), "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t", "entity", "team", "x", "y"])
            w.writerows(self.frames)
        with open(os.path.join(out, "summary.json"), "w") as f:
            json.dump(self.summary(), f, indent=2, ensure_ascii=False)
        with open(os.path.join(out, "ground_truth.json"), "w") as f:
            json.dump({
                "do_not_read_from_engine": True,
                "shield_player": self.shield.pid, "shield_name": self.shield.name,
                "shield_on": self.shield_on,
                "planted": {"interception_multiplier": 1.6, "tackle_multiplier": 2.2,
                            "lane_reach_m": 5.0, "tackle_reach_m": 3.0,
                            "positioning": "screens the line between ball and own goal"},
                "seed": self.seed,
            }, f, indent=2, ensure_ascii=False)


def report(m):
    s = m.summary()
    h, a = s["teams"][HOME], s["teams"][AWAY]
    print(f"{h['club']} {h['goals']} - {a['goals']} {a['club']}   "
          f"(seed {m.seed}, shield {'ON' if m.shield_on else 'OFF'})")
    for k in ("possession", "passes", "pass_accuracy", "shots", "xg", "interceptions", "tackles_won"):
        print(f"  {k:14s} {h[k]:>8}   {a[k]:>8}")
    sh = s["players"][m.shield.pid]
    print(f"  Shield {sh['name']}: {sh['interceptions']} int, {sh['tackles_won']} tkl won, "
          f"{sh['blocks']} blk, {sh['pressures']} press, {sh['distance_km']} km, "
          f"danger intercepted {sh['danger_intercepted']}")
    top = sorted((v for v in s["players"].values() if v["team"] == HOME),
                 key=lambda v: -v["interceptions"])[:3]
    print("  home interceptions rank:", ", ".join(f"{v['name']} ({v['interceptions']})" for v in top))


def compare(n, minutes):
    agg = {True: {"shots": 0, "xg": 0.0, "goals": 0, "int": 0}, False: {"shots": 0, "xg": 0.0, "goals": 0, "int": 0}}
    for seed in range(1, n + 1):
        for on in (True, False):
            m = Match(seed, minutes, shield_on=on).run()
            a = m.summary()["teams"][AWAY]
            sh = m.summary()["players"][m.shield.pid]
            g = agg[on]
            g["shots"] += a["shots"]
            g["xg"] += a["xg"]
            g["goals"] += a["goals"]
            g["int"] += sh["interceptions"]
    print(f"Away team attacking output across {n} seeds (lower = Shield is working)")
    print(f"{'':12s}{'shots':>8}{'xG':>8}{'goals':>8}{'Shield int':>12}")
    for on, label in ((True, "Shield ON"), (False, "Shield OFF")):
        g = agg[on]
        print(f"{label:12s}{g['shots'] / n:8.1f}{g['xg'] / n:8.2f}{g['goals'] / n:8.2f}{g['int'] / n:12.1f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--minutes", type=int, default=90)
    ap.add_argument("--no-shield", action="store_true")
    ap.add_argument("--out", default="out")
    ap.add_argument("--compare", type=int, default=0, help="run N seeds with and without the Shield")
    args = ap.parse_args()
    if args.compare:
        compare(args.compare, args.minutes)
    else:
        m = Match(args.seed, args.minutes, shield_on=not args.no_shield).run()
        m.write(args.out)
        report(m)
        print(f"written to {args.out}/")
