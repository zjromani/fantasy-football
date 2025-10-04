from __future__ import annotations

from typing import Dict, List, Tuple
import json as _json

from .inbox import notify
from .models import LeagueSettings
from .store import get_connection
from .ai.client import ask
from .ai.config import get_ai_settings
from .config import get_settings
from .news import fetch_all_news, get_injury_news


def _get_league_context(settings: LeagueSettings) -> Dict:
    """Fetch current league state from database."""
    conn = get_connection()
    try:
        cur = conn.cursor()

        # Get user's team
        cfg = get_settings()
        my_team_id = cfg.team_key.split(".")[-1] if cfg.team_key else None

        # Teams
        cur.execute("SELECT id, name, manager FROM teams")
        teams = [{"id": row[0], "name": row[1], "manager": row[2]} for row in cur.fetchall()]

        # My roster (current week)
        my_roster = []
        if my_team_id:
            cur.execute(
                "SELECT r.player_id, p.name, p.position, r.slot, r.status FROM rosters r "
                "LEFT JOIN players p ON r.player_id = p.id "
                "WHERE r.team_id = ? ORDER BY r.week DESC LIMIT 20",
                (my_team_id,)
            )
            my_roster = [
                {"id": row[0], "name": row[1], "position": row[2], "slot": row[3], "status": row[4]}
                for row in cur.fetchall()
            ]

        # Recent transactions (last 20)
        cur.execute(
            "SELECT kind, team_id, raw FROM transactions_raw ORDER BY id DESC LIMIT 20"
        )
        transactions = []
        for row in cur.fetchall():
            try:
                tx_data = _json.loads(row[2]) if row[2] else {}
                transactions.append({"kind": row[0], "team_id": row[1], "data": tx_data})
            except:
                pass

        # Matchups (current week)
        cur.execute(
            "SELECT week, team_id, opponent_id FROM matchups ORDER BY week DESC LIMIT 12"
        )
        matchups = [{"week": row[0], "team": row[1], "opponent": row[2]} for row in cur.fetchall()]

        return {
            "teams": teams,
            "my_team_id": my_team_id,
            "my_roster": my_roster,
            "transactions": transactions,
            "matchups": matchups,
            "settings": settings.model_dump(),
        }
    finally:
        conn.close()


