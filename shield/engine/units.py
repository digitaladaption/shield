"""
Units the way football says them.

English broadcast uses yards for anything on the pitch (from 25 yards, the
six-yard box, the edge of the box), kilometres an hour for a sprint and
kilometres for distance covered. Spanish, German and French commentary use
metres throughout. Speeds are km/h in every language, which is what the
broadcast graphics show.

The pitch is 105 x 68 m with goals at x=0 and x=105, y=34. The same rules
live in web/index.html (`distP`, `distL`, `kmh`, `shotWhere`).
"""
from __future__ import annotations

L, W = 105.0, 68.0
YARD = 0.9144
BOX_DEPTH, BOX_HALF = 16.5, 20.16     # the 18-yard box
SIX_DEPTH, SIX_HALF = 5.5, 9.16       # the six-yard box


def yards(m: float) -> int:
    return int(round(float(m) / YARD))


def kmh(ms: float) -> float:
    return round(float(ms) * 3.6, 1)


def dist_prose(m: float, lang: str) -> str:
    """'25 yards' / '23 metros' / '23 Meter' / '23 mètres'."""
    if lang == "en":
        y = yards(m)
        return f"{y} yard" if y == 1 else f"{y} yards"
    n = round(float(m))
    return {"es": f"{n} metros", "de": f"{n} Meter", "fr": f"{n} mètres"}.get(lang, f"{n} m")


def dist_label(m: float, lang: str) -> str:
    """Short form for graphics: '25 yds' / '23 m'."""
    return f"{yards(m)} yds" if lang == "en" else f"{round(float(m))} m"


def speed_label(ms: float, lang: str = "en") -> str:
    return f"{kmh(ms)} km/h"


def shot_zone(x: float, y: float) -> str:
    """six | box | edge | out, from where the ball was struck."""
    depth = min(float(x), L - float(x))
    ly = abs(float(y) - W / 2)
    if depth <= SIX_DEPTH + 0.3 and ly <= SIX_HALF + 0.3:
        return "six"
    if depth <= BOX_DEPTH and ly <= BOX_HALF:
        return "box"
    if depth <= BOX_DEPTH + 4.0 and ly <= BOX_HALF + 2.0:
        return "edge"
    return "out"


WHERE = {
    "en": {"six": "from inside the six-yard box", "edge": "from the edge of the box", "n": "from {n} yards"},
    "es": {"six": "desde dentro del área pequeña", "edge": "desde la frontal del área", "n": "desde {n} metros"},
    "de": {"six": "aus dem Fünfmeterraum", "edge": "von der Strafraumkante", "n": "aus {n} Metern"},
    "fr": {"six": "des six mètres", "edge": "depuis l'entrée de la surface", "n": "de {n} mètres"},
}


def shot_where(dist_m: float, x: float | None, y: float | None, lang: str) -> str:
    """How a pundit places a shot: 'from inside the six-yard box', 'from 11 yards',
    'from the edge of the box', 'from 25 yards'. The number, when there is one,
    is the distance to the centre of the goal in the language's unit."""
    w = WHERE.get(lang) or WHERE["en"]
    n = yards(dist_m) if lang == "en" else round(float(dist_m))
    zone = shot_zone(x, y) if x is not None and y is not None else "out"
    if zone == "six":
        return w["six"]
    if zone == "edge":
        return w["edge"]
    return w["n"].format(n=n)
