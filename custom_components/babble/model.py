from __future__ import annotations

from datetime import datetime
from typing import Any

Snapshot = dict[str, Any]


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _since_snapshot(snapshot: Snapshot, now: datetime) -> float:
    as_of = parse_time(snapshot["as_of"])
    return max(0.0, (now - as_of).total_seconds()) if as_of else 0.0


def current_sleep_seconds(snapshot: Snapshot, now: datetime) -> float | None:
    sleep = snapshot["sleep"]
    if sleep["state"] == "none":
        return None
    extra = _since_snapshot(snapshot, now) if sleep["state"] == "active" else 0
    return sleep["asleep_s"] + extra


def nursing_side_seconds(snapshot: Snapshot, now: datetime, side: str) -> float:
    nursing = snapshot["nursing"]
    extra = (
        _since_snapshot(snapshot, now)
        if nursing["state"] == "active" and nursing["active_side"] == side
        else 0
    )
    return nursing[f"{side}_s"] + extra


def is_asleep(snapshot: Snapshot) -> bool:
    return snapshot["sleep"]["state"] != "none"


def is_feeding(snapshot: Snapshot) -> bool:
    return snapshot["nursing"]["state"] != "none"


def feed_overdue(snapshot: Snapshot, now: datetime) -> bool:
    feed = snapshot["feed"]
    due = parse_time(feed["next_due"])
    return due is not None and not feed["quiet"] and now >= due


def nappy_type(nappy: dict[str, Any]) -> str:
    if nappy["wet"] and nappy["dirty"]:
        return "both"
    if nappy["dirty"]:
        return "dirty"
    return "wet" if nappy["wet"] else "dry"


def nursing_side_active(snapshot: Snapshot, side: str) -> bool:
    nursing = snapshot["nursing"]
    return nursing["state"] == "active" and nursing["active_side"] == side


def nursing_turn_on(snapshot: Snapshot, side: str) -> tuple[str, dict[str, Any]] | None:
    nursing = snapshot["nursing"]
    if nursing["state"] == "none":
        return "start_nursing", {"side": side}
    if nursing["state"] == "paused":
        return "resume_nursing", {"side": side}
    if nursing["active_side"] != side:
        return "switch_nursing_side", {}
    return None


def minutes(seconds: float | None) -> int | None:
    return None if seconds is None else int(seconds // 60)
