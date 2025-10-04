## Overview

Fantasy Football helper app focused on settings-driven decisions with a single Inbox surface. Built with FastAPI, httpx, pydantic, sqlite, and Jinja templates.

- Inbox for messages: lineup checks, waivers, trades, weekly brief
- Yahoo ingest and LeagueSettings parsing
- Scoring and lineup optimizer honoring LeagueSettings
- Waiver ranker with FAAB guidance
- Trade Advisor v1 (needs-based, bye relief, playoff weighting)

Server-rendered UI at `/` shows notifications with filters and mark-as-read.

## Quickstart

1) Create virtualenv and install deps
```bash
make venv
```

2) Run the app (http://127.0.0.1:8000)
```bash
make run
```

3) Tests and lint
```bash
make test
make lint
```

## Environment

Copy the example and fill in Yahoo OAuth secrets and your league key.
```bash
cp .env.example .env
# set YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET, YAHOO_REDIRECT_URI, LEAGUE_KEY, TEAM_KEY
# LEAGUE_KEY accepts either nfl.l.<id> or just the numeric <id>
# TEAM_KEY identifies your team for writes, e.g., nfl.l.<id>.t.<team_id>
```

Optional:
- `DB_PATH` to override the sqlite file location (defaults to `./app.db`).
- `OPENAI_API_KEY` for AI-powered recommendations (get from https://platform.openai.com/api-keys)
- `AI_AUTOPILOT=false` set to `true` to auto-execute high-confidence recommendations

**Note on Projections**: The app includes a projections module (`app/projections.py`) that you can plug your own source into. Free projection APIs are hard to find - most require paid subscriptions. The AI works great without projections by using real-time news, Yahoo player stats, and matchup data instead.

## Ngrok for Yahoo OAuth

Yahoo requires an HTTPS, publicly reachable Redirect URI. The app runs locally on `http://localhost:8000`, which Yahoo won’t accept. Ngrok exposes your local port with a public HTTPS URL.

### Why we need ngrok

Yahoo OAuth redirect must be HTTPS and public. Ngrok provides that, tunneling to your local FastAPI server.

### How we set it up

1) Start ngrok in a separate terminal
```bash
ngrok http 8000
```
You’ll see something like:
```
Forwarding  https://e10adb7406ea.ngrok-free.app -> http://localhost:8000
```

2) Update Redirect URI everywhere
- In Yahoo Developer portal, set:
```
https://<your-subdomain>.ngrok-free.app/oauth/callback
```
- In your `.env`:
```
YAHOO_REDIRECT_URI=https://<your-subdomain>.ngrok-free.app/oauth/callback
```
Restart the app after changing `.env`.

3) Use the ngrok URL in browser
- Click “Connect Yahoo” in the UI to authorize the app (saves tokens). If misconfigured, the Inbox will show an error.

### Quality-of-life: reserved domains

If you don’t want the URL to change each time:
1) Log into ngrok dashboard and reserve a subdomain (e.g., `zachfantasy.ngrok.app`).
2) Create/update `~/.config/ngrok/ngrok.yml`:
```yaml
version: "3"
authtoken: <your-ngrok-authtoken>
tunnels:
  fantasy:
    addr: 8000
    proto: http
    domain: zachfantasy.ngrok.app
```
3) Start with:
```bash
ngrok start fantasy
```
Your Redirect URI remains stable:
```
https://zachfantasy.ngrok.app/oauth/callback
```

### Dev loop summary
- Run FastAPI app locally on port 8000
- Run `ngrok http 8000` (or `ngrok start fantasy` if reserved)
- Copy the HTTPS forwarding URL to Yahoo Redirect URI and `.env`
- Use that ngrok URL for OAuth flows (via the scripts below)

## OAuth and Yahoo API

1) Generate the authorization URL and sign in
```bash
python - <<'PY'
from app.yahoo_client import YahooClient
print("Open and sign in:", YahooClient().get_authorization_url(state="local"))
PY
```

2) Exchange the code for tokens (saved to `~/.fantasy-bot/tokens.json`)
```bash
python - <<'PY'
from app.yahoo_client import YahooClient
YahooClient().exchange_code_for_tokens("PASTE_CODE")
print("Tokens saved.")
PY
```

