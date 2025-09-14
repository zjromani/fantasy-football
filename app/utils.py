import re


def normalize_league_key(raw: str | None) -> str | None:
    if not raw:
        return raw
    s = raw.strip()
    if re.fullmatch(r"\d+", s):
        return f"nfl.l.{s}"
    m = re.fullmatch(r"l\.(\d+)", s, flags=re.IGNORECASE)
    if m:
        return f"nfl.l.{m.group(1)}"
    return s


__all__ = ["normalize_league_key"]


