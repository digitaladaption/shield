"""
Shield web app: static demo + JSON API, one process. This is what runs on
Azure Container Apps for the judges.

  uvicorn shield.server:app --host 0.0.0.0 --port 8080

Endpoints
  GET  /                      the demo
  GET  /api/state?clock=1500  engine snapshot (score, team stats, moments)
  GET  /api/player/H06        fingerprint
  GET  /api/counterfactual/e01100
  POST /api/story             {"mode": "kid", "language": "es", "player": "H06", "clock": 2700}
                              runs the Narrator -> Verifier -> Personalizer workflow
  GET  /api/overlay?clock=    timed overlay items
  GET  /healthz
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shield.agents.pipeline import MODES, build_workflow, tell_story
from shield.engine.analysis import Engine
from shield.engine.live import LiveTracker
from shield.engine.match import load_match

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATCH = os.environ.get("SHIELD_MATCH", os.path.join(ROOT, "data", "match_7"))
WEB = os.path.join(ROOT, "web")

app = FastAPI(title="Shield match intelligence")
_engine = Engine(load_match(MATCH))
_workflow, _backend = build_workflow(MATCH, use_mcp_tool=False)
from shield.agents.coach import build_coach_workflow  # noqa: E402
_coach_wf, _ = build_coach_workflow()


class StoryRequest(BaseModel):
    mode: str = "casual"
    language: str = "en"
    player: str | None = None
    clock: float | None = None


@app.get("/healthz")
def healthz():
    return {"ok": True, "backend": _backend, "match": MATCH}


@app.get("/api/state")
def state(clock: float | None = None):
    st = _engine.snapshot(clock)
    return {"clock": st.t_end, "score": st.score, "teams": st.team_stats, "moments": st.moments[:20],
            "momentum": st.momentum}


@app.get("/api/player/{pid}")
def player(pid: str, clock: float | None = None):
    st = _engine.snapshot(clock)
    return st.fingerprints.get(pid) or {"error": "unknown player"}


class PlanRequest(BaseModel):
    player: str
    age_band: str = "u11"
    first_name: str = "you"
    language: str = "en"


@app.post("/api/plan")
async def plan(req: PlanRequest):
    """Coach agent: four-week plan from a player's playbook, checked by the Plan Verifier."""
    from shield.agents.coach import AGE_BANDS, make_plan
    if req.age_band not in AGE_BANDS:
        return {"error": f"age_band must be one of {list(AGE_BANDS)}"}
    pb = _engine.snapshot(None).playbook(req.player)
    if "error" in pb:
        return pb
    p = await make_plan(pb, req.age_band, req.first_name or "you", workflow=_coach_wf, language=req.language)
    return p.to_dict()


class VerifyRequest(BaseModel):
    text: str
    player: str | None = None


@app.post("/api/verify")
def verify_text(req: VerifyRequest):
    """Try to make it lie: run any text through the same Verifier the agents face."""
    from shield.agents.verifier import verify
    st = _engine.snapshot(None)
    pk = st.fact_packet(player_focus=req.player)
    roster = [p["name"] for p in _engine.data.meta["players"]]
    rep = verify(req.text, pk["facts"], roster)
    return {"report": rep.to_dict(), "facts": pk["facts"][:12]}


@app.get("/api/see/{pid}")
def see(pid: str, clock: float):
    return _engine.snapshot(None).see(clock, pid)


@app.get("/api/counterfactual/{event_id}")
def counterfactual(event_id: str):
    return _engine.snapshot(None).counterfactual(event_id)


@app.get("/api/overlay")
def overlay(clock: float | None = None):
    return _engine.snapshot(clock).overlay_items()


@app.post("/api/story")
async def story(req: StoryRequest):
    if req.mode not in MODES:
        return {"error": f"mode must be one of {list(MODES)}"}
    s = await tell_story(MATCH, req.mode, req.language, req.player, req.clock, workflow=_workflow)
    return s.to_dict()


@app.get("/api/stream")
async def stream(speed: float = 4.0, start: float = 0.0, narrate: bool = False):
    """Server-sent events. Replays the synthetic match as a live feed at `speed` x real time.
    Each event is pushed with its wall-clock send time; key moments are pushed as `overlay`
    messages with the engine's own processing latency. With narrate=true, a one-line
    caption also goes through the Narrator -> Verifier workflow and its latency is reported."""
    data = _engine.data
    xg_curve = _engine.snapshot(None).xg_curve_table
    tracker = LiveTracker(data.clubs, data.players, xg_curve)
    events = [e for e in data.events if e["t"] >= start]

    async def gen():
        yield f"event: hello\ndata: {json.dumps({'speed': speed, 'start': start, 'events': len(events)})}\n\n"
        wall0 = time.perf_counter()
        t0 = events[0]["t"] if events else 0.0
        for e in events:
            due = wall0 + (e["t"] - t0) / speed
            delay = due - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            sent_ms = time.time() * 1000
            yield f"event: match\ndata: {json.dumps({'event': e, 'sent_ms': sent_ms})}\n\n"
            item = tracker.ingest(e)
            if item:
                if narrate:
                    n0 = time.perf_counter()
                    try:
                        s = await tell_story(MATCH, "overlay", "en", item["player"], e["t"], workflow=_workflow)
                        item["caption"] = s.text
                        item["caption_backend"] = s.backend
                    except Exception as ex:  # keep the feed alive
                        item["caption_error"] = str(ex)[:120]
                    item["narration_latency_ms"] = round((time.perf_counter() - n0) * 1000, 1)
                item["sent_ms"] = time.time() * 1000
                item["state"] = tracker.state()
                yield f"event: overlay\ndata: {json.dumps(item)}\n\n"
        yield f"event: end\ndata: {json.dumps(tracker.state())}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/", StaticFiles(directory=WEB), name="web")