3) Fetch your LeagueSettings and post to Inbox (optional script)
```bash
python - <<'PY'
from app.yahoo_client import YahooClient
from app.models import LeagueSettings
from app.inbox import notify

# Uses LEAGUE_KEY from .env if you don't pass a key into the UI actions
LEAGUE_KEY="nfl.l.XXXXX"  # optional override
c = YahooClient()
data = c.get(f"league/{LEAGUE_KEY}", params={"format":"json"}).json()
settings = LeagueSettings.from_yahoo(data)
notify("info", "Detected League Settings", "Loaded from Yahoo.", settings.model_dump())
print(settings.model_dump_json(indent=2))
PY
```

## Common Workflows

### Cache a league snapshot (or use the UI “Run Ingest Now”)
```bash
python - <<'PY'
from app.yahoo_client import YahooClient
from app.ingest import fetch_league_bundle
# LEAGUE_KEY comes from .env if not specified here
LEAGUE_KEY="nfl.l.XXXXX"
bundle = fetch_league_bundle(YahooClient(), LEAGUE_KEY, cache_dir=".cache")
print("cached:", list(bundle.keys()))
PY
```

### Tuesday GM Brief
```bash
python -m app.schedule gm_brief
```
Posts a deterministic GM Brief to Inbox.

### Waiver recommendations (demo)
```bash
python - <<'PY'
from app.models import LeagueSettings
from app.waivers import recommend_waivers

s = LeagueSettings.from_yahoo({"settings":{"roster_positions":[
 {"position":"QB","count":1},{"position":"RB","count":2},{"position":"WR","count":2},
 {"position":"TE","count":1},{"position":"W/R/T","count":1},{"position":"BN","count":5}],
 "scoring":{"ppr":"full"}}})
current = {"RB":2,"WR":2,"QB":1,"TE":1}
free_agents = [
  {"id":"p_rb1","name":"Upside RB","position":"RB","proj_base":11,"trend_last2":2,"schedule_next4":1},
  {"id":"p_wr1","name":"Volume WR","position":"WR","proj_base":12,"trend_last2":0,"schedule_next4":0},
  {"id":"p_te1","name":"Athletic TE","position":"TE","proj_base":8,"trend_last2":1,"schedule_next4":2},
]
recs, msg_id = recommend_waivers(settings=s, current_starters_count=current, free_agents=free_agents, faab_remaining=50, waiver_type="faab", top_n=3)
print("Inbox message id:", msg_id)
for r in recs:
    print(r)
PY
```

### Lineup optimizer (demo)
```bash
python - <<'PY'
from app.models import LeagueSettings
from app.lineup import optimize_lineup
from app.inbox import notify

s=LeagueSettings.from_yahoo({"settings":{"roster_positions":[
 {"position":"QB","count":1},{"position":"RB","count":2},{"position":"WR","count":2},
 {"position":"TE","count":1},{"position":"W/R/T","count":1},{"position":"BN","count":5}],
 "scoring":{"ppr":"full"}}})
candidates=[
 {"id":"rbA","position":"RB","projected":13.5,"injury":"","is_bye":False,"tier":"tier-1"},
 {"id":"rbB","position":"RB","projected":12.1,"injury":"Q","is_bye":False},
 {"id":"wrA","position":"WR","projected":14.2,"injury":"","is_bye":False},
 {"id":"teA","position":"TE","projected":8.4,"injury":"","is_bye":False},
]
current={"RB":["rbA","rbB"],"WR":["wrA"],"TE":["teA"]}
swaps=optimize_lineup(settings=s, candidates=candidates, current_starters=current)
lines=[f"- {sw.in_player_id} over {sw.out_player_id}: {sw.reason}" for sw in swaps]
notify("lineup","Lineup suggestions","\n".join(lines),{"swaps":[sw.__dict__ for sw in swaps]})
print("\n".join(lines))
PY
```

### Trade Advisor v1 (demo)
## Yahoo writes (approvals)

Approving a waiver recommendation will attempt a Yahoo write if both env vars are set:

- `LEAGUE_KEY` (e.g., nfl.l.10530)
- `TEAM_KEY` (e.g., nfl.l.10530.t.7)

The app submits a minimal XML payload via `POST /fantasy/v2/league/{LEAGUE_KEY}/transactions` and logs the request/response to `transactions_raw`. Writes are only attempted on Approve; Deny cancels the item.

