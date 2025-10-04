"""
AI agent prompts and instruction templates.
Defines the system prompt, style, and policy constraints.

Based on best practices:
- Provide league context up front
- Force reasoning steps (numbered logic)
- Constrain domain to provided data only
- Ask for trade-offs and risk bands
- Use chain-of-thought with structured output
"""

# ==============================================================================
# LEGACY AGENT PROMPTS (for AI tool calling agent)
# ==============================================================================

SYSTEM = (
    "You are an assistant for a fantasy football app. All decisions must be settings-driven."
    " Do not assume scoring or roster slots; use tools to fetch facts."
    " Prefer safe changes; ask for approval unless autopilot is explicitly enabled."
)

STYLE = (
    "Slack-style. Short sentences. Include numbers. One-liner rationales."
)

POLICY = (
    "Allowed tools: get_league_state, rank_waivers, optimize_lineup, find_trade_opportunities, post_inbox, execute_waiver."
    " Never submit trades via Yahoo in v1."
)


# ==============================================================================
# WAIVER WIRE RECOMMENDATION PROMPT
# ==============================================================================

WAIVER_SYSTEM = """
You are a fantasy football analytics engine. You interpret data exactly, do not hallucinate.
Always cite reasoning steps. Only recommend players from the provided free agents list.
"""

def build_waiver_prompt(
    league_settings: dict,
    my_roster: list[dict],
    free_agents: list[dict],
    current_week: int,
    faab_remaining: int,
    recent_transactions: list[dict] = None
) -> str:
    """
    Build a structured waiver recommendation prompt.

    Args:
        league_settings: Scoring rules, roster slots, etc.
        my_roster: Current roster with positions, projections, status
        free_agents: Available players with stats/trends/projections
        current_week: Current NFL week
        faab_remaining: Remaining FAAB budget
        recent_transactions: Optional recent add/drop activity

    Returns:
        Formatted prompt string
    """
    # Format roster for prompt
    roster_text = "\n".join([
        f"  - {p['name']} ({p['position']}, {p.get('team', '??')}) - "
        f"Slot: {p.get('slot', 'BN')}, Proj: {p.get('projection', 'N/A')} pts, "
        f"Status: {p.get('status', 'Healthy')}"
        for p in my_roster
    ])

    # Format free agents for prompt
    fa_text = "\n".join([
        f"  {i+1}. {fa['name']} ({fa['position']}, {fa.get('team', '??')}) - "
        f"Proj: {fa.get('projection', fa.get('proj_base', 'N/A'))} pts, "
        f"Status: {fa.get('status', 'Healthy')}, "
        f"Bye: Week {fa.get('bye_week', 'N/A')}"
        for i, fa in enumerate(free_agents[:50])  # Limit to top 50
    ])

    # Format league settings
    scoring = league_settings.get('scoring', {})
    scoring_text = f"PPR: {scoring.get('ppr', 0)}, Pass TD: {scoring.get('pass_td', 4)}, Rush/Rec TD: {scoring.get('rush_td', 6)}"

    return f"""
I give you:

**LEAGUE SETTINGS:**
- Scoring: {scoring_text}
- Roster Slots: {league_settings.get('roster_slots', 'Standard')}
- FAAB Budget Remaining: ${faab_remaining}
- Current Week: {current_week}

**MY ROSTER (Starters + Bench):**
{roster_text}

**FREE AGENTS (Top {len(free_agents[:50])} Available):**
{fa_text}

**TASK:**
Rank the **top 5 waiver claims** that would improve my roster. For each, provide:

1. **player_name** and **position** (from free agents list above)
2. **projected_points** this week (use provided projections)
3. **drop_candidate** (which of my bench players to drop, if any)
4. **net_gain** (projected improvement in points)
5. **faab_bid_range** (min-max, respecting my ${faab_remaining} budget)
6. **reasoning** (3 numbered points):
   - Matchup analysis
   - Recent trend or opportunity
   - How this fills a roster gap

**CONSTRAINTS:**
- Only recommend players from the FREE AGENTS list above
- Do not suggest dropping starters (slot != BN)
- Do not suggest dropping healthy players with higher projections than the add
- Cap FAAB bids at ${faab_remaining} total
- Skip players with status "O" (Out) or "IR" (Injured Reserve)

**OUTPUT FORMAT:**
Provide a concise analysis followed by a numbered list (1-5) with:
- Player to add
- Player to drop
- Net gain
- FAAB range
- 3-point reasoning

Think step-by-step. Be conservative. Cite the data I provided.
"""


# ==============================================================================
# TRADE PROPOSAL PROMPT
# ==============================================================================

TRADE_SYSTEM = """
You are a fantasy trade advisor. Your output must always improve the user's roster based on league rules.
Never suggest one-sided trades. Be realistic about acceptance probability.
"""

