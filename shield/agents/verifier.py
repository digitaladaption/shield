"""
Deterministic verifier.

Every sentence the Narrator writes must cite at least one fact id like [f12],
and every number and every player name in that sentence must appear in the
cited facts. Anything else is rejected and sent back for a rewrite. This is
code, not a model, so it cannot be talked round.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

CITE_RE = re.compile(r"\[(f\d+)(?:\s*,\s*(f\d+))*\]")
CITE_ALL_RE = re.compile(r"f\d+")
NUM_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*%?")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZÀ-ÿ¡¿\"'(\[])")


@dataclass
class SentenceCheck:
    text: str
    cited: list[str]
    ok: bool
    problems: list[str] = field(default_factory=list)


@dataclass
class VerifyReport:
    ok: bool
    sentences: list[SentenceCheck]
    clean_text: str          # citations stripped, rejected sentences removed
    rejected: int

    def feedback(self) -> str:
        lines = []
        for s in self.sentences:
            if not s.ok:
                lines.append(f"- \"{s.text}\": " + "; ".join(s.problems))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "rejected": self.rejected, "clean_text": self.clean_text,
                "sentences": [{"text": s.text, "cited": s.cited, "ok": s.ok, "problems": s.problems}
                              for s in self.sentences]}


def _numbers_in(text: str) -> list[float]:
    out = []
    for m in NUM_RE.finditer(text):
        raw = m.group(1).replace(",", ".")
        try:
            out.append(float(raw))
        except ValueError:
            pass
    return out


def _fact_numbers(fact: dict) -> set[float]:
    nums = set(_numbers_in(str(fact.get("text", ""))))
    v = fact.get("value")
    if isinstance(v, (int, float)):
        nums.add(float(v))
        nums.add(round(float(v) * 100, 0))   # 0.84 -> 84 (%)
        nums.add(round(float(v), 1))
        nums.add(round(float(v), 0))
    elif isinstance(v, str):
        nums.update(_numbers_in(v))
    # also allow rounded forms of every number in the text
    for n in list(nums):
        nums.add(round(n, 1))
        nums.add(round(n, 0))
        nums.add(round(n * 100, 0))
    return nums


def _number_supported(n: float, pool: set[float]) -> bool:
    for p in pool:
        if abs(p - n) <= 0.011 or (p and abs(p - n) / abs(p) <= 0.02):
            return True
    return False


def split_sentences(text: str) -> list[str]:
    text = text.replace("\n", " ").strip()
    parts = [p.strip() for p in SENT_SPLIT.split(text) if p.strip()]
    return parts


def verify(narrative: str, facts: list[dict], roster_names: list[str] | None = None,
           allow_uncited_minutes: bool = True, lang: str = "en", style: bool = True) -> VerifyReport:
    by_id = {f["id"]: f for f in facts}
    roster_names = roster_names or []
    checks: list[SentenceCheck] = []
    kept: list[str] = []
    for sent in split_sentences(narrative):
        cited = CITE_ALL_RE.findall(" ".join(CITE_RE.findall(sent) and [m.group(0) for m in CITE_RE.finditer(sent)]))
        cited = [c for c in cited if c in by_id]
        problems = []
        if not cited:
            problems.append("no valid fact citation")
        body = CITE_RE.sub("", sent)
        pool: set[float] = set()
        names_pool = ""
        for c in cited:
            pool |= _fact_numbers(by_id[c])
            names_pool += " " + str(by_id[c].get("text", ""))
        # numbers
        for n in _numbers_in(body):
            if allow_uncited_minutes and n <= 95 and (
                    re.search(rf"\b{int(n)}(?:st|nd|rd|th|e|er|\.)?\s*(?:minute|min|Minute|minuto|')", body)
                    or re.search(rf"(?:minute|minuto|Minute|min)\s*{int(n)}\b", body)):
                continue
            if not _number_supported(n, pool):
                problems.append(f"number {n:g} not in cited facts")
        # names: any roster surname mentioned must be in a cited fact
        for full in roster_names:
            surname = full.split()[-1]
            if re.search(rf"\b{re.escape(surname)}\b", body) and surname not in names_pool:
                problems.append(f"player {surname} not in cited facts")
        if style:
            from shield.agents.voice import style_problems
            problems += style_problems(body, lang)
        ok = not problems
        checks.append(SentenceCheck(text=sent, cited=cited, ok=ok, problems=problems))
        if ok:
            kept.append(body.strip())
    clean = re.sub(r"\s+([.,!?;:])", r"\1", re.sub(r"\s{2,}", " ", " ".join(kept))).strip()
    rejected = sum(1 for c in checks if not c.ok)
    return VerifyReport(ok=rejected == 0 and bool(checks), sentences=checks, clean_text=clean, rejected=rejected)
