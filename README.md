# Shield: Play Like Your Idol

Explainable match intelligence for the Microsoft x Premier League *Inside the Game* hackathon.

Highlights show goals and assists. They miss the defensive midfielder who closes passing lanes and ends attacks before they start. Shield makes that work visible, proves every sentence it says against the data, and turns it into something a young player can train from.

All data is synthetic. No real Premier League data, players or footage are used.

## What it does

```
synthetic events ──> stats engine ──> fact packet ──> Narrator ──> Verifier ──> Personalizer ──> story
(generator)          (deterministic)   (facts + ids)   (Foundry)    (code)       (Foundry)        + overlay JSON
                          │
                          └── MCP server: the agents' only route to the numbers
```

1. **Ingest.** A seeded simulator produces passes, shots, tackles, interceptions, pressure events and player positions twice a second, with a planted "Shield" archetype so the engine can be graded.
2. **Interpret.** A deterministic engine computes everything: danger per moment, possession sequences, **threat prevented**, momentum, control-vs-chaos, player fingerprints and archetypes. No model touches a number.
3. **Explain.** Every fact carries event IDs. The Narrator must cite fact IDs; the Verifier (plain code) rejects any sentence whose numbers or names are not in the cited facts and sends it back for a rewrite.
4. **Render.** Timed, machine-readable overlay items, plus a 2D pitch replay with a freeze-frame of each stop and an empirical "without him" counterfactual built from the match's own possessions.
5. **Personalize.** Fan, Analyst, Player focus and Play-like-your-idol modes, any language, same verified facts.

### Real time

`GET /api/stream?speed=4&narrate=true` replays the synthetic match as a server-sent event feed at any multiple of real time. An incremental tracker processes each event as it arrives and pushes key moments with its own measured latency (well under a millisecond for the engine; the verified caption adds tens of milliseconds through the local narrator, or a model round-trip through Foundry). The demo's **Live feed** button connects to it. Nothing in the live path knows what happens next.

The hackathon rules require synthetic data and no real Premier League feed is used. The point of the live path is that the pipeline is event-driven and fast enough to sit on a real feed; swapping the source is an adapter, not a redesign.

### Threat prevented

For every interception, tackle or block, the player is credited with the danger the attack was heading towards when he stopped it. Goals and assists record what happened; this records what didn't. In the demo match, the Shield ends 20 opposition attacks. In a control run of the same seed with him switched off, the opposition's shots go from 12 to 17 and their xG from 0.9 to 1.74.

### Play like your idol

For coaches and 9 to 14 year olds. Pick a way of playing (The Shield, The Metronome, The Creator…) and the playbook engine (`shield/engine/playbook.py`) writes, in plain words and with evidence for every line:

- **what playing like him looks like**: where he stands, what he does first when he wins the ball, where he asks for the ball, how quickly he moves it on;
- **his game today, the main points**: his key moments from the match, in order, each one clickable onto the pitch replay with a freeze-frame (the pass he cut out, the key pass he played, the shot) and, for interceptions, an empirical "without him" counterfactual;
- **best at, train like him, what he could work on**: a drill for each, chosen from the metric, not generic.

Enter a kid's simple match stats and it finds the archetype whose *shape* they resemble. Style, not level.

### What the brief asks for, where it lives

| Brief | Where |
|---|---|
| Player identification, speed and distance indicators on thresholds | name tags on the pitch above 7.5 m/s; overlay items for a new fastest sprint and for 10 km covered |
| Pass quality: distance, accuracy, difficulty | every pass event carries all three; Analyst mode has a pass quality table; key passes are moments |
| Ball speed and shot speed | on pass and shot events, shown in captions and freeze-frames |
| Narratives, milestones, recaps | Narrator agent from the fact packet; Fan, Analyst and Player focus modes |
| Explainability: control vs chaos, pressure, rhythm | 5-minute momentum windows with a regime label and pressure counts; every fact carries event IDs; the Verifier rejects anything unsupported |
| Data innovation | the generator, with a planted archetype and a control run |
| Multi-language | Personalizer agent; needs a Foundry model endpoint |
| Favourite club, favourite player, player-focused mode | Fan mode has a club selector; Player focus and idol modes follow one player |

## Microsoft technologies

| Where | What |
|---|---|
| Narrator, Personalizer | **Microsoft Agent Framework** `Agent` on a **Microsoft Foundry** model (`FoundryChatClient`), Azure OpenAI also supported |
| Orchestration | Agent Framework `WorkflowBuilder` with a conditional reject-and-rewrite loop |
| Tools | The stats engine is an **MCP server** (`shield/mcp_server`); the Narrator mounts it with `MCPStdioTool` for drill-downs |
| Hosting | FastAPI app in a container for **Azure Container Apps** |
| Build | GitHub Copilot used during development |

With no model endpoint configured, a local template narrator runs through the same workflow and verifier, so the demo always works. The UI says which path produced each story.

## Run it

```bash
pip install -r requirements.txt
python -m shield.generator.generate --seed 7 --out data/match_7
python -m shield.generator.generate --seed 7 --no-shield --out data/match_7_control
python -m shield.engine.build_bundle --match data/match_7 --control data/match_7_control
uvicorn shield.server:app --port 8080        # open http://localhost:8080
```

Stories from the command line:

```bash
python -m shield.agents.pipeline --mode casual
python -m shield.agents.pipeline --mode kid --player H06
python -m shield.agents.pipeline --mode player --player H06 --lang es --clock 2700   # live snapshot at 45:00
```

MCP server on its own (stdio, or `--http` for streamable HTTP on :8000):

```bash
python -m shield.mcp_server.server --match data/match_7
```

Live feed from the command line:

```bash
curl -N "localhost:8080/api/stream?speed=50&narrate=true"
```

Tests (engine, live tracker, verifier, and the workflow loop with a fake model):

```bash
pytest
```

### Connect a Foundry model

Copy `.env.example` to `.env`, set `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL`, and sign in with `az login` (or use a managed identity on Container Apps). The bundle builder will then produce English, Spanish and German stories for the demo.

### Deploy

```bash
az containerapp up --name shield --resource-group shield-rg --source . --ingress external --target-port 8080
```

## Repository

```
shield/generator/generate.py   synthetic match generator (planted Shield, control flag, --compare)
shield/engine/analysis.py      deterministic stats engine: danger, threat prevented, fingerprints, facts
shield/engine/live.py          incremental tracker for the live feed
shield/engine/build_bundle.py  precomputes everything the demo needs
shield/mcp_server/server.py    the engine as MCP tools
shield/agents/verifier.py      deterministic verifier
shield/agents/pipeline.py      Narrator -> Verifier -> Personalizer workflow (Agent Framework)
shield/server.py               FastAPI: demo + JSON API
web/index.html                 the demo (vanilla JS, canvas)
tests/                         engine, verifier and workflow tests
```

## Honest limits

- The generator is a possession simulator, not a physics engine. Numbers are football-realistic at team level (about 84% pass accuracy, 12 to 15 shots a side, 1 to 2 xG) but the Shield's interception count is exaggerated for detectability.
- "Danger" is deliberately simple (distance to goal, attackers ahead of the ball, defenders goal-side) so it can be explained to a child. It is not xT.
- The counterfactual is empirical and honest about its sample size; it is not a prediction model.
- Auto-eventing from video is out of scope. Children's video is a safeguarding question first and a computer-vision question second.

## Data and licence

Synthetic data generated by this repository. MIT licence.