def build_gm_brief(settings: LeagueSettings) -> Tuple[str, str, Dict]:
    """Generate AI-powered GM brief using OpenAI."""
    context = _get_league_context(settings)

    try:
        # Check if OpenAI is configured
        ai_settings = get_ai_settings()

        # Get latest news for context
        all_news = fetch_all_news(max_age_minutes=60, limit_per_source=15)
        injury_news = get_injury_news(limit=10)

        # Format news for AI
        news_summary = []
        for item in injury_news[:5]:
            news_summary.append(f"- [{item.source}] {item.title}")

        for item in all_news[:10]:
            if item.category != "injury":  # Already got injuries above
                news_summary.append(f"- [{item.source}] {item.title}")

        # Build enhanced context with player details
        roster_detail = []
        for p in context['my_roster']:
            roster_detail.append({
                "name": p.get('name'),
                "position": p.get('position'),
                "slot": p.get('slot'),
                "status": p.get('status') or "Active"
            })

        # Build prompt for OpenAI
        prompt = f"""You are an expert fantasy football advisor for NFL Week {context.get('current_week', '?')}.
Generate a concise, actionable GM brief for the user's fantasy team.

LEAGUE SETTINGS:
- Scoring: {"PPR (1.0)" if settings.scoring.ppr == 1 else ("Half-PPR (0.5)" if settings.scoring.ppr == 0.5 else "Standard (0.0)")}
- Starting Roster: {settings.roster_slots}
- FAAB Budget: ${settings.faab_budget or 100}

YOUR CURRENT ROSTER ({len(roster_detail)} players):
{_json.dumps(roster_detail, indent=2)}

LATEST NFL NEWS (use this for injury/status updates):
{chr(10).join(news_summary)}

RECENT LEAGUE TRANSACTIONS:
{_json.dumps(context['transactions'][:3], indent=2)}

MATCHUP INFO:
{_json.dumps(context['matchups'][:3], indent=2)}

IMPORTANT INSTRUCTIONS:
- Use the NEWS section above to inform your recommendations (injuries, player status, team changes)
- Only recommend players who are actually available as free agents (not on rosters)
- Check the transactions to see recent league activity
- Be specific about WHICH players from the user's roster to start/sit
- Provide FAAB bid ranges (e.g., $5-8) for waiver recommendations
- Focus on THIS week's matchups and decisions

Generate a brief with these sections:
1. **🎯 Actions** (3-4 items): Immediate action items for this week
2. **👥 Lineup** (2-3 items): Specific sit/start advice from YOUR ROSTER above
3. **➕ Waivers** (Top 3-5): Available free agents to target with FAAB ranges
4. **🔄 Trades** (1-2 items): Trade opportunities based on team needs
5. **⚡ Key Insights**: Injury alerts and important news affecting your players

Format as markdown. Be concise but specific."""

        # Call OpenAI
        response = ask(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            max_tokens=1500,
            temperature=0.7,
        )

        ai_body = response.get("content", "AI brief generation failed")

        # Parse sections for payload (best effort)
        payload = {
            "ai_generated": True,
            "context": context,
            "raw_response": ai_body,
            "settings": settings.model_dump(),
        }

        return "🤖 AI GM Brief", ai_body, payload

    except Exception as e:
        # Fallback to data-driven brief if AI fails
        return _build_data_brief(settings, context, str(e))


def _build_data_brief(settings: LeagueSettings, context: Dict, error: str) -> Tuple[str, str, Dict]:
    """Data-driven brief when AI is unavailable."""

    # Build intelligent fallback using actual data
    body_lines = [
        "## 📊 GM Brief",
        "",
        "### Your Team",
        f"- **Roster:** {len(context['my_roster'])} players",
        f"- **Scoring:** PPR={settings.scoring.ppr}",
        f"- **FAAB Budget:** ${settings.faab_budget or 100}",
        "",
        "### Current Roster",
    ]

    # Group by position
    by_pos = {}
    for p in context['my_roster']:
        pos = p.get('position') or 'UNKNOWN'
        by_pos.setdefault(pos, []).append(p)

    for pos in ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']:
        players = by_pos.get(pos, [])
        if players:
            names = [p.get('name', 'Unknown') for p in players if p.get('name')]
            if names:
                body_lines.append(f"- **{pos}:** {', '.join(names)}")

    body_lines.extend([
        "",
        "### Recent League Activity",
        f"- {len(context['transactions'])} transactions in database",
        f"- {len(context['matchups'])} matchups tracked",
        "",
        "### Actions",
        "- Review your roster for injury updates",
        "- Check waiver wire for breakout candidates",
        "- Scout trade opportunities with league managers",
        "",
        "---",
    ])

    # Add helpful message based on error type
    if "insufficient_quota" in error or "RateLimitError" in error:
        body_lines.append("_💡 OpenAI API quota exceeded. Add credits at https://platform.openai.com/account/billing_")
    elif "OPENAI_API_KEY" in error and "required" in error:
        body_lines.append("_💡 To enable AI-powered insights, set `OPENAI_API_KEY` in your .env file_")
    else:
        body_lines.append(f"_⚠️ AI unavailable: {error[:80]}_" if len(error) < 80 else f"_⚠️ AI unavailable: {error[:80]}..._")

    return "📊 GM Brief", "\n".join(body_lines), {"data_driven": True, "error": error, "context": context}


def post_gm_brief(settings: LeagueSettings) -> int:
    title, body, payload = build_gm_brief(settings)
    return notify("brief", title, body, payload)


__all__ = ["build_gm_brief", "post_gm_brief"]


