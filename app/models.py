from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ScoringBonus(BaseModel):
    description: str
    stat: str
    threshold: float
    points: float


class ScoringRules(BaseModel):
    # Core PPR/half/none
    ppr: float = Field(1.0, description="Points per reception: 1.0=PPR, 0.5=half, 0.0=standard")
    pass_td: float = 4.0
    pass_yd: float = 0.04  # 1 pt per 25 yards
    pass_int: float = -2.0
    rush_td: float = 6.0
    rush_yd: float = 0.1  # 1 pt per 10 yards
    rec_td: float = 6.0
    rec_yd: float = 0.1
    fumble_lost: float = -2.0

    # Kicker
    fg: Dict[str, float] = Field(default_factory=lambda: {"0-39": 3.0, "40-49": 4.0, "50+": 5.0})
    xp: float = 1.0

    # Defense/Special Teams simplified bucket
    dst_td: float = 6.0
    dst_sack: float = 1.0
    dst_int: float = 2.0
    dst_fum_rec: float = 2.0
    dst_pa: Dict[str, float] = Field(default_factory=lambda: {"0": 10.0, "1-6": 7.0, "7-13": 4.0, "14-20": 1.0, "21-27": 0.0, "28-34": -1.0, "35+": -4.0})

    bonuses: List[ScoringBonus] = Field(default_factory=list)


class PositionalLimits(BaseModel):
    qb: int
    rb: int
    wr: int
    te: int
    flex: int = 0
    superflex: int = 0
    k: int = 0
    dst: int = 0


class LeagueSettings(BaseModel):
    roster_slots: Dict[str, int]  # e.g., {"QB":1,"RB":2,"WR":2,"TE":1,"FLEX":1,"BENCH":5}
    positional_limits: PositionalLimits
    bench_size: int
    trade_deadline_week: Optional[int] = None
    faab_budget: Optional[int] = None
    scoring: ScoringRules

    @classmethod
    def from_yahoo(cls, raw: Dict) -> "LeagueSettings":
        # The Yahoo raw structure varies; expect a dict with keys that allow mapping.
        # This implementation is defensive and uses sane defaults.
        settings = raw.get("settings", raw)

        # Roster / position slots
        positions = settings.get("roster_positions") or settings.get("roster", {}).get("positions") or []
        slot_map: Dict[str, int] = {}
        bench = 0
        for pos in positions:
            # Yahoo may present as {"position": "RB", "count": 2} or similar
            name = pos.get("position") or pos.get("name") or str(pos)
            count = int(pos.get("count", 1))
            if name.upper() in {"BN", "BENCH"}:
                bench += count
            else:
                slot_map[name.upper()] = slot_map.get(name.upper(), 0) + count

        # Positional limits inferred from slot map
        positional_limits = PositionalLimits(
            qb=slot_map.get("QB", 0),
            rb=slot_map.get("RB", 0),
            wr=slot_map.get("WR", 0),
            te=slot_map.get("TE", 0),
            flex=slot_map.get("FLEX", 0) + slot_map.get("W/R/T", 0),
            superflex=slot_map.get("SUPERFLEX", 0) + slot_map.get("Q/W/R/T", 0),
            k=slot_map.get("K", 0),
            dst=slot_map.get("DEF", 0) + slot_map.get("DST", 0),
        )

        # FAAB & deadline
        faab = settings.get("faab") or settings.get("faab_budget")
        trade_deadline = settings.get("trade_deadline_week") or settings.get("trade_deadline")
        if isinstance(trade_deadline, dict):
            trade_deadline = trade_deadline.get("week")

        # Scoring
        scoring_raw = settings.get("scoring") or {}
        ppr_mode = scoring_raw.get("ppr")
        ppr = 1.0 if ppr_mode in (True, 1, "full", "PPR") else 0.5 if str(ppr_mode).lower() in ("0.5", "half") else 0.0 if ppr_mode in (False, 0, "standard") else 1.0

        # Map known stat weights if present
        sr = ScoringRules(
            ppr=ppr,
            pass_td=float(scoring_raw.get("pass_td", 4)),
            pass_yd=float(scoring_raw.get("pass_yd", 0.04)),
            pass_int=float(scoring_raw.get("pass_int", -2)),
            rush_td=float(scoring_raw.get("rush_td", 6)),
            rush_yd=float(scoring_raw.get("rush_yd", 0.1)),
            rec_td=float(scoring_raw.get("rec_td", 6)),
            rec_yd=float(scoring_raw.get("rec_yd", 0.1)),
            fumble_lost=float(scoring_raw.get("fumble_lost", -2)),
        )

        # Bonuses mapping (optional list)
        bonuses: List[ScoringBonus] = []
        for b in scoring_raw.get("bonuses", []):
            try:
                bonuses.append(
                    ScoringBonus(
                        description=b.get("description", ""),
                        stat=b.get("stat", ""),
                        threshold=float(b.get("threshold", 0)),
                        points=float(b.get("points", 0)),
                    )
                )
            except Exception:
                continue
        sr.bonuses = bonuses

        return cls(
            roster_slots=slot_map or {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1},
            positional_limits=positional_limits,
            bench_size=int(bench or settings.get("bench", 0) or 5),
            trade_deadline_week=int(trade_deadline) if trade_deadline else None,
            faab_budget=int(faab) if faab is not None else None,
            scoring=sr,
        )


