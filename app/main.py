import os
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, status, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from contextlib import asynccontextmanager
import json as _json

from .db import get_connection, migrate, seed_example_data_if_empty
from .store import migrate as store_migrate
from .inbox import list_notifications as inbox_list, get_notification as inbox_get, mark_read as inbox_mark_read, unread_count as inbox_unread, latest_settings_payload, notify, mark_all_read as inbox_mark_all
from .brief import post_gm_brief
from .waivers import recommend_waivers, free_agents_from_yahoo
from .models import LeagueSettings
from .yahoo_client import YahooClient
from .config import get_settings
from .ingest import fetch_league_bundle, persist_bundle
from .store import record_snapshot, list_recommendations, set_recommendation_status, count_pending_recommendations, get_recommendation, insert_transaction_raw
from .config import get_settings
from .utils import normalize_league_key
from .news import fetch_all_news
from .projections import get_projections
from .scouting import post_scouting_report, get_next_opponent


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate()
    # Ensure full app schema exists (players, teams, recommendations, etc.)
    store_migrate()
    seed_example_data_if_empty()
    yield


app = FastAPI(title="Fantasy Bot", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))




@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/news")
def api_news(limit: int = 30):
    """Get latest fantasy football news from all sources."""
    from fastapi.responses import JSONResponse
    items = fetch_all_news(max_age_minutes=20, limit_per_source=min(20, limit))
    return JSONResponse({"items": [it.to_dict() for it in items[:limit]]})


@app.get("/api/projections")
def api_projections(week: int, position: Optional[str] = None):
    """Get weekly player projections from FantasyPros."""
    from fastapi.responses import JSONResponse
    projections = get_projections(week, position, use_cache=True, max_age_hours=24)
    return JSONResponse({
        "week": week,
        "position": position,
        "count": len(projections),
        "projections": [p.to_dict() for p in projections[:100]]  # Limit response size
    })


@app.get("/")
def list_notifications(request: Request, kind: Optional[str] = None):
    rows = inbox_list(kind)
    settings_payload = latest_settings_payload() or {}
    pending_count = count_pending_recommendations()

    # Get league teams for scouting report dropdown and my starting lineup
    teams_list = []
    my_lineup = []
    if settings_payload:
        conn = get_connection()
        try:
            cfg = get_settings()
            my_team_id = cfg.team_key.split(".")[-1] if cfg.team_key else None
            
            cur = conn.cursor()
            cur.execute("SELECT id, name, manager FROM teams WHERE id != ? ORDER BY name", (my_team_id,))
            for row in cur.fetchall():
                teams_list.append({"id": row[0], "name": row[1], "manager": row[2]})
            
            # Get my current lineup (deduplicated, sorted by position)
            cur.execute("SELECT MAX(week) FROM matchups")
            current_week_result = cur.fetchone()
            current_week = current_week_result[0] if current_week_result else 1
            
            cur.execute("""
                SELECT p.name, p.position, p.team, p.bye_week, r.status
                FROM rosters r
                JOIN players p ON r.player_id = p.id
                WHERE r.team_id = ? AND r.week = ?
                GROUP BY p.name, p.position, p.team
                ORDER BY 
                    CASE p.position
                        WHEN 'QB' THEN 1
                        WHEN 'RB' THEN 2
                        WHEN 'WR' THEN 3
                        WHEN 'TE' THEN 4
                        WHEN 'K' THEN 5
                        WHEN 'DEF' THEN 6
                        ELSE 7
                    END,
                    p.name
            """, (my_team_id, current_week))
            
            for row in cur.fetchall():
                my_lineup.append({
                    "name": row[0],
                    "position": row[1],
                    "team": row[2] or "FA",
                    "bye_week": row[3],
                    "status": row[4] or "Active"
                })
        except:
            pass
        finally:
            conn.close()

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "notifications": rows,
            "unread": inbox_unread(),
            "filter_kind": kind or "",
            "league_settings": settings_payload,
            "pending_recs": pending_count,
            "teams": teams_list,
            "my_lineup": my_lineup,
        },
    )


