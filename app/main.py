import os
from typing import Optional
from datetime import datetime, timedelta

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


@app.get("/api/dashboard/summary")
def dashboard_summary():
    """
    Lightweight endpoint for Coach Bar status.
    Returns key metrics without heavy computation.
    """
    # Get current week
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT MAX(week) FROM matchups")
        result = cur.fetchone()
        current_week = result[0] if result and result[0] else 1

        # Get my team info
        cfg = get_settings()
        my_team_id = cfg.team_key.split(".")[-1] if cfg.team_key else None

        # Count starters and injuries
        starters_ready = 0
        total_starters = 0
        injury_count = 0

        if my_team_id:
            cur.execute("""
                SELECT p.position, r.slot, r.status
                FROM rosters r
                JOIN players p ON r.player_id = p.id
                WHERE r.team_id = ? AND r.week = ?
            """, (my_team_id, current_week))

            for row in cur.fetchall():
                slot = row[1]
                status = row[2]

                # Count starters (not BN or IR)
                if slot and slot not in ["BN", "IR"]:
                    total_starters += 1
                    if status not in ["O", "IR", "D"]:
                        starters_ready += 1

                # Count injuries
                if status in ["O", "IR", "D", "Q"]:
                    injury_count += 1

        # Get opponent for this week
        opponent = None
        if my_team_id:
            cur.execute("""
                SELECT t.name
                FROM matchups m
                JOIN teams t ON m.opponent_id = t.id
                WHERE m.team_id = ? AND m.week = ?
            """, (my_team_id, current_week))
            result = cur.fetchone()
            if result:
                opponent = {"name": result[0]}

        # Get FAAB remaining from league settings
        payload = latest_settings_payload()
        faab_remaining = 100  # Default
        if payload:
            faab_budget = payload.get("faab_budget", 100)
            # TODO: Track actual FAAB spent
            faab_remaining = faab_budget

        # Get last sync time
        cur.execute("SELECT MAX(created_at) FROM snapshots")
        result = cur.fetchone()
        last_sync = None
        if result and result[0]:
            try:
                last_sync_dt = datetime.fromisoformat(result[0])
                delta = datetime.now() - last_sync_dt
                if delta < timedelta(minutes=5):
                    last_sync = "Just now"
                elif delta < timedelta(hours=1):
                    last_sync = f"{int(delta.total_seconds() / 60)}m ago"
                else:
                    last_sync = f"{int(delta.total_seconds() / 3600)}h ago"
            except:
                last_sync = "Unknown"

        # Count pending approvals
        pending_count = count_pending_recommendations()

        return {
            "current_week": current_week,
            "opponent": opponent,
            "win_chance": 50,  # TODO: Calculate from projections
            "starters_ready": starters_ready,
            "total_starters": max(total_starters, 9),
            "injury_count": injury_count,
            "faab_remaining": faab_remaining,
            "waiver_deadline": "Wed 12:00am",  # TODO: Get from league settings
            "last_sync": last_sync,
            "sync_status": "success",
            "pending_count": pending_count,
        }
    finally:
        conn.close()


