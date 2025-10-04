"""
Improved Yahoo free agents fetching using better API features.

Based on Yahoo Fantasy Sports API documentation:
https://developer.yahoo.com/fantasysports/guide/

Key improvements:
- Pagination with start parameter (bypass 25 limit)
- Position-specific queries
- Sort by Add/Drop rank (AR) for relevance
- Extract percent_owned for better scoring
"""
from typing import List, Dict
from .yahoo_client import YahooClient


def fetch_free_agents_paginated(
    client: YahooClient,
    league_key: str,
    position: str = None,
    total_players: int = 100,
    sort_by: str = "AR"  # AR = Add/Drop rank, OR = Ownership rank
) -> List[Dict]:
    """
    Fetch free agents using pagination to bypass Yahoo's 25-player limit.
    
    Args:
        client: YahooClient instance
        league_key: League key (e.g., "nfl.l.10530")
        position: Optional position filter (QB, RB, WR, TE, K, DEF)
        total_players: Total number of players to fetch
        sort_by: Sort method (AR for Add/Drop rank, OR for Ownership)
    
    Returns:
        List of player dicts with enhanced Yahoo data
    """
    all_players = []
    count_per_page = 25  # Yahoo's page size
    
    # Calculate how many pages we need
    num_pages = (total_players + count_per_page - 1) // count_per_page
    
    for page in range(num_pages):
        start = page * count_per_page
        
        # Build query path
        path_parts = [f"league/{league_key}/players", "status=A"]
        
        if position:
            path_parts.append(f"position={position}")
        
        path_parts.append(f"sort={sort_by}")
        path_parts.append(f"start={start}")
        path_parts.append(f"count={count_per_page}")
        
        path = ";".join(path_parts)
        
        try:
            response = client.get(path, params={"format": "json"})
            data = response.json()
            
            # Parse Yahoo's nested structure
            fc = data.get("fantasy_content", {})
            league_data = fc.get("league")
            
            # Yahoo returns league as [league_obj, {sub_resources}]
            players_data = {}
            if isinstance(league_data, list) and len(league_data) > 1:
                players_data = league_data[1].get("players", {})
            elif isinstance(league_data, dict):
                players_data = league_data.get("players", {})
            
            # Extract players from this page
            page_players = _parse_players_data(players_data)
            
            if not page_players:
                # No more players available
                break
            
            all_players.extend(page_players)
            
            # Stop if we've reached our target
            if len(all_players) >= total_players:
                break
                
        except Exception as e:
            print(f"[YAHOO] Error fetching page {page}: {e}")
            break
    
    return all_players[:total_players]


def fetch_free_agents_by_position(
    client: YahooClient,
    league_key: str,
    positions: List[str] = None,
    per_position: int = 20
) -> List[Dict]:
    """
    Fetch top free agents for each position separately.
    
    This approach gets better quality players than a generic query.
    
    Args:
        client: YahooClient instance
        league_key: League key
        positions: List of positions (defaults to QB, RB, WR, TE)
        per_position: Number of players per position
    
    Returns:
        Combined list of top free agents by position
    """
    if positions is None:
        positions = ["QB", "RB", "WR", "TE"]
    
    all_players = []
    
    for pos in positions:
        print(f"[YAHOO] Fetching top {per_position} free agents at {pos}...")
        players = fetch_free_agents_paginated(
            client=client,
            league_key=league_key,
            position=pos,
            total_players=per_position,
            sort_by="AR"  # Add/Drop rank
        )
        all_players.extend(players)
        print(f"[YAHOO] Found {len(players)} {pos}s")
    
    return all_players


def _parse_players_data(players_data: Dict) -> List[Dict]:
    """Parse Yahoo players data structure into clean player dicts."""
    result = []
    
    # Players are keyed numerically: "0", "1", "2", ...
    for key, value in players_data.items():
        if key == "count" or not key.isdigit():
            continue
        
        player_wrap = value
        if not isinstance(player_wrap, dict):
            continue
        
        player_list = player_wrap.get("player")
        if not isinstance(player_list, list):
            continue
        
        # Flatten Yahoo's nested list structure
        player = {}
        for item in player_list:
            if isinstance(item, list):
                for sub_item in item:
                    if isinstance(sub_item, dict):
                        player.update(sub_item)
            elif isinstance(item, dict):
                player.update(item)
        
        # Extract player info
        pid = str(player.get("player_id") or player.get("player_key") or "")
        if not pid:
            continue
        
        name_obj = player.get("name", {})
        if isinstance(name_obj, dict):
            name = name_obj.get("full") or name_obj.get("ascii_first", "") + " " + name_obj.get("ascii_last", "")
            name = name.strip()
        else:
            name = str(name_obj) if name_obj else pid
        
        pos = player.get("display_position") or player.get("primary_position") or "UTIL"
        team = player.get("editorial_team_abbr") or ""
        
        # Extract ownership percentage (key improvement!)
        ownership_obj = player.get("ownership", {})
        if isinstance(ownership_obj, dict):
            ownership_pct = float(ownership_obj.get("ownership_percentage", 0) or 0)
        else:
            ownership_pct = 0.0
        
        # Extract percent_owned for current week
        percent_owned = player.get("percent_owned", {})
        if isinstance(percent_owned, dict):
            coverage = percent_owned.get("coverage_type", "")
            value = percent_owned.get("value", 0)
            if coverage == "week":
                ownership_pct = max(ownership_pct, float(value or 0))
        
        # Extract bye week
        bye_weeks = player.get("bye_weeks", {})
        bye_week = None
        if isinstance(bye_weeks, dict):
            week_str = bye_weeks.get("week")
            if week_str:
                try:
                    bye_week = int(week_str)
                except:
                    pass
        
        # Extract status (IR, O, Q, D, etc.)
        status = player.get("status", "")
        
        # Extract player points (if available)
        player_points = player.get("player_points", {})
        total_pts = 0.0
        if isinstance(player_points, dict):
            total_pts = float(player_points.get("total", 0) or 0)
        
        result.append({
            "id": pid,
            "name": name,
            "position": pos,
            "team": team,
            "ownership_pct": ownership_pct,
            "bye_week": bye_week,
            "status": status,
            "total_pts": total_pts,
        })
    
    return result


__all__ = [
    "fetch_free_agents_paginated",
    "fetch_free_agents_by_position",
]

