"""Workflow tests with a fake model: proves the reject-and-rewrite loop and the
final check work without any cloud endpoint."""
import asyncio
import os
import sys

import pytest
from agent_framework import Agent, BaseChatClient, ChatResponse, Message, WorkflowBuilder

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shield.agents import pipeline as pl  # noqa: E402
from shield.engine.analysis import Engine  # noqa: E402
from shield.engine.match import load_match  # noqa: E402

MATCH = os.path.join(os.path.dirname(__file__), "..", "data", "match_7")


class FakeChatClient(BaseChatClient):
    """Returns scripted replies in order. Used as the Narrator and Personalizer model."""

    def __init__(self, replies):
        super().__init__()
        self.replies = list(replies)
        self.prompts = []

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        self.prompts.append(messages[-1].text if messages else "")
        text = self.replies.pop(0) if self.replies else "Nothing. [f1]"
        return ChatResponse(messages=[Message("assistant", [text])])


def _build(replies):
    client = FakeChatClient(replies)
    store = {}
    narrator = pl.NarratorExecutor(Agent(client, pl.NARRATOR_INSTRUCTIONS, name="Narrator"), "fake")
    verifier = pl.VerifierExecutor("verifier")
    keep = pl.EnglishStoreExecutor(store, "fake")
    personalizer = pl.PersonalizerExecutor(Agent(client, pl.PERSONALIZER_INSTRUCTIONS, name="Personalizer"))
    final = pl.FinalCheckExecutor(store)
    wf = (WorkflowBuilder(start_executor=narrator)
          .add_edge(narrator, verifier)
          .add_edge(verifier, narrator, condition=lambda m: isinstance(m, pl.Rejected))
          .add_edge(verifier, keep, condition=lambda m: isinstance(m, pl.Verified))
          .add_edge(keep, personalizer)
          .add_edge(personalizer, final)
          .build())
    return wf, client


@pytest.fixture(scope="module")
def packet():
    data = load_match(MATCH, with_frames=False)
    st = Engine(data).snapshot()
    return st.fact_packet(), [p["name"] for p in data.meta["players"]]


def test_reject_then_rewrite(packet):
    pk, roster = packet
    f_int = next(f for f in pk["facts"] if "interceptions" in f["tags"] and f["player"] == "H06")
    bad = f"Okonkwo-Hale made 99 interceptions [{f_int['id']}]. Bianchi scored a hat-trick."
    good = f"Okonkwo-Hale made {f_int['value']} interceptions [{f_int['id']}]."
    wf, client = _build([bad, good, good])  # narrator x2, personalizer x1 (casual mode triggers it)
    req = pl.NarrateRequest(packet=pk, mode="casual", language="en", player_focus=None, roster=roster)
    story = asyncio.run(wf.run(req)).get_outputs()[-1]
    assert story.attempts == 2
    assert "99" not in story.text
    assert "hat-trick" not in story.text
    assert story.verification["ok"]
    assert "REJECTED BY THE VERIFIER" in client.prompts[1]
    agents = [t["agent"] for t in story.trace]
    assert agents[:4] == ["Narrator", "Verifier", "Narrator", "Verifier"]
    assert story.trace[1]["verdict"] == "rejected, sent back"
    assert story.trace[1]["problems"] and "99" in story.trace[1]["problems"][0]["text"]


def test_personalizer_cannot_add_facts(packet):
    pk, roster = packet
    f_int = next(f for f in pk["facts"] if "interceptions" in f["tags"] and f["player"] == "H06")
    good = f"Okonkwo-Hale made {f_int['value']} interceptions [{f_int['id']}]."
    tampered = f"Okonkwo-Hale hizo {f_int['value']} intercepciones [{f_int['id']}]. También marcó 2 goles [{f_int['id']}]."
    wf, _ = _build([good, tampered])
    req = pl.NarrateRequest(packet=pk, mode="casual", language="es", player_focus=None, roster=roster)
    story = asyncio.run(wf.run(req)).get_outputs()[-1]
    assert "intercepciones" in story.text
    assert "2 goles" not in story.text           # dropped by the final check
    assert story.verification["rejected"] == 1


def test_local_mode_always_verifies(packet):
    pk, roster = packet
    for mode in pl.MODES:
        req = pl.NarrateRequest(packet=pk, mode=mode, language="en", player_focus="H06", roster=roster)
        text = pl.local_narrate(req)
        rep = pl.verify(text, pk["facts"], roster)
        assert rep.ok, (mode, rep.feedback())


def test_template_languages_verify(packet):
    pk, roster = packet
    for lang in ("es", "de", "fr"):
        for mode in ("casual", "analyst", "kid"):
            req = pl.NarrateRequest(packet=pk, mode=mode, language=lang, player_focus="H06", roster=roster)
            text = pl.local_narrate(req)
            rep = pl.verify(text, pk["facts"], roster)
            assert rep.ok, (lang, mode, rep.feedback())
            assert text != pl.local_narrate(pl.NarrateRequest(packet=pk, mode=mode, language="en", player_focus="H06", roster=roster))


def test_verifier_rejects_slop(packet):
    pk, roster = packet
    f = next(x for x in pk["facts"] if "interceptions" in x["tags"] and x["player"] == "H06")
    slop = f"Okonkwo-Hale delivered a defensive masterclass with {f['value']} interceptions [{f['id']}]! Truly remarkable [{f['id']}]."
    rep = pl.verify(slop, pk["facts"], roster)
    assert not rep.ok and rep.rejected == 2
    joined = " ".join(p for s in rep.sentences for p in s.problems)
    assert "masterclass" in joined and "exclamation" in joined


def test_pundit_voice_says_the_name_once(packet):
    pk, roster = packet
    req = pl.NarrateRequest(packet=pk, mode="kid", language="en", player_focus="H06", roster=roster)
    text = pl.local_narrate(req)
    assert text.count("Dario Okonkwo-Hale") == 1 and text.count("Okonkwo-Hale") >= 3
    assert "!" not in text and "—" not in text
    assert "th minute" in text or "st minute" in text or "nd minute" in text or "rd minute" in text


def test_football_units(packet):
    """English says yards and landmarks, the other languages say metres, speeds are km/h, and the
    Verifier accepts both because the fact states both."""
    from shield.engine import units
    pk, roster = packet
    goal = next(f for f in pk["facts"] if f["key"] == "m_goal")
    assert "yards" in goal["text"] and "m)" in goal["text"] and goal["params"]["yd"] == units.yards(goal["params"]["dist"])
    en = pl.local_narrate(pl.NarrateRequest(packet=pk, mode="analyst", language="en", player_focus=None, roster=roster))
    es = pl.local_narrate(pl.NarrateRequest(packet=pk, mode="analyst", language="es", player_focus=None, roster=roster))
    assert "yards" in en and "metre" not in en and " m/s" not in en
    assert "metros" in es and "yard" not in es
    ok = pl.verify(f"He scored from {goal['params']['yd']} yards [{goal['id']}].", pk["facts"], roster)
    assert ok.ok, ok.feedback()
    bad = pl.verify(f"He scored from 50 yards [{goal['id']}].", pk["facts"], roster)
    assert not bad.ok
    assert units.shot_where(5.0, 101.0, 34.0, "en") == "from inside the six-yard box"
    assert units.shot_where(18.0, 87.5, 34.0, "en") == "from the edge of the box"
    assert units.shot_where(22.9, 82.0, 34.0, "en") == "from 25 yards"
    assert units.shot_where(22.9, 82.0, 34.0, "de") == "aus 23 Metern"
    assert units.kmh(10.0) == 36.0
