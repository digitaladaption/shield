"""Load a generated match (meta, events, frames) into memory."""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field


@dataclass
class Frame:
    t: float
    players: dict[str, tuple[float, float]]
    ball: tuple[float, float]


@dataclass
class MatchData:
    meta: dict
    events: list[dict]
    frames: list[Frame] = field(default_factory=list)
    path: str = ""

    @property
    def players(self) -> dict[str, dict]:
        return {p["id"]: p for p in self.meta["players"]}

    @property
    def clubs(self) -> dict[str, str]:
        return self.meta["clubs"]

    @property
    def pitch(self) -> tuple[float, float]:
        return self.meta["pitch"]["length"], self.meta["pitch"]["width"]

    def team_of(self, pid: str) -> str:
        return self.players[pid]["team"]

    def name_of(self, pid: str) -> str:
        return self.players[pid]["name"]

    def role_of(self, pid: str) -> str:
        return self.players[pid]["role"]

    def frame_at(self, t: float) -> Frame | None:
        """Nearest frame at or before t (frames are 0.5s apart)."""
        if not self.frames:
            return None
        idx = int(t / self.meta["tick_seconds"])
        idx = max(0, min(idx, len(self.frames) - 1))
        return self.frames[idx]


def load_match(path: str, with_frames: bool = True) -> MatchData:
    with open(os.path.join(path, "meta.json")) as f:
        meta = json.load(f)
    events = []
    with open(os.path.join(path, "events.jsonl")) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    events.sort(key=lambda e: (e["t"], e["id"]))
    data = MatchData(meta=meta, events=events, path=path)
    if with_frames and os.path.exists(os.path.join(path, "frames.csv")):
        data.frames = _load_frames(os.path.join(path, "frames.csv"))
    return data


def _load_frames(path: str) -> list[Frame]:
    frames: list[Frame] = []
    cur_t = None
    cur: Frame | None = None
    with open(path, newline="") as f:
        r = csv.reader(f)
        next(r)
        for t, entity, _team, x, y in r:
            t = float(t)
            if t != cur_t:
                cur = Frame(t=t, players={}, ball=(0.0, 0.0))
                frames.append(cur)
                cur_t = t
            if entity == "ball":
                cur.ball = (float(x), float(y))
            else:
                cur.players[entity] = (float(x), float(y))
    return frames
