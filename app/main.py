import os
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, status, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from .db import get_connection, migrate, seed_example_data_if_empty
from .store import migrate as store_migrate
from .inbox import list_notifications as inbox_list, get_notification as inbox_get, mark_read as inbox_mark_read, unread_count as inbox_unread, latest_settings_payload, notify, mark_all_read as inbox_mark_all
from .brief import post_gm_brief
from .waivers import recommend_waivers, free_agents_from_yahoo
from .models import LeagueSettings
from .yahoo_client import YahooClient
from .config import get_settings
from .ingest import fetch_league_bundle, persist_bundle
from .store import record_snapshot
from .config import get_settings
from .utils import normalize_league_key


app = FastAPI(title="Fantasy Bot")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


@app.on_event("startup")
def on_startup() -> None:
    migrate()
    # Ensure full app schema exists (players, teams, recommendations, etc.)
    store_migrate()
    seed_example_data_if_empty()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/")
def list_notifications(request: Request, kind: Optional[str] = None):
    rows = inbox_list(kind)
    settings_payload = latest_settings_payload() or {}
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "notifications": rows,
            "unread": inbox_unread(),
            "filter_kind": kind or "",
            "league_settings": settings_payload,
        },
    )


@app.get("/notifications/{notification_id}")
def notification_detail(request: Request, notification_id: int):
    row = inbox_get(notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    return templates.TemplateResponse(
        "detail.html", {"request": request, "n": row, "unread": inbox_unread()}
    )


@app.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int):
    inbox_mark_read(notification_id)
    return RedirectResponse(url=f"/notifications/{notification_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/oauth/start")
def oauth_start():
    try:
        url = YahooClient().get_authorization_url(state="web")
        return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)
    except Exception as err:
        notify("info", "Yahoo OAuth not configured", f"{err}", {})
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/oauth/callback")
def oauth_callback(code: Optional[str] = None, error: Optional[str] = None):
    if error:
        notify("info", "Yahoo OAuth error", f"{error}", {})
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    try:
        YahooClient().exchange_code_for_tokens(code)
        notify("info", "Yahoo connected", "OAuth tokens saved.", {})
    except Exception as err:
        notify("info", "Yahoo OAuth error", f"{err}", {})
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/gm_brief")
def action_gm_brief():
    payload = latest_settings_payload() or {}
    raw = {"settings": payload} if payload else {"settings": {"roster_positions": [{"position": "QB", "count": 1}, {"position": "RB", "count": 2}, {"position": "WR", "count": 2}, {"position": "TE", "count": 1}, {"position": "W/R/T", "count": 1}, {"position": "BN", "count": 5}], "scoring": {"ppr": "full"}}}
    settings = LeagueSettings.from_yahoo(raw)
    post_gm_brief(settings)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/notifications/mark_all_read")
def action_mark_all_read():
    inbox_mark_all()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/waivers_demo")
def action_waivers_demo():
    payload = latest_settings_payload() or {}
    raw = {"settings": payload} if payload else {"settings": {"roster_positions": [{"position": "QB", "count": 1}, {"position": "RB", "count": 2}, {"position": "WR", "count": 2}, {"position": "TE", "count": 1}, {"position": "W/R/T", "count": 1}, {"position": "BN", "count": 5}], "scoring": {"ppr": "full"}}}
    settings = LeagueSettings.from_yahoo(raw)
    current = {"RB": 2, "WR": 2, "QB": 1, "TE": 1}
    free_agents = [
        {"id": "p_rb1", "name": "Upside RB", "position": "RB", "proj_base": 11, "trend_last2": 2, "schedule_next4": 1},
        {"id": "p_wr1", "name": "Volume WR", "position": "WR", "proj_base": 12, "trend_last2": 0, "schedule_next4": 0},
        {"id": "p_te1", "name": "Athletic TE", "position": "TE", "proj_base": 8, "trend_last2": 1, "schedule_next4": 2},
    ]
    recommend_waivers(settings=settings, current_starters_count=current, free_agents=free_agents, faab_remaining=50, waiver_type="faab", top_n=3)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/waivers_live")
def action_waivers_live(league_key: str = Form(None)):
    if not league_key:
        league_key = get_settings().league_key
    league_key = normalize_league_key(league_key)
    payload = latest_settings_payload() or {}
    raw = {"settings": payload} if payload else {"settings": {"roster_positions": [{"position": "QB", "count": 1}, {"position": "RB", "count": 2}, {"position": "WR", "count": 2}, {"position": "TE", "count": 1}, {"position": "W/R/T", "count": 1}, {"position": "BN", "count": 5}], "scoring": {"ppr": "full"}}}
    settings = LeagueSettings.from_yahoo(raw)
    try:
        client = YahooClient()
        fa = free_agents_from_yahoo(client, league_key)
        # Rough starter counts; future: compute from roster data
        current = {"RB": settings.positional_limits.rb, "WR": settings.positional_limits.wr, "QB": settings.positional_limits.qb, "TE": settings.positional_limits.te}
        recommend_waivers(settings=settings, current_starters_count=current, free_agents=fa, faab_remaining=100 if settings.faab_budget else 0, waiver_type="faab", top_n=5)
    except Exception as err:
        notify("info", "Waivers live error", f"{err}", {"league_key": league_key})
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/load_settings")
def action_load_settings(league_key: str = Form(None)):
    if not league_key:
        league_key = get_settings().league_key
    league_key = normalize_league_key(league_key)
    try:
        client = YahooClient()
        data = client.get(f"league/{league_key}", params={"format": "json"}).json()
        settings = LeagueSettings.from_yahoo(data)
        notify("info", "Detected League Settings", "Loaded from Yahoo.", settings.model_dump())
    except Exception as err:
        notify("info", "Load League Settings error", f"{err}", {"league_key": league_key})
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/ingest_now")
def action_ingest_now(league_key: str = Form(None)):
    if not league_key:
        league_key = get_settings().league_key
    league_key = normalize_league_key(league_key)
    try:
        client = YahooClient()
        bundle = fetch_league_bundle(client, league_key, cache_dir=".cache")
        # Snapshot each endpoint's raw JSON
        import json as _json
        endpoints = {
            "league": f"league/{league_key}",
            "teams": f"league/{league_key}/teams",
            "rosters": f"league/{league_key}/rosters",
            "players": f"league/{league_key}/players",
            "matchups": f"league/{league_key}/scoreboard",
            "standings": f"league/{league_key}/standings",
            "transactions": f"league/{league_key}/transactions",
        }
        for name, data in bundle.items():
            ep = endpoints.get(name, name)
            record_snapshot(endpoint=ep, params={"format": "json"}, raw=_json.dumps(data))
        # Persist into sqlite for local querying
        persist_bundle(bundle)
        notify("info", "Ingest complete", f"Cached and snapshotted {len(bundle)} endpoints.", {"league_key": league_key, "endpoints": list(bundle.keys())})
    except Exception as err:
        notify("info", "Ingest error", f"{err}", {"league_key": league_key})
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


