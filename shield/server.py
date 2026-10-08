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

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shield.agents.pipeline import MODES, build_workflow, tell_story
from shield.engine.analysis import Engine
from shield.engine.match import load_match

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MATCH = os.environ.get("SHIELD_MATCH", os.path.join(ROOT, "data", "match_7"))
WEB = os.path.join(ROOT, "web")

app = FastAPI(title="Shield match intelligence")
_engine = Engine(load_match(MATCH))
_workflow, _backend = build_workflow(MATCH, use_mcp_tool=False)


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


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/", StaticFiles(directory=WEB), name="web")
