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
