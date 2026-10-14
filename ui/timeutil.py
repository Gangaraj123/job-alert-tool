"""All timestamps are stored in UTC (db._now()) — this converts them to IST
for display, since that's what the raw "...Z" strings looked like otherwise."""
from __future__ import annotations

import datetime as _dt

IST_OFFSET = _dt.timedelta(hours=5, minutes=30)


def to_ist(utc_str: str | None) -> str:
    if not utc_str:
        return "—"
    try:
        dt = _dt.datetime.strptime(utc_str[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        try:
            dt = _dt.datetime.strptime(utc_str[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return utc_str
    ist = dt + IST_OFFSET
    return ist.strftime("%d %b %Y, %I:%M %p IST")