@app.get("/")
def list_notifications(request: Request, kind: Optional[str] = None):
    rows = inbox_list(kind)
    settings_payload = latest_settings_payload() or {}
    pending_count = count_pending_recommendations()
    
    # Fetch top pending recommendations for Action Cards
    pending_recs = []
    try:
        from app.store import get_pending_recommendations
        pending_recs_raw = get_pending_recommendations()
        # Parse payload JSON for each recommendation
        for rec in pending_recs_raw:
            try:
                rec["payload_obj"] = json.loads(rec.get("payload") or "{}")
            except:
                rec["payload_obj"] = {}
            pending_recs.append(rec)
    except Exception as e:
        print(f"Error fetching pending recommendations: {e}")

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

            # Get my current lineup using REAL Yahoo slot data
            cur.execute("SELECT MAX(week) FROM matchups")
            current_week_result = cur.fetchone()
            current_week = current_week_result[0] if current_week_result else 1

            cur.execute("""
                SELECT p.name, p.position, p.team, p.bye_week, r.status, r.slot
                FROM rosters r
                JOIN players p ON r.player_id = p.id
                WHERE r.team_id = ? AND r.week = ?
                GROUP BY p.name, p.position, p.team
                ORDER BY
                    CASE WHEN r.slot = 'BN' THEN 99 WHEN r.slot IS NULL THEN 100 ELSE 0 END,
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

            # Use Yahoo's actual slot data: BN = bench, anything else = starter
            for row in cur.fetchall():
                slot = row[5]  # Yahoo slot: QB, RB, WR, W/R/T, TE, K, DEF, BN, etc.
                is_starter = (slot and slot != 'BN' and slot != 'IR')

                my_lineup.append({
                    "name": row[0],
                    "position": row[1],
                    "team": row[2] or "FA",
                    "bye_week": row[3],
                    "status": row[4] or "Active",
                    "is_starter": is_starter,
                    "slot": slot or "?"
                })
        except Exception as e:
            print(f"Error fetching lineup data: {e}")
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
            "pending_recs": pending_recs,  # Pass the full list, not just count
            "pending_count": pending_count,  # Keep count for backwards compatibility
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


@app.post("/actions/optimize_lineup")
def action_optimize_lineup():
    """Generate lineup optimization recommendations."""
    payload = latest_settings_payload() or {}
    if not payload:
        notify("info", "No settings", "Run 'Sync Yahoo Data' first to load league data.", {})
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    try:
        raw = {"settings": payload}
        settings = LeagueSettings.from_yahoo(raw)

        from .lineup_actions import run_lineup_optimizer_action
        msg_id = run_lineup_optimizer_action(settings)

        if msg_id:
            return RedirectResponse(url=f"/notifications/{msg_id}", status_code=status.HTTP_303_SEE_OTHER)
        else:
            return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as e:
        notify("info", "Optimizer error", f"Failed to optimize lineup: {e}", {})
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/approvals")
def approvals(request: Request):
    """List pending recommendations with parsed payloads."""
    recs = list_recommendations(status="pending")

    # Parse payload JSON for each recommendation
    for rec in recs:
        if rec.get("payload"):
            try:
                payload = rec["payload"]
                if isinstance(payload, str):
                    rec["payload_obj"] = json.loads(payload)
                else:
                    rec["payload_obj"] = payload
            except Exception as e:
                print(f"[APPROVALS] Failed to parse payload for rec#{rec['id']}: {e}")
                rec["payload_obj"] = {}
        else:
            rec["payload_obj"] = {}

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
                payload_str = rec.get("payload") or "{}"
                payload = _json.loads(payload_str) if isinstance(payload_str, str) else payload_str
            except Exception as e:
                print(f"[APPROVE] Failed to parse payload: {e}")
                payload = {}

            settings = get_settings()
            league_key = normalize_league_key(settings.league_key)
            team_key = settings.team_key
            if not league_key or not team_key:
                raise RuntimeError("LEAGUE_KEY and TEAM_KEY must be set in env for Yahoo writes")

            # Enhanced format: add_player_id, drop_player_id, faab_min
            add_player_id = payload.get("add_player_id")
            drop_player_id = payload.get("drop_player_id")
            faab = payload.get("faab_min", 0)
            add_player_name = payload.get("add_player_name", "Unknown")
            drop_player_name = payload.get("drop_player_name")

            if not add_player_id:
                raise RuntimeError("Missing add_player_id in recommendation payload")

            # Build Yahoo transaction XML
            # If drop_player_id exists, it's an add/drop. Otherwise, just add.
            if drop_player_id:
                xml = f"""
<fantasy_content>
  <transaction>
    <type>add/drop</type>
    <faab_bid>{int(faab)}</faab_bid>
    <players>
      <player>
        <player_key>{add_player_id}</player_key>
        <transaction_data>
          <type>add</type>
        </transaction_data>
      </player>
      <player>
        <player_key>{drop_player_id}</player_key>
        <transaction_data>
          <type>drop</type>
        </transaction_data>
      </player>
    </players>
  </transaction>
</fantasy_content>""".strip()
                action_desc = f"Add {add_player_name}, Drop {drop_player_name}"
            else:
                xml = f"""
<fantasy_content>
  <transaction>
    <type>add</type>
    <faab_bid>{int(faab)}</faab_bid>
    <player>
      <player_key>{add_player_id}</player_key>
    </player>
  </transaction>
</fantasy_content>""".strip()
                action_desc = f"Add {add_player_name}"

            # Submit to Yahoo
            client = YahooClient()
            resp = client.post_xml(f"league/{league_key}/transactions", xml)

            # Log transaction
            insert_transaction_raw(
                kind="waiver_submit",
                team_id=None,
                raw=f"request={_json.dumps({'xml': xml})}; response={resp.text}"
            )

            # Confirm to user
            notify("info", "✅ Waiver Claim Submitted",
                  f"{action_desc} with ${int(faab)} FAAB bid. Check Yahoo for confirmation.",
                  {"rec_id": rec_id, "yahoo_response": resp.text[:200]})
    except Exception as err:
        import traceback
        traceback.print_exc()
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
    recs, msg_id = recommend_waivers(settings=settings, current_starters_count=current, free_agents=free_agents, faab_remaining=50, waiver_type="faab", top_n=3)
    return RedirectResponse(url=f"/notifications/{msg_id}" if msg_id else "/", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/actions/waivers_live")
def action_waivers_live(league_key: str = Form(None)):
    """Enhanced waiver analysis with real projections and drop candidates."""
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
        # Get current week
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT MAX(week) FROM matchups")
            result = cur.fetchone()
            current_week = result[0] if result and result[0] else 1
        finally:
            conn.close()

        # Use enhanced waiver analysis
        from .waivers_enhanced import analyze_waivers_enhanced, post_enhanced_waivers_to_inbox

        recommendations = analyze_waivers_enhanced(
            settings=settings,
            week=current_week,
            max_players=75,
            top_n=5
        )

        msg_id = post_enhanced_waivers_to_inbox(recommendations, current_week)

        return RedirectResponse(url=f"/notifications/{msg_id}" if msg_id else "/", status_code=status.HTTP_303_SEE_OTHER)
    except Exception as err:
        notify("info", "Waivers error", f"{err}", {"league_key": league_key})
        import traceback
        traceback.print_exc()
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


