"""
Coach agent: turns a playbook into a four-week training plan for one young
player, at their level, and a Plan Verifier that refuses any drill the
library does not contain and any session longer than the age allows.

    Coach (Foundry / Agent Framework)  ->  Plan Verifier (code)  --rejected-->  Coach (with feedback)
                                                 |
                                              accepted  ->  Plan

With no model configured, a deterministic planner builds the plan from the
same library, so the demo always has one. The output says which path ran.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field

from agent_framework import Agent, Executor, WorkflowBuilder, WorkflowContext, handler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shield.agents.pipeline import make_chat_client  # noqa: E402
from shield.engine.playbook import METRIC_DRILLS  # noqa: E402

AGE_BANDS = {
    "u9": {"label": "Under 9", "max_session_min": 45, "sessions_per_week": 2, "tone": "games first, no laps, every drill has a ball"},
    "u11": {"label": "Under 11", "max_session_min": 60, "sessions_per_week": 2, "tone": "small-sided games, short blocks, lots of touches"},
    "u13": {"label": "Under 13", "max_session_min": 75, "sessions_per_week": 3, "tone": "add decisions under pressure, start measuring"},
    "u15": {"label": "Under 15", "max_session_min": 90, "sessions_per_week": 3, "tone": "position-specific work, measured targets"},
}

COACH_INSTRUCTIONS = """You are the Coach in a youth football system. You receive a player's playbook (what the
idol does, what the young player should train and work on) and the player's age band. Write a four-week plan.
Rules you cannot break:
- Use ONLY drills from the DRILL LIBRARY you are given, by their exact names. Do not invent drills.
- Every session must fit the age band's maximum minutes and sessions per week.
- Week 1 is easiest; each week adds one progression. Keep the tone encouraging, never gushing.
Return JSON only, this shape:
{"weeks":[{"week":1,"theme":"...","sessions":[{"day":"Tue","minutes":45,"drills":[{"name":"<library name>","minutes":15,"coaching_point":"..."}]}]}],
 "measure":"one thing to count each week, in plain words",
 "note_to_player":"two sentences, to the player, by first name"}"""


# ----------------------------------------------------------------------------- messages
@dataclass
class PlanRequest:
    playbook: dict
    age_band: str
    first_name: str
    library: dict          # drill name -> {"how":..., "for":...}
    feedback: str | None = None
    attempt: int = 0
    trace: list = field(default_factory=list)

    def step(self, agent, what, t0, **kw):
        self.trace.append({"agent": agent, "step": what, "ms": round((time.perf_counter() - t0) * 1000, 1), **kw})


@dataclass
class PlanDraft:
    plan: dict
    raw: str
    req: PlanRequest


@dataclass
class PlanRejected:
    draft: PlanDraft
    problems: list[str]


@dataclass
class Plan:
    plan: dict
    problems: list[str]
    attempts: int
    backend: str
    trace: list = field(default_factory=list)

    def to_dict(self):
        return self.__dict__


# ----------------------------------------------------------------------------- library
def drill_library(playbook: dict) -> dict:
    lib = {}
    for item in playbook.get("train_like_him", []) + playbook.get("work_on", []):
        lib[item["drill"]] = {"how": item["how"], "for": item["friendly"], "metric": item["metric"]}
    # a few general ones so a plan is never thin
    for k in ("passes_p90", "pass_accuracy", "ball_recoveries_p90", "distance_km"):
        name, how = METRIC_DRILLS[k]
        lib.setdefault(name, {"how": how, "for": k.replace("_p90", "").replace("_", " "), "metric": k})
    return lib


# ----------------------------------------------------------------------------- verifier
def verify_plan(plan: dict, req: PlanRequest) -> list[str]:
    problems = []
    band = AGE_BANDS[req.age_band]
    weeks = plan.get("weeks") or []
    if len(weeks) != 4:
        problems.append(f"plan has {len(weeks)} weeks, needs 4")
    for w in weeks:
        sessions = w.get("sessions") or []
        if len(sessions) > band["sessions_per_week"]:
            problems.append(f"week {w.get('week')}: {len(sessions)} sessions, {band['label']} allows {band['sessions_per_week']}")
        for s in sessions:
            total = sum(int(d.get("minutes", 0)) for d in s.get("drills", []))
            if int(s.get("minutes", total)) > band["max_session_min"] or total > band["max_session_min"]:
                problems.append(f"week {w.get('week')} {s.get('day')}: {max(total, int(s.get('minutes', 0)))} min, {band['label']} max is {band['max_session_min']}")
            for d in s.get("drills", []):
                if d.get("name") not in req.library:
                    problems.append(f"week {w.get('week')} {s.get('day')}: drill '{d.get('name')}' is not in the library")
    if not plan.get("measure"):
        problems.append("missing 'measure'")
    if not plan.get("note_to_player"):
        problems.append("missing 'note_to_player'")
    return problems


# ----------------------------------------------------------------------------- local planner
def local_plan(req: PlanRequest) -> dict:
    band = AGE_BANDS[req.age_band]
    pb = req.playbook
    train = [d["drill"] for d in pb.get("train_like_him", []) if d["drill"] in req.library]
    work = [d["drill"] for d in pb.get("work_on", []) if d["drill"] in req.library]
    general = [n for n in req.library if n not in train and n not in work]
    days = ["Tue", "Thu", "Sat"][: band["sessions_per_week"]]
    per = band["max_session_min"]
    themes = ["Learn the shape", "Add a defender", "Add the clock", "Play it in a game"]
    points = ["Get the movement right, slowly.", "Now with one opponent trying to stop you.",
              "Same drill, but you have two seconds to decide.", "Only count it when it happens in the game."]
    weeks = []
    k = 0
    for i in range(4):
        # weeks 1 and 2 copy the idol; weeks 3 and 4 add what he could work on
        pool = (train + general) if i < 2 else (train + work + general)
        pool = [n for j, n in enumerate(pool) if n not in pool[:j]] or list(req.library)
        sessions = []
        for d in days:
            n_drills = 3 if per >= 60 else 2
            # the idol's own drill leads every session; the rest rotate through the pool
            lead = train[k % len(train)] if train else pool[k % len(pool)]
            rest = [n for n in pool if n != lead]
            chosen = [lead] + [rest[(k + j) % len(rest)] for j in range(min(n_drills - 1, len(rest)))]
            k += 1
            each = min(20, per // (len(chosen) + 1))
            drills = [{"name": n, "minutes": each, "coaching_point": points[i]} for n in chosen]
            drills.append({"name": chosen[0], "minutes": min(15, per - each * len(chosen)),
                           "coaching_point": "Small-sided game to finish. A bonus point every time this happens."})
            sessions.append({"day": d, "minutes": sum(x["minutes"] for x in drills), "drills": drills})
        weeks.append({"week": i + 1, "theme": themes[i], "sessions": sessions})
    best = pb.get("best_at", [{}])[0].get("friendly", "the thing he does best")
    return {"weeks": weeks,
            "measure": f"Count {best} in every game this month. Write the number down. Beat it.",
            "note_to_player": f"{req.first_name}, you don't need to be the fastest or score the most to matter. "
                              f"Do what {pb.get('name', 'he')} does and your team will feel it."}


# ----------------------------------------------------------------------------- executors
class CoachExecutor(Executor):
    def __init__(self, agent: Agent | None, backend: str):
        super().__init__(id="coach")
        self.agent, self.backend = agent, backend

    async def _draft(self, req: PlanRequest, ctx):
        t0 = time.perf_counter()
        if self.agent is None:
            plan, raw = local_plan(req), ""
        else:
            prompt = (f"PLAYER FIRST NAME: {req.first_name}\nAGE BAND: {json.dumps(AGE_BANDS[req.age_band])}\n"
                      f"DRILL LIBRARY: {json.dumps(req.library, ensure_ascii=False)}\n"
                      f"PLAYBOOK: {json.dumps({k: req.playbook.get(k) for k in ('name', 'archetype_label', 'intro', 'looks_like', 'best_at', 'train_like_him', 'work_on')}, ensure_ascii=False)}\n")
            if req.feedback:
                prompt += f"\nYOUR PREVIOUS PLAN WAS REJECTED. Fix these and return the full JSON again:\n{req.feedback}\n"
            resp = await self.agent.run(prompt)
            raw = resp.text
            m = re.search(r"\{.*\}", raw, re.S)
            try:
                plan = json.loads(m.group(0)) if m else {}
            except json.JSONDecodeError:
                plan = {}
        req.step("Coach", f"plan {req.attempt + 1}" + (" after feedback" if req.feedback else ""), t0, backend=self.backend,
                 weeks=len(plan.get("weeks") or []))
        await ctx.send_message(PlanDraft(plan=plan, raw=raw, req=req))

    @handler
    async def start(self, req: PlanRequest, ctx: WorkflowContext[PlanDraft]) -> None:
        await self._draft(req, ctx)

    @handler
    async def retry(self, rej: PlanRejected, ctx: WorkflowContext[PlanDraft]) -> None:
        req = rej.draft.req
        req.attempt += 1
        req.feedback = "\n".join(f"- {p}" for p in rej.problems)
        await self._draft(req, ctx)


class PlanVerifierExecutor(Executor):
    def __init__(self, max_attempts: int = 2):
        super().__init__(id="plan_verifier")
        self.max_attempts = max_attempts

    @handler
    async def check(self, draft: PlanDraft, ctx: WorkflowContext[PlanRejected, Plan]) -> None:
        t0 = time.perf_counter()
        problems = verify_plan(draft.plan, draft.req)
        verdict = "accepted" if not problems else ("rejected, sent back" if draft.req.attempt < self.max_attempts else "accepted with problems listed")
        draft.req.step("Plan Verifier", "check drills, minutes, weeks", t0, verdict=verdict, problems=problems)
        if problems and draft.req.attempt < self.max_attempts:
            await ctx.send_message(PlanRejected(draft=draft, problems=problems))
        else:
            await ctx.yield_output(Plan(plan=draft.plan, problems=problems, attempts=draft.req.attempt + 1,
                                        backend=draft.req.trace[0].get("backend", "local"), trace=draft.req.trace))


def build_coach_workflow():
    client, backend = make_chat_client()
    agent = Agent(client, COACH_INSTRUCTIONS, name="Coach") if client is not None else None
    coach = CoachExecutor(agent, backend)
    verifier = PlanVerifierExecutor()
    wf = (WorkflowBuilder(start_executor=coach, name="shield-coach")
          .add_edge(coach, verifier)
          .add_edge(verifier, coach, condition=lambda m: isinstance(m, PlanRejected))
          .build())
    return wf, backend


async def make_plan(playbook: dict, age_band: str = "u11", first_name: str = "you", workflow=None) -> Plan:
    wf = workflow or build_coach_workflow()[0]
    req = PlanRequest(playbook=playbook, age_band=age_band, first_name=first_name, library=drill_library(playbook))
    return (await wf.run(req)).get_outputs()[-1]
