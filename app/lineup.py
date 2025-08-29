from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import LeagueSettings


@dataclass
class ProposedSwap:
    out_player_id: str
    in_player_id: str
    reason: str
    delta_points: float


def optimize_lineup(
    *,
    settings: LeagueSettings,
    candidates: List[Dict],  # each: {id, position, projected, injury, is_bye, tier}
    current_starters: Dict[str, List[str]],  # slot -> list of player ids
    delta_threshold_for_tier1: float = 3.0,
) -> List[ProposedSwap]:
    # Simple heuristic: for each slot capacity, ensure highest projected non-bye, non-D/Q over injured
    swaps: List[ProposedSwap] = []

    # Build pool by slot
    by_slot: Dict[str, List[Dict]] = {}
    for p in candidates:
        for slot in _eligible_slots(p["position"], settings):
            by_slot.setdefault(slot, []).append(p)

    # Apply filters
    for slot, players in by_slot.items():
        players.sort(key=lambda x: float(x.get("projected", 0.0)), reverse=True)

    # Enforce starters per positional limits
    limits = settings.positional_limits
    targets = {
        "QB": limits.qb,
        "RB": limits.rb,
        "WR": limits.wr,
        "TE": limits.te,
        "FLEX": limits.flex,
        "SUPERFLEX": limits.superflex,
    }

    for slot, required in targets.items():
        if required <= 0:
            continue
        pool = [p for p in by_slot.get(slot, []) if not p.get("is_bye")]
        # avoid Q/D unless small delta
        def ok(p):
            injury = str(p.get("injury", "")).upper()
            return injury not in {"D", "OUT"}

        chosen = []
        for p in pool:
            if len(chosen) >= required:
                break
            if ok(p) or not chosen:
                chosen.append(p)

        # Determine swaps vs current starters
        current = set(current_starters.get(slot, []))
        chosen_ids = {p["id"] for p in chosen}
        to_add = chosen_ids - current
        to_remove = current - chosen_ids
        for add_id in to_add:
            add = _find(candidates, add_id)
            # pick a remove with lowest projection
            rem_id = None
            rem_proj = 1e9
            for cid in current:
                cp = _find(candidates, cid)
                if cp and cp.get("projected", 0) < rem_proj:
                    rem_proj = cp.get("projected", 0)
                    rem_id = cid
            if add and rem_id:
                add_proj = float(add.get("projected", 0))
                delta = add_proj - float(rem_proj if rem_proj != 1e9 else 0)
                # never bench tier-1 unless delta>N
                if _is_tier1(rem_id, candidates) and delta < delta_threshold_for_tier1:
                    continue
                reason = f"{slot}: +{add_id} over {rem_id} (Δ {delta:.1f})"
                swaps.append(ProposedSwap(out_player_id=rem_id, in_player_id=add_id, reason=reason, delta_points=delta))

    swaps.sort(key=lambda s: s.delta_points, reverse=True)
    return swaps


def _eligible_slots(position: str, settings: LeagueSettings) -> List[str]:
    pos = position.upper()
    slots = [pos]
    if pos in {"RB", "WR", "TE"} and settings.positional_limits.flex > 0:
        slots.append("FLEX")
    if pos in {"QB", "RB", "WR", "TE"} and settings.positional_limits.superflex > 0:
        slots.append("SUPERFLEX")
    return slots


def _find(candidates: List[Dict], pid: str) -> Dict:
    for c in candidates:
        if c["id"] == pid:
            return c
    return {}


def _is_tier1(pid: str, candidates: List[Dict]) -> bool:
    c = _find(candidates, pid)
    return str(c.get("tier", "")).lower() == "tier-1"


__all__ = ["optimize_lineup", "ProposedSwap"]


