"""
Shield multi-agent workflow (Microsoft Agent Framework).

    Narrator  ->  Verifier  --rejected-->  Narrator (with feedback, max 2 retries)
                     |
                  verified
                     v
              Personalizer  ->  Final check  ->  Story

Narrator and Personalizer are LLM agents on Microsoft Foundry (or Azure OpenAI /
OpenAI). The Verifier and Final check are deterministic code (see verifier.py).
The Narrator can also call the Shield MCP server for drill-downs.

If no model endpoint is configured, a local template narrator is used instead so
the pipeline (and the demo) always runs. The output says which path was used.

Run:
  python -m shield.agents.pipeline --match data/match_7 --mode casual --lang en
  python -m shield.agents.pipeline --match data/match_7 --mode player --player H06 --lang es
  python -m shield.agents.pipeline --match data/match_7 --mode kid --player H06 --clock 2700
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field

from agent_framework import Agent, Executor, WorkflowBuilder, WorkflowContext, handler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from shield.agents.verifier import verify, VerifyReport  # noqa: E402
from shield.engine.analysis import Engine, mmss  # noqa: E402
from shield.engine.match import load_match  # noqa: E402

MODES = {
    "analyst": "Analyst mode: dense, numeric, show the reasoning. 5 to 7 sentences. Use the metrics.",
    "casual": "Casual fan mode: 3 sentences, plain words, one 'why you should care' line. Numbers only when they land.",
    "player": "Player focus mode: tell the match through ONE player's eyes, on and off the ball. 4 to 6 sentences. "
              "Explain what he did that the highlights would miss.",
    "kid": "Play-like-your-idol mode for a young player (age 9 to 14) and their coach. 4 to 5 short sentences. "
           "Say what the player does, how he thinks (where he receives, first action after winning the ball, "
           "how fast he releases), his best attribute, one thing to work on, and one drill to try. Encouraging, never gushing.",
    "overlay": "Overlay mode: 1 sentence of at most 12 words for an on-screen caption.",
}

LANG_NAMES = {"en": "English", "es": "Spanish", "de": "German", "fr": "French", "pt": "Portuguese", "ar": "Arabic",
              "ja": "Japanese", "th": "Thai", "zh": "Chinese", "it": "Italian", "nl": "Dutch", "hi": "Hindi"}


# ----------------------------------------------------------------------------- messages
@dataclass
class NarrateRequest:
    packet: dict
    mode: str
    language: str
    player_focus: str | None
    roster: list[str]
    feedback: str | None = None
    attempt: int = 0
    trace: list = field(default_factory=list)

    def step(self, agent: str, what: str, t0: float, **kw):
        self.trace.append({"agent": agent, "step": what, "ms": round((time.perf_counter() - t0) * 1000, 1), **kw})


@dataclass
class Draft:
    text: str
    req: NarrateRequest
    stage: str = "narration"  # narration | personalized


@dataclass
class Verified:
    text_with_cites: str
    clean_text: str
    report: VerifyReport
    req: NarrateRequest
    stage: str


@dataclass
class Rejected:
    draft: Draft
    report: VerifyReport


@dataclass
class Story:
    mode: str
    language: str
    player_focus: str | None
    text: str
    english_text: str
    cited_text: str
    verification: dict
    attempts: int
    backend: str
    facts_used: list[dict] = field(default_factory=list)
    trace: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__


# ----------------------------------------------------------------------------- model client
def make_chat_client():
    """Pick a chat client from the environment. Returns (client, backend_name) or (None, 'local')."""
    try:
        if os.getenv("FOUNDRY_PROJECT_ENDPOINT"):
            from agent_framework.foundry import FoundryChatClient
            return FoundryChatClient(model=os.getenv("FOUNDRY_MODEL", "gpt-4.1-mini")), "microsoft-foundry"
        if os.getenv("AZURE_OPENAI_ENDPOINT"):
            from agent_framework.openai import OpenAIChatClient
            return OpenAIChatClient(model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini"),
                                    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
                                    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
                                    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-04-01-preview")), "azure-openai"
        if os.getenv("OPENAI_API_KEY"):
            from agent_framework.openai import OpenAIChatClient
            return OpenAIChatClient(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini")), "openai"
    except Exception as ex:  # pragma: no cover
        print(f"[shield] model client unavailable ({ex}); using local narrator", file=sys.stderr)
    return None, "local"


def mcp_tool_for_narrator(match_path: str):
    """Give the Narrator the Shield MCP server as a tool (drill-downs on demand)."""
    from agent_framework import MCPStdioTool
    return MCPStdioTool(name="shield_engine", command=sys.executable,
                        args=["-m", "shield.mcp_server.server", "--match", match_path],
                        env={**os.environ, "PYTHONPATH": os.path.join(os.path.dirname(__file__), "..", "..")},
                        allowed_tools=["get_counterfactual", "get_player_fingerprint", "get_threat_prevented",
                                       "compare_players", "get_momentum"])


NARRATOR_INSTRUCTIONS = """You are the Narrator in a football match-intelligence system.
You write ONLY from the fact packet you are given. Every sentence must end with a citation of the
fact ids it uses, like [f3] or [f3, f8]. Never state a number that is not in a cited fact. Never name a
player who is not in a cited fact. Do not use headings or bullet points. Write in English; translation
happens later. If a tool is available you may call it for extra detail, but anything you learn from a tool
that is not in the fact packet must NOT appear in the text."""

PERSONALIZER_INSTRUCTIONS = """You are the Personalizer. You receive a verified English narrative with fact
citations like [f3]. Rewrite it for the requested audience mode and language. Keep EVERY citation exactly
where its sentence is, keep every number exactly as written, keep player names unchanged. Do not add facts.
Return only the rewritten text."""


# ----------------------------------------------------------------------------- local narrator
def local_narrate(req: NarrateRequest) -> str:
    """Template narrator used when no model is configured. Cites facts so the
    verifier treats it exactly like the model's output. Renders in any of the
    template languages (en, es, de, fr); other languages fall back to English."""
    from shield.engine import i18n
    lang = req.language if req.language in i18n.LANGS else "en"
    facts = req.packet["facts"]
    txt = lambda f: (f.get("i18n") or {}).get(lang) or f["text"]
    by_tag = lambda tag: [f for f in facts if tag in f["tags"]]
    he = {"en": "He", "es": "Él", "de": "Er", "fr": "Il"}[lang]
    out = []
    score = by_tag("score")
    if score:
        out.append(f"{txt(score[0])} [{score[0]['id']}].")
    focus = req.player_focus
    pf = [f for f in facts if f.get("player") == focus] if focus else []
    if req.mode in ("player", "kid") and pf:
        fp = req.packet.get("player_focus") or {}
        nm = fp.get("name", "He")
        if req.mode == "kid":
            out = []
        for i, f in enumerate(pf[:4]):
            t = txt(f) if i == 0 else txt(f).replace(nm, he, 1)
            out.append(f"{t} [{f['id']}].")
        short = nm.split()[-1] if req.mode == "kid" else nm
        if req.mode == "kid" and fp:
            hht = fp.get("how_he_thinks", {})
            faw = hht.get("first_action_after_winning_ball", {})
            if faw:
                top = max(faw.items(), key=lambda kv: kv[1])
                out.append(i18n.render("thinks", lang, name=short, dir=i18n.T["dir"][lang].get(top[0], top[0])) + f" [{pf[0]['id']}].")
            strengths = fp.get("strengths", [])
            weak = fp.get("weaknesses", [])
            pretty = lambda m: i18n.metric(m, lang)
            if strengths:
                out.append(i18n.render("best", lang, m=pretty(strengths[0]["metric"])) + f" [{pf[0]['id']}].")
            if weak:
                out.append(i18n.render("work", lang, m=pretty(weak[0]["metric"])) + f" [{pf[0]['id']}].")
            out.append(i18n.render("drill", lang) + f" [{pf[0]['id']}].")
    elif req.mode == "overlay":
        m = by_tag("moment")
        if m:
            return f"{txt(m[0])} [{m[0]['id']}]."
    else:
        n = 7 if req.mode == "analyst" else 3
        moments = by_tag("moment")[: 2 if req.mode == "casual" else 4]
        players = [f for f in facts if "moment" not in f["tags"] and "score" not in f["tags"] and f.get("player")]
        players.sort(key=lambda f: -(float(f["value"]) if isinstance(f["value"], (int, float)) else 0)
                     * (3 if "goals" in f["tags"] else 0.1 if "physical" in f["tags"] else 1))
        if req.mode == "casual":
            goal = [f for f in moments if "goal" in f["tags"]][:1]
            stop = [f for f in moments if "stop" in f["tags"]][:1]
            moments = goal + stop
        for f in moments + players:
            if len(out) >= n:
                break
            out.append(f"{txt(f)} [{f['id']}].")
        if req.mode == "casual":
            tps = [f for f in facts if "threat_prevented" in f["tags"]]
            stop = max(tps, key=lambda f: f["value"]) if tps else None
            if stop:
                nm = stop["text"].split(" prevented")[0]
                out.append(i18n.render("why", lang, name=nm) + f" [{stop['id']}].")
    return " ".join(out) if out else "No facts yet. [f0]"


# ----------------------------------------------------------------------------- executors
class NarratorExecutor(Executor):
    def __init__(self, agent: Agent | None, backend: str):
        super().__init__(id="narrator")
        self.agent, self.backend = agent, backend

    @handler
    async def narrate(self, req: NarrateRequest, ctx: WorkflowContext[Draft]) -> None:
        t0 = time.perf_counter()
        if self.agent is None:
            text = local_narrate(req)
        else:
            prompt = (f"MODE: {MODES[req.mode]}\n"
                      f"PLAYER FOCUS: {req.player_focus or 'none'}\n"
                      f"FACT PACKET (JSON):\n{json.dumps(req.packet, ensure_ascii=False)}\n")
            if req.feedback:
                prompt += f"\nYOUR PREVIOUS DRAFT WAS REJECTED BY THE VERIFIER. Fix these and rewrite:\n{req.feedback}\n"
            resp = await self.agent.run(prompt)
            text = resp.text
        req.step("Narrator", f"draft {req.attempt + 1}" + (" after feedback" if req.feedback else ""), t0,
                 text=text, backend=self.backend, feedback=req.feedback)
        await ctx.send_message(Draft(text=text, req=req, stage="narration"))

    @handler
    async def retry(self, rej: Rejected, ctx: WorkflowContext[Draft]) -> None:
        req = rej.draft.req
        req.attempt += 1
        req.feedback = rej.report.feedback()
        await self.narrate(req, ctx)


class VerifierExecutor(Executor):
    def __init__(self, id: str = "verifier", max_attempts: int = 2):
        super().__init__(id=id)
        self.max_attempts = max_attempts

    @handler
    async def check(self, draft: Draft, ctx: WorkflowContext[Verified | Rejected]) -> None:
        t0 = time.perf_counter()
        rep = verify(draft.text, draft.req.packet["facts"], draft.req.roster)
        verdict = "accepted" if rep.ok else ("accepted with cuts" if (draft.req.attempt >= self.max_attempts or draft.stage == "personalized") else "rejected, sent back")
        draft.req.step("Verifier", f"check {draft.stage}", t0, verdict=verdict, kept=sum(1 for x in rep.sentences if x.ok),
                       rejected=rep.rejected, problems=[{"text": x.text, "problems": x.problems} for x in rep.sentences if not x.ok])
        if rep.ok or draft.req.attempt >= self.max_attempts or draft.stage == "personalized":
            await ctx.send_message(Verified(text_with_cites=draft.text, clean_text=rep.clean_text, report=rep,
                                            req=draft.req, stage=draft.stage))
        else:
            await ctx.send_message(Rejected(draft=draft, report=rep))


class PersonalizerExecutor(Executor):
    def __init__(self, agent: Agent | None):
        super().__init__(id="personalizer")
        self.agent = agent

    @handler
    async def personalize(self, v: Verified, ctx: WorkflowContext[Draft]) -> None:
        req = v.req
        text = v.text_with_cites
        t0 = time.perf_counter()
        ran = False
        if self.agent is not None and (req.language != "en" or req.mode in ("casual", "kid")):
            ran = True
            prompt = (f"AUDIENCE MODE: {MODES[req.mode]}\nLANGUAGE: {LANG_NAMES.get(req.language, req.language)}\n"
                      f"PLAYER FOCUS: {req.player_focus or 'none'}\n\nTEXT:\n{text}")
            resp = await self.agent.run(prompt)
            text = resp.text
        req.step("Personalizer", f"rewrite for {req.mode} in {LANG_NAMES.get(req.language, req.language)}" if ran else "no rewrite needed (English, no model)",
                 t0, text=text if ran else None, ran=ran)
        await ctx.send_message(Draft(text=text, req=req, stage="personalized"))


class FinalCheckExecutor(Executor):
    def __init__(self, english: dict):
        super().__init__(id="final_check")
        self.english = english  # shared store for the verified English version

    @handler
    async def finish(self, draft: Draft, ctx: WorkflowContext[None, Story]) -> None:
        t0 = time.perf_counter()
        rep = verify(draft.text, draft.req.packet["facts"], draft.req.roster)
        draft.req.step("Final check", "verify personalized text", t0, verdict="accepted" if rep.ok else "cuts applied",
                       kept=sum(1 for x in rep.sentences if x.ok), rejected=rep.rejected,
                       problems=[{"text": x.text, "problems": x.problems} for x in rep.sentences if not x.ok])
        eng = self.english.get("text", "")
        # if personalization broke verification, fall back to the verified English
        text = rep.clean_text if rep.ok else (self.english.get("clean", eng) if draft.req.language == "en" else rep.clean_text or eng)
        used_ids = sorted({c for s in rep.sentences if s.ok for c in s.cited})
        facts_used = [f for f in draft.req.packet["facts"] if f["id"] in used_ids]
        await ctx.yield_output(Story(mode=draft.req.mode, language=draft.req.language,
                                     player_focus=draft.req.player_focus, text=text,
                                     english_text=self.english.get("clean", ""), cited_text=draft.text,
                                     verification=rep.to_dict(), attempts=draft.req.attempt + 1,
                                     backend=self.english.get("backend", "local"), facts_used=facts_used,
                                     trace=draft.req.trace))


class EnglishStoreExecutor(Executor):
    """Sits between verifier and personalizer; keeps the verified English copy."""

    def __init__(self, store: dict, backend: str):
        super().__init__(id="english_store")
        self.store, self.backend = store, backend

    @handler
    async def keep(self, v: Verified, ctx: WorkflowContext[Verified]) -> None:
        self.store.update({"text": v.text_with_cites, "clean": v.clean_text, "backend": self.backend,
                           "report": v.report.to_dict()})
        await ctx.send_message(v)


# ----------------------------------------------------------------------------- workflow
def build_workflow(match_path: str, use_mcp_tool: bool = True):
    client, backend = make_chat_client()
    narrator_agent = personalizer_agent = None
    if client is not None:
        tools = [mcp_tool_for_narrator(match_path)] if use_mcp_tool else None
        narrator_agent = Agent(client, NARRATOR_INSTRUCTIONS, name="Narrator", tools=tools)
        personalizer_agent = Agent(client, PERSONALIZER_INSTRUCTIONS, name="Personalizer")
    store: dict = {}
    narrator = NarratorExecutor(narrator_agent, backend)
    verifier = VerifierExecutor("verifier")
    keep = EnglishStoreExecutor(store, backend)
    personalizer = PersonalizerExecutor(personalizer_agent)
    final = FinalCheckExecutor(store)
    wf = (WorkflowBuilder(start_executor=narrator, name="shield-story")
          .add_edge(narrator, verifier)
          .add_edge(verifier, narrator, condition=lambda m: isinstance(m, Rejected))
          .add_edge(verifier, keep, condition=lambda m: isinstance(m, Verified))
          .add_edge(keep, personalizer)
          .add_edge(personalizer, final)
          .build())
    return wf, backend


async def tell_story(match_path: str, mode: str = "casual", language: str = "en", player: str | None = None,
                     clock: float | None = None, workflow=None) -> Story:
    data = load_match(match_path, with_frames=(mode in ("player", "kid")))
    st = Engine(data).snapshot(clock)
    packet = st.fact_packet(player_focus=player)
    roster = [p["name"] for p in data.meta["players"]]
    wf = workflow or build_workflow(match_path)[0]
    req = NarrateRequest(packet=packet, mode=mode, language=language, player_focus=player, roster=roster)
    result = await wf.run(req)
    outputs = result.get_outputs()
    return outputs[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default="data/match_7")
    ap.add_argument("--mode", default="casual", choices=list(MODES))
    ap.add_argument("--lang", default="en")
    ap.add_argument("--player", default=None)
    ap.add_argument("--clock", type=float, default=None, help="seconds, for a live snapshot")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    story = asyncio.run(tell_story(args.match, args.mode, args.lang, args.player, args.clock))
    if args.json:
        print(json.dumps(story.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"[{story.backend} | {story.mode} | {story.language} | attempts {story.attempts} | "
              f"rejected sentences {story.verification['rejected']}]\n")
        print(story.text)


if __name__ == "__main__":
    main()
