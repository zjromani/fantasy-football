from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import time
from datetime import date


def deterministic_delay(secret: str, job: str, maximum_seconds: int) -> int:
    week = date.today().isocalendar()
    message = f"{week.year}-{week.week}-{job}".encode()
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()
    return int.from_bytes(digest[:4], "big") % (maximum_seconds + 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("job")
    parser.add_argument("--maximum-seconds", type=int, default=900)
    parser.add_argument("--no-sleep", action="store_true")
    args = parser.parse_args()
    delay = deterministic_delay(
        os.environ["SCHEDULE_JITTER_SECRET"],
        args.job,
        args.maximum_seconds,
    )
    print(delay)
    if not args.no_sleep:
        time.sleep(delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
