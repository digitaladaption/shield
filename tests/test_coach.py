import asyncio, json, os, sys
from agent_framework import Agent, WorkflowBuilder
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shield.agents import coach as co
from shield.engine.analysis import Engine
from shield.engine.match import load_match
from tests.test_pipeline import FakeChatClient

MATCH = os.path.join(os.path.dirname(__file__), "..", "data", "match_7")


def _pb():
    return Engine(load_match(MATCH)).snapshot().playbook("H06")


def test_local_plan_passes_its_own_verifier():
    pb = _pb()
    plan = asyncio.run(co.make_plan(pb, "u9", "Sam"))
    assert plan.problems == []
    assert len(plan.plan["weeks"]) == 4
    for w in plan.plan["weeks"]:
        for s in w["sessions"]:
            assert s["minutes"] <= co.AGE_BANDS["u9"]["max_session_min"]
    assert "Sam" in plan.plan["note_to_player"]


def test_coach_cannot_invent_a_drill():
    pb = _pb()
    lib = co.drill_library(pb)
    real = next(iter(lib))
    bad = json.dumps({"weeks": [{"week": i + 1, "theme": "t", "sessions": [{"day": "Tue", "minutes": 40,
                      "drills": [{"name": "Laps of the pitch", "minutes": 40, "coaching_point": "go"}]}]} for i in range(4)],
                      "measure": "m", "note_to_player": "n"})
    good = json.dumps({"weeks": [{"week": i + 1, "theme": "t", "sessions": [{"day": "Tue", "minutes": 40,
                       "drills": [{"name": real, "minutes": 40, "coaching_point": "go"}]}]} for i in range(4)],
                       "measure": "m", "note_to_player": "n"})
    client = FakeChatClient([bad, good])
    coach = co.CoachExecutor(Agent(client, co.COACH_INSTRUCTIONS, name="Coach"), "fake")
    ver = co.PlanVerifierExecutor()
    wf = (WorkflowBuilder(start_executor=coach).add_edge(coach, ver)
          .add_edge(ver, coach, condition=lambda m: isinstance(m, co.PlanRejected)).build())
    req = co.PlanRequest(playbook=pb, age_band="u11", first_name="Sam", library=lib)
    plan = asyncio.run(wf.run(req)).get_outputs()[-1]
    assert plan.attempts == 2 and plan.problems == []
    assert "Laps of the pitch" in client.prompts[1]          # the feedback named the invented drill
    assert plan.trace[1]["verdict"] == "rejected, sent back"