def build_trade_prompt(
    league_settings: dict,
    my_roster: list[dict],
    opponent_roster: list[dict],
    opponent_name: str,
    current_week: int,
    manager_tendencies: dict = None
) -> str:
    """
    Build a structured trade proposal prompt.

    Args:
        league_settings: Scoring rules, roster slots
        my_roster: My team with projections
        opponent_roster: Opponent's team with projections
        opponent_name: Opponent manager name
        current_week: Current NFL week
        manager_tendencies: Optional tendencies (trade acceptance history, etc.)

    Returns:
        Formatted prompt string
    """
    # Format rosters
    my_roster_text = "\n".join([
        f"  - {p['name']} ({p['position']}, {p.get('team', '??')}) - "
        f"Proj: {p.get('projection', 'N/A')} pts, Slot: {p.get('slot', 'BN')}"
        for p in my_roster
    ])

    opponent_roster_text = "\n".join([
        f"  - {p['name']} ({p['position']}, {p.get('team', '??')}) - "
        f"Proj: {p.get('projection', 'N/A')} pts"
        for p in opponent_roster
    ])

    tendencies_text = ""
    if manager_tendencies:
        tendencies_text = f"""
**OPPONENT TENDENCIES ({opponent_name}):**
- Trade acceptance rate: {manager_tendencies.get('trade_accept_rate', 'Unknown')}
- Position preference: {manager_tendencies.get('position_bias', 'Unknown')}
- Typical action: {manager_tendencies.get('action_time', 'Unknown')}
"""

    return f"""
I give you:

**LEAGUE SETTINGS:**
- Scoring: PPR {league_settings.get('scoring', {}).get('ppr', 0)}
- Current Week: {current_week}

**MY ROSTER:**
{my_roster_text}

**OPPONENT'S ROSTER ({opponent_name}):**
{opponent_roster_text}

{tendencies_text}

**TASK:**
Propose **2 fair trade ideas** that improve my roster while also benefiting {opponent_name}. For each:

1. **you_give**: List of players I trade away (names & positions)
2. **you_receive**: List of players I get (names & positions)
3. **net_points_gain_me**: My projected point gain over next 3 weeks
4. **net_points_gain_opponent**: Their projected point gain over next 3 weeks
5. **acceptance_probability**: Estimate 0.0-1.0 (both must gain)
6. **rationale** (3 bullets):
   - How this addresses my positional needs
   - How this addresses their positional needs
   - Schedule/matchup advantages
7. **risk_factors**: Injury risk, usage volatility, playoff implications

**CONSTRAINTS:**
- Both sides must gain points (mutual benefit)
- Do not trade away my highest-projected starter at any position
- Only include players from the rosters I provided
- Keep trades simple (1-for-1 or 2-for-2 max)
- Consider bye weeks and injury status

**OUTPUT FORMAT:**
Provide brief analysis, then 2 trade proposals with all fields above.

Think through roster gaps carefully. Be realistic about acceptance odds.
"""


# ==============================================================================
# LINEUP OPTIMIZATION PROMPT
# ==============================================================================

LINEUP_SYSTEM = """
You are a fantasy lineup optimizer. Only choose among the eligible players provided.
Always explain your reasoning with data. Consider matchups, injuries, and upside.
"""

def build_lineup_prompt(
    league_settings: dict,
    my_roster: list[dict],
    current_week: int,
    opponent_defenses: dict = None,
    weather: dict = None
) -> str:
    """
    Build a structured lineup optimization prompt.

    Args:
        league_settings: Scoring rules, roster slots
        my_roster: Available players with projections, status, matchups
        current_week: Current NFL week
        opponent_defenses: Optional defensive rankings by position
        weather: Optional weather data for games

    Returns:
        Formatted prompt string
    """
    # Format roster with all details
    roster_text = "\n".join([
        f"  {i+1}. {p['name']} ({p['position']}, {p.get('team', '??')}) - "
        f"Current Slot: {p.get('slot', 'BN')}, "
        f"Proj: {p.get('projection', 'N/A')} pts, "
        f"Opponent: {p.get('opponent', '??')}, "
        f"Status: {p.get('status', 'Healthy')}, "
        f"News: {p.get('news_summary', 'None')[:60]}"
        for i, p in enumerate(my_roster)
    ])

    # Format roster requirements
    slots = league_settings.get('roster_slots', {})
    slots_text = ", ".join([f"{pos}: {count}" for pos, count in slots.items() if count > 0 and pos != 'BENCH'])

    context_text = ""
    if opponent_defenses:
        context_text += "\n**DEFENSIVE MATCHUPS:**\n"
        for pos, rankings in opponent_defenses.items():
            context_text += f"  {pos}: {rankings}\n"

    if weather:
        context_text += "\n**WEATHER ALERTS:**\n"
        for game, conditions in weather.items():
            context_text += f"  {game}: {conditions}\n"

    return f"""
I give you:

**LEAGUE SETTINGS:**
- Scoring: PPR {league_settings.get('scoring', {}).get('ppr', 0)}
- Required Starting Slots: {slots_text}
- Current Week: {current_week}

**MY ROSTER (Current Lineup):**
{roster_text}

{context_text}

**TASK:**
Optimize my starting lineup. For each position, choose the best player(s) from my roster. Provide:

1. **starters**: List of players who should start (with positions)
2. **bench**: List of players who should be benched
3. **swaps**: For each change from current lineup, explain:
   - Player moved to starting
   - Player moved to bench
   - Delta points (estimated improvement)
   - Rationale (2 bullets: matchup + upside/risk)
4. **total_expected_gain**: Sum of all positive deltas vs current lineup

**CONSTRAINTS:**
- Only select from MY ROSTER above
- Respect positional eligibility and slot counts ({slots_text})
- Do not start players with status "O" (Out) or "IR" (Injured Reserve)
- Do not start players with status "D" (Doubtful) unless no alternative
- Prioritize players with favorable matchups and high projections

**OUTPUT FORMAT:**
Provide brief analysis of key matchups, then:
- Starting lineup (by position)
- Bench players
- Recommended swaps with reasoning
- Total expected point gain

Use the data I provided. Be conservative with risky plays.
"""


__all__ = [
    "SYSTEM",
    "STYLE",
    "POLICY",
    "WAIVER_SYSTEM",
    "TRADE_SYSTEM",
    "LINEUP_SYSTEM",
    "build_waiver_prompt",
    "build_trade_prompt",
    "build_lineup_prompt",
]
