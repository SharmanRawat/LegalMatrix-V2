"""App clock — all legal/demo-facing timestamps are Asia/Kolkata (IST).

The server box may sit in any timezone (this one is UTC+9); hard-coding IST
keeps inspection IDs, report timestamps and history consistent with the SIH
audience instead of the host's local clock.
"""
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Current wall-clock time in India (Asia/Kolkata), tz-aware."""
    return datetime.now(IST)