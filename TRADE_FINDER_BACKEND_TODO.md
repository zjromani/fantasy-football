# Trade Finder Backend Implementation

## Owner Mode Philosophy

**Owner clicks one button → GM does all the work → Owner accepts/declines recommendations**

The UI has a single "Find Trade Opportunities" button. No team selection. The GM scans ALL teams, finds the best opportunities based on:
- Manager tendencies (past trades, acceptance rate)
- Position needs (both teams)
- Bye week issues
- Playoff schedules
- Mutual benefit scores

## UI Already Built ✅

1. **"Find Trade Opportunities" button** - One click, GM handles everything
2. **Trade proposal cards** - Shows:
   - Acceptance odds (color-coded: green >70%, yellow >50%, red <50%)
   - Send vs Receive comparison with player names
   - Mutual benefit score
   - Manager tendencies/intel
   - Rationale for each trade
3. **Action card integration** - Trades appear in Owner Inbox with Accept/Decline

## Backend Route Needed

Create `/actions/find_trades` POST endpoint:

```python
@app.route("/actions/find_trades", methods=["POST"])
def find_trades(request: Request):
    """
    GM scans all teams in the league and finds best trade opportunities.
    No user input needed - this is fully automated analysis.
    """

    # Get my team state
    my_team = build_team_state(my_team_id)
    league_settings = get_league_settings()

    # Scan ALL teams except mine
    teams = get_all_teams_except_mine()
    all_proposals = []
    manager_intel = {}

    for opponent in teams:
        # Build opponent state with transaction history
        opponent_state = build_team_state(opponent.id)

        # Analyze manager tendencies from past transactions
        tendencies = analyze_manager_tendencies(
            team_id=opponent.id,
            transactions=get_team_transactions(opponent.id)
        )
        manager_intel[opponent.id] = tendencies

        # Use existing trades.py logic to find mutual benefit trades
        proposals = propose_trades(
            settings=league_settings,
            team_a=my_team,
            team_b=opponent_state,
            top_k=2  # Get top 2 from each team
        )

        # Attach opponent name for display
        for p in proposals:
            p.opponent_name = opponent.name
            p.opponent_manager = opponent.manager
            p.manager_tendencies = tendencies

        all_proposals.extend(proposals)

    if not all_proposals:
        # No trades found
        notify(
            kind="trades",
            title="No Trade Opportunities Found",
            body="GM scanned all teams. No mutually beneficial trades available right now. Try again next week or after waivers clear.",
            payload={}
        )
        return redirect("/")

    # Sort by value score: acceptance_odds * both_sides_gain
    # This prioritizes trades that are LIKELY TO BE ACCEPTED and VALUABLE
    best_proposals = sorted(
        all_proposals,
        key=lambda p: p.acceptance_odds * p.both_sides_gain,
        reverse=True
    )[:5]  # Keep top 5 overall

    # Build manager intel summary
    intel_summary = []
    for p in best_proposals:
        mgr = p.opponent_manager
        tendencies = p.manager_tendencies
        intel_summary.append(
            f"{mgr}: {tendencies.get('trade_acceptance_rate', 0.5)*100:.0f}% acceptance rate, "
            f"values {tendencies.get('position_preference', 'balance')}, "
            f"{tendencies.get('recent_activity', 'inactive')}"
        )

    # Create recommendation in Owner Inbox
    # Each proposal becomes a separate recommendation OR group them
    notify(
        kind="trades",
        title=f"GM Found {len(best_proposals)} Trade Opportunities",
        body=f"Scanned {len(teams)} teams. Ranked by acceptance probability and value.",
        payload={
            "proposals": [
                {
                    **p.__dict__,
                    "opponent_name": p.opponent_name,
                    "opponent_manager": p.opponent_manager,
                }
                for p in best_proposals
            ],
            "manager_tendencies": intel_summary,
            "scan_summary": f"Analyzed {len(all_proposals)} potential trades across {len(teams)} teams",
        }
    )

    return redirect("/")
```

## Data Sources Needed

To make this work, the backend needs to:

### 1. Manager Tendencies Tracking
```python
# Store in database or analyze from transaction history
manager_tendencies = {
    "trade_acceptance_rate": 0.65,  # Accept 65% of offers
    "position_preference": "WR",     # Values WRs highly
    "recent_trades": [
        {"gave": ["RB1"], "got": ["WR1", "WR2"], "week": 4},
    ],
    "bye_week_panic": True,  # Trades aggressively during byes
    "playoff_priorit": 0.8,  # Values playoff schedule (0-1)
}
```

### 2. Team State Builder
```python
def build_team_state(team_id: str) -> TeamState:
    roster = get_roster(team_id)
    transactions = get_team_transactions(team_id)

    return TeamState(
        team_id=team_id,
        starters_by_slot=get_roster_slots(),
        bench_redundancy=count_bench_by_position(roster),
        bye_exposure=count_upcoming_byes(roster),
        injuries=count_injured(roster),
        schedule_difficulty=calculate_schedule_strength(team_id),
        manager_profile=get_manager_tendencies(team_id, transactions),
        roster=[Player(...) for p in roster]
    )
```

### 3. Transaction History Analyzer
```python
def analyze_manager_tendencies(team_id: str, transactions: list) -> dict:
    # Look at past trades
    trades = [t for t in transactions if t["type"] == "trade"]

    # Calculate acceptance rate (if we track proposals vs accepted)
    # Or use league average if unknown
    acceptance_rate = len(trades) / max(1, proposed_count) if proposed_count else 0.5

    # Detect position preferences
    # What positions do they acquire vs give up?
    acquired_positions = [p["position"] for t in trades for p in t["received"]]
    given_positions = [p["position"] for t in trades for p in t["sent"]]

    position_bias = most_common(acquired_positions)

    # Detect timing patterns
    # Do they trade right before deadlines? During bye weeks?
    trade_weeks = [t["week"] for t in trades]
    bye_week_activity = has_bye_week_pattern(trade_weeks, team_byes)

    return {
        "trade_acceptance_rate": acceptance_rate,
        "position_preference": position_bias,
        "bye_week_reactive": bye_week_activity,
        "recent_activity": f"{len(trades)} trades in last 4 weeks",
    }
```

## Auto-Loop Integration (Future)

Make trade scanning automatic:
- **Thursday scan** - After waivers clear, GM automatically scans for trades
- **Monday scan** - After weekly results, GM looks for buy-low/sell-high opportunities
- **Deadline proximity** - Increase scan frequency 1 week before trade deadline

Owner just gets notifications: "GM found 3 new trade opportunities this week"

## UI Enhancements (Future)

Once backend is working:
1. **Add "Copy to Yahoo" button** - Pre-fill Yahoo trade form with proposal
2. **Show trade deadline countdown** - "7 days until deadline"
3. **Historical success rate** - "You've completed 3/5 trades with this manager"
4. **Alternative trades** - "If they decline, GM will suggest these backups..."
5. **Trade value chart** - Visual comparison of player values
6. **Negotiation hints** - "Offer WR2 instead of WR1 to increase acceptance odds to 85%"

## Testing Strategy

1. **Unit tests** - Test `propose_trades()` with mock rosters
2. **Integration test** - Test full `/actions/find_trades` flow
3. **Manager tendency accuracy** - Validate predictions vs actual outcomes
4. **Performance** - "Scan All Teams" should complete in <3s

## Success Metrics

Track:
- Trade proposals generated
- Acceptance rate of AI-proposed trades
- Time saved vs manual Yahoo browsing
- Owner satisfaction with trade suggestions