@app.get("/notifications/{notification_id}")
def notification_detail(request: Request, notification_id: int):
    row = inbox_get(notification_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")

    payload_obj = {}
    payload_raw = row.get("payload") or "{}"

    # Ensure payload_obj is always a dict
    try:
        parsed = _json.loads(payload_raw)
        # Handle case where parsed value is a string (double-encoded JSON)
        if isinstance(parsed, str):
            payload_obj = _json.loads(parsed)
        elif isinstance(parsed, dict):
            payload_obj = parsed
        else:
            payload_obj = {}
    except Exception as e:
        # If parsing fails, payload_obj stays as empty dict
        payload_obj = {"_parse_error": str(e), "_raw": payload_raw[:100]}

    return templates.TemplateResponse(
        request, "detail.html", {"n": row, "payload_obj": payload_obj, "unread": inbox_unread()}
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
    if not payload:
        notify("info", "Missing LeagueSettings", "Load settings before posting GM Brief.", {})
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    raw = {"settings": payload}
    settings = LeagueSettings.from_yahoo(raw)
    post_gm_brief(settings)
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/notifications/mark_all_read")
def action_mark_all_read():
    inbox_mark_all()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/approvals")
def approvals(request: Request):
    recs = list_recommendations(status="pending")
    return templates.TemplateResponse(request, "approvals.html", {"recs": recs})


@app.post("/approvals/{rec_id}/approve")
def approve(rec_id: int):
    rec = get_recommendation(rec_id)
    if not rec:
        notify("info", "Recommendation not found", f"ID {rec_id}", {})
        return RedirectResponse(url="/approvals", status_code=status.HTTP_303_SEE_OTHER)

    # Default: mark approved
    set_recommendation_status(rec_id, "approved")

    # Attempt Yahoo write for waivers if configured
    try:
        if rec.get("kind") == "waivers":
            import json as _json
            payload = {}
            try:
                payload = _json.loads(rec.get("payload") or "{}")
            except Exception:
                payload = {}
            items = payload.get("items") or [payload]
            if not isinstance(items, list):
                items = [payload]
            settings = get_settings()
            league_key = normalize_league_key(settings.league_key)
            team_key = settings.team_key
            if not league_key or not team_key:
                raise RuntimeError("LEAGUE_KEY and TEAM_KEY must be set in env for Yahoo writes")
            # Build a minimal transaction XML: add with FAAB bid for first item
            item0 = items[0] if items else {}
            player_key = item0.get("player_id") or item0.get("player_key")
            faab = item0.get("faab_min") or item0.get("faab") or 0
            if not player_key:
                raise RuntimeError("Missing player_id in recommendation payload")
            xml = f"""
<fantasy_content>
  <transaction>
    <type>add</type>
    <faab_bid>{int(faab) if faab else 0}</faab_bid>
    <player>
      <player_key>{player_key}</player_key>
    </player>
    <team_key>{team_key}</team_key>
  </transaction>
</fantasy_content>""".strip()
            client = YahooClient()
            resp = client.post_xml(f"league/{league_key}/transactions", xml)
            insert_transaction_raw(kind="waiver_submit", team_id=None, raw=f"request={_json.dumps({'xml': xml})}; response={resp.text}")
            notify("info", "Waiver submitted", f"Submitted add for {player_key}", {"rec_id": rec_id})
    except Exception as err:
        notify("info", "Yahoo write error", f"{err}", {"rec_id": rec_id})

    notify("info", "Recommendation approved", f"Rec {rec_id} approved.", {"id": rec_id})
    return RedirectResponse(url="/approvals", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/scouting_report")
def action_scouting_report(opponent_team_id: str = Form(...)):
    """Generate AI-powered scouting report for specified opponent."""
    try:
        payload = latest_settings_payload()
        if not payload:
            notify("info", "No settings", "Run 'Ingest Now' first to load league data.")
            return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

        settings = LeagueSettings(**payload)

        # Get current week
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT MAX(week) FROM matchups")
            result = cur.fetchone()
            current_week = result[0] if result and result[0] else 1
        finally:
            conn.close()

        # Generate and post report
        msg_id = post_scouting_report(settings, opponent_team_id, current_week)

        return RedirectResponse(url=f"/notifications/{msg_id}", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        notify("info", "Scouting error", f"Failed to generate report: {e}", {})
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/approve_waiver")
def action_approve_waiver(add_player_id: str = Form(...), drop_player_id: Optional[str] = Form(None), bid_amount: Optional[float] = Form(0)):
    # Attempt Yahoo write; if not configured, just post a confirmation
    try:
        settings = get_settings()
        league_key = normalize_league_key(settings.league_key)
        team_key = settings.team_key
        if not league_key or not team_key:
            raise RuntimeError("LEAGUE_KEY and TEAM_KEY must be set in env for Yahoo writes")
        xml = f"""
<fantasy_content>
  <transaction>
    <type>add</type>
    <faab_bid>{int(bid_amount or 0)}</faab_bid>
    <player>
      <player_key>{add_player_id}</player_key>
    </player>
    <team_key>{team_key}</team_key>
  </transaction>
</fantasy_content>""".strip()
        client = YahooClient()
        resp = client.post_xml(f"league/{league_key}/transactions", xml)
        insert_transaction_raw(kind="waiver_submit", team_id=None, raw=f"request={_json.dumps({'xml': xml})}; response={resp.text}")
        notify("waivers", "Executed waiver", f"Added {add_player_id} for {int(bid_amount or 0)} FAAB", {"add_player_id": add_player_id, "bid": bid_amount})
    except Exception as err:
        notify("info", "Waiver execute error", f"{err}", {"add_player_id": add_player_id, "bid": bid_amount})
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/deny_waiver")
def action_deny_waiver(add_player_id: str = Form(...)):
    notify("waivers", "Waiver denied", f"Denied add for {add_player_id}", {"add_player_id": add_player_id})
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/approvals/{rec_id}/deny")
def deny(rec_id: int):
    set_recommendation_status(rec_id, "cancelled")
    notify("info", "Recommendation denied", f"Rec {rec_id} denied.", {"id": rec_id})
    return RedirectResponse(url="/approvals", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/waivers_demo")
def action_waivers_demo():
    payload = latest_settings_payload() or {}
    if not payload:
        notify("info", "Missing LeagueSettings", "Load settings before running waivers.", {})
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    raw = {"settings": payload}
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
    if not league_key:
        notify("info", "League key not configured", "Set LEAGUE_KEY in .env", {})
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    payload = latest_settings_payload() or {}
    if not payload:
        notify("info", "Missing LeagueSettings", "Load settings before running waivers.", {})
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    raw = {"settings": payload}
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
    if not league_key:
        notify("info", "League key not configured", "Set LEAGUE_KEY in .env", {})
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
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
    if not league_key:
        notify("info", "League key not configured", "Set LEAGUE_KEY in .env", {})
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
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
        # err may include response text; include it in payload for diagnostics
        notify("info", "Ingest error", f"{err}", {"league_key": league_key, "error": str(err)})
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