```bash
python - <<'PY'
from app.models import LeagueSettings
from app.trades import Player, TeamState, propose_and_notify

s=LeagueSettings.from_yahoo({"settings":{"roster_positions":[
 {"position":"QB","count":1},{"position":"RB","count":2},{"position":"WR","count":2},
 {"position":"TE","count":1},{"position":"W/R/T","count":1},{"position":"BN","count":5}],
 "scoring":{"ppr":"full"}}})

a = TeamState(
  team_id="A", starters_by_slot={"RB":2,"WR":2,"TE":1}, bench_redundancy={"RB":0,"WR":1,"TE":0},
  bye_exposure=1, injuries=0, schedule_difficulty=1.0, manager_profile={},
  roster=[
    Player("a1","RB1","RB", proj_next3=45, playoff_proj=30, bye_next3=0),
    Player("a2","WR1","WR", proj_next3=40, playoff_proj=28, bye_next3=0),
  ],
)
b = TeamState(
  team_id="B", starters_by_slot={"RB":2,"WR":2,"TE":1}, bench_redundancy={"RB":2,"WR":0,"TE":0},
  bye_exposure=0, injuries=0, schedule_difficulty=1.5, manager_profile={},
  roster=[
    Player("b1","WR2","WR", proj_next3=42, playoff_proj=25, bye_next3=0),
    Player("b2","RB2","RB", proj_next3=38, playoff_proj=27, bye_next3=0),
  ],
)
props, msg_id = propose_and_notify(s, a, b, top_k=3)
print("Inbox message id:", msg_id)
for p in props:
    print(p)
PY
```

## CLI

Migrate database schema:
```bash
python -m app.store migrate
```

Tuesday brief:
```bash
python -m app.schedule gm_brief
```

## Troubleshooting

- Port 8000 already in use:
```bash
lsof -i :8000
kill -9 <pid>
```

- Tokens missing or expired: re-run the OAuth steps. Ensure `.env` contains correct Redirect URI matching your ngrok URL.

- Yahoo API returns XML: pass `params={"format":"json"}` when calling API via `YahooClient().get(...)`.

- SQLite write errors: ensure repo directory is writable or set `DB_PATH` to a writable location.


## AI Agent

The app includes an AI Agent that pulls league data, ranks waivers, optimizes your lineup, and proposes trades. It talks to OpenAI and uses the app’s internal tools (ingest, scoring, waivers, trades, inbox, and optional writes).

### Prereqs
- Python venv active
- Yahoo OAuth connected
- ngrok URL set as Redirect URI in Yahoo
- OpenAI paid account

### Env
Add to `.env`:

```
OPENAI_API_KEY=sk-...
AI_AUTOPILOT=false               # true enables auto-execute for approved actions
AI_THRESHOLDS_JSON={"waiver":{"score_min":12,"confidence_min":0.65,"faab_cap_pct":0.25}}
```

### What the Agent can do
- Pull league state and parse LeagueSettings
- Rank waivers with FAAB min/max, settings-aware
- Optimize start/sit with injury and BYE rules
- Propose trades that improve both sides and relieve BYE zeros
- Post a single GM Brief to the Inbox with 3 actions
- Optionally execute waivers if autopilot and thresholds pass
- Everything is logged to SQLite for audit

### Run it
Daily brief:

```
python -m app.schedule ai_morning
```

Tuesday waiver plan:

```
python -m app.schedule ai_tuesday
```

Game day:

```
python -m app.schedule ai_gameday
```

Manual run:

```
python - <<'PY'
from app.ai.agent import run_agent
msg_id = run_agent("weekly_brief", constraints={})
print("Inbox message:", msg_id)
PY
```

### Approvals and autopilot
- By default the Agent asks for approval in the Inbox before writes.
- Set `AI_AUTOPILOT=true` to allow auto-execution for actions that meet thresholds.
- Thresholds live in `AI_THRESHOLDS_JSON` and are validated at startup.

### Observability
- Each agent run writes to `agent_runs`.
- Each tool call writes to `tool_calls`.
- Final decisions write to `decisions`.
Open an Inbox message and follow the summary to trace the run.

### Notes
- Every decision uses LeagueSettings. If settings are missing, runs stop.
- Trades are proposals only in v1. Waivers can execute with approval or autopilot.
- When in doubt on token usage, reduce context in `app/ai/context.py`.


