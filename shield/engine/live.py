"""
Incremental live tracker: consume one event at a time, keep running state,
and flag key moments the instant they happen. This is the real-time path;
the batch Engine is the same logic over the whole match.
"""
from __future__ import annotations

import time
from collections import defaultdict


class LiveTracker:
    def __init__(self, clubs: dict, players: dict, xg_curve: list[tuple] | None = None):
        self.clubs, self.players = clubs, players
        self.score = {"home": 0, "away": 0}
        self.shots = {"home": 0, "away": 0}
        self.xg = {"home": 0.0, "away": 0.0}
        self.per_player = defaultdict(lambda: {"interceptions": 0, "tackles_won": 0, "blocks": 0, "danger_stopped": 0.0,
                                               "xg_prevented": 0.0, "attacks_ended": 0, "passes": 0, "shots": 0, "goals": 0})
        self.curve = xg_curve or [(0.0, 0.1, 0.01, 0), (0.1, 0.2, 0.02, 0), (0.2, 0.35, 0.03, 0),
                                  (0.35, 0.5, 0.04, 0), (0.5, 0.7, 0.06, 0), (0.7, 1.01, 0.1, 0)]
        self.n = 0
        self.clock = 0.0
        self.moments: list[dict] = []
        self._last_shot: dict | None = None
        self._cur_poss = None
        self._cur_poss_team = None

    def _xg_for(self, d: float) -> float:
        for lo, hi, v, _ in self.curve:
            if lo <= d < hi:
                return v
        return self.curve[-1][2]

    def ingest(self, e: dict) -> dict | None:
        """Returns an overlay item if this event is a key moment, else None."""
        t0 = time.perf_counter()
        self.n += 1
        self.clock = e["t"]
        kind = None
        detail = {}
        pid = e.get("player")
        nm = self.players.get(pid, {}).get("name", pid)
        if e["type"] == "possession_change":
            if self._cur_poss is not None and e["possession_id"] != self._cur_poss and e.get("reason") in ("interception", "tackle", "block"):
                self.per_player[pid]["attacks_ended"] += 1
            self._cur_poss, self._cur_poss_team = e["possession_id"], e["team"]
        elif e["type"] == "pass":
            self.per_player[pid]["passes"] += 1
            if e["outcome"] == "complete":
                gain = e["danger_intended"] - e["danger_before"]
                if gain >= 0.3 or (e["difficulty"] >= 65 and e["progressive"] and gain >= 0.15):
                    kind, detail = "key_pass", {"danger_gain": round(gain, 3), "receiver": e["receiver"], "distance": e["distance"],
                                                "pass_speed": e["speed"], "difficulty": e["difficulty"],
                                                "end_x": e["end_x"], "end_y": e["end_y"]}
        elif e["type"] == "shot":
            self.shots[e["team"]] += 1
            self.xg[e["team"]] += e["xg"]
            self.per_player[pid]["shots"] += 1
            self._last_shot = e
            if e["outcome"] == "goal":
                self.score[e["team"]] += 1
                self.per_player[pid]["goals"] += 1
                kind, detail = "goal", {"xg": e["xg"], "distance": e["distance"]}
            elif e["xg"] >= 0.12:
                kind, detail = "chance", {"xg": e["xg"], "outcome": e["outcome"]}
        elif e["type"] in ("interception", "tackle", "block"):
            if e["type"] == "tackle" and e["outcome"] != "won":
                pass
            else:
                if e["type"] == "interception":
                    d = e["danger_intended"]
                    self.per_player[pid]["interceptions"] += 1
                elif e["type"] == "tackle":
                    d = e["danger"]
                    self.per_player[pid]["tackles_won"] += 1
                else:
                    d = self._last_shot["danger"] if self._last_shot else 0.3
                    self.per_player[pid]["blocks"] += 1
                xg = self._last_shot["xg"] if (e["type"] == "block" and self._last_shot) else self._xg_for(d)
                self.per_player[pid]["danger_stopped"] += d
                self.per_player[pid]["xg_prevented"] += xg
                if d >= 0.2:
                    kind, detail = "stop", {"action": e["type"], "danger_stopped": round(d, 3), "xg_prevented": round(xg, 3)}
        if kind is None:
            return None
        if kind == "goal":
            text = f"GOAL {nm} (xG {detail['xg']})"
        elif kind == "key_pass":
            text = f"{nm} key pass: {detail['distance']} m at {detail['pass_speed']} m/s, difficulty {detail['difficulty']}"
        elif kind == "chance":
            text = f"{nm} shot, xG {detail['xg']}"
        else:
            text = f"{nm} {detail['action']}: danger {detail['danger_stopped']} stopped"
        item = {"t_start": e["t"], "t_end": e["t"] + 6.0, "kind": kind, "player": pid, "team": e.get("team"),
                "text": {"en": text}, "evidence": [e["id"]] + ([e["pass_id"]] if e["type"] == "interception" else []),
                "detail": detail, "x": e.get("x"), "y": e.get("y"),
                "engine_latency_ms": round((time.perf_counter() - t0) * 1000, 3)}
        self.moments.append(item)
        return item

    def state(self) -> dict:
        top = sorted(self.per_player.items(), key=lambda kv: -kv[1]["danger_stopped"])[:3]
        return {"clock": self.clock, "events_seen": self.n, "score": self.score, "shots": self.shots,
                "xg": {k: round(v, 2) for k, v in self.xg.items()},
                "top_stoppers": [{"player": k, "name": self.players.get(k, {}).get("name", k), **v} for k, v in top]}
