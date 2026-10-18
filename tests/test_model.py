from datetime import UTC, datetime

from custom_components.babble.model import (
    current_sleep_seconds,
    feed_overdue,
    minutes,
    nappy_type,
    nursing_side_active,
    nursing_side_seconds,
    nursing_turn_on,
    parse_time,
)

from .conftest import snapshot

AS_OF = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


def at(minute: int) -> datetime:
    return AS_OF.replace(minute=minute)


def test_parse_time_reads_iso_with_z():
    assert parse_time("2026-10-06T12:00:00.000Z") == AS_OF
    assert parse_time(None) is None


def test_running_sleep_keeps_counting_after_the_snapshot():
    assert current_sleep_seconds(snapshot(), at(15)) == 3600 + 15 * 60


def test_paused_sleep_stops_counting():
    paused = snapshot(sleep={"state": "paused", "asleep_s": 1800})
    assert current_sleep_seconds(paused, at(15)) == 1800


def test_no_sleep_has_no_length():
    assert current_sleep_seconds(snapshot(sleep={"state": "none"}), at(0)) is None
    assert minutes(None) is None
    assert minutes(119) == 1


def test_only_the_active_side_keeps_counting():
    feeding = snapshot(nursing={"state": "active", "active_side": "right", "left_s": 600, "right_s": 60})
    assert nursing_side_seconds(feeding, at(2), "right") == 60 + 120
    assert nursing_side_seconds(feeding, at(2), "left") == 600


def test_feed_is_overdue_once_due_unless_quiet():
    assert not feed_overdue(snapshot(), datetime(2026, 10, 6, 12, 59, tzinfo=UTC))
    assert feed_overdue(snapshot(), datetime(2026, 10, 6, 13, 0, tzinfo=UTC))
    assert not feed_overdue(snapshot(feed={"quiet": True}), datetime(2026, 10, 6, 14, 0, tzinfo=UTC))
    assert not feed_overdue(snapshot(feed={"next_due": None}), datetime(2026, 10, 6, 14, 0, tzinfo=UTC))


def test_nappy_type():
    assert nappy_type({"wet": True, "dirty": True}) == "both"
    assert nappy_type({"wet": False, "dirty": True}) == "dirty"
    assert nappy_type({"wet": True, "dirty": False}) == "wet"
    assert nappy_type({"wet": False, "dirty": False}) == "dry"


def test_turning_a_side_on_starts_resumes_or_switches():
    assert nursing_turn_on(snapshot(), "right") == ("start_nursing", {"side": "right"})
    paused = snapshot(nursing={"state": "paused", "active_side": None})
    assert nursing_turn_on(paused, "left") == ("resume_nursing", {"side": "left"})
    feeding_left = snapshot(nursing={"state": "active", "active_side": "left"})
    assert nursing_turn_on(feeding_left, "right") == ("switch_nursing_side", {})
    assert nursing_turn_on(feeding_left, "left") is None
    assert nursing_side_active(feeding_left, "left")
    assert not nursing_side_active(feeding_left, "right")
