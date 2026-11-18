"""Time helpers for the UI: parsing the picked time, quick presets, and readable countdowns. No tkinter here."""

from __future__ import annotations

from datetime import datetime, timedelta


def humanize_delta(delta: timedelta) -> str:
    """'3 h 20 min', '45 min', 'less than a minute', '2 days 4 h'."""
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "less than a minute"
    if minutes < 60:
        return f"{minutes} min"
    hours, mins = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {mins:02d} min" if mins else f"{hours} h"
    days, hours = divmod(hours, 24)
    return f"{days} days {hours} h" if hours else f"{days} days"


def next_at(hour: int, minute: int, now: datetime) -> datetime:
    """The next time the clock shows hour:minute, strictly after now."""
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return candidate if candidate > now else candidate + timedelta(days=1)


def presets(now: datetime) -> list[tuple[str, datetime]]:
    in_an_hour = (now + timedelta(hours=1, seconds=59)).replace(second=0, microsecond=0)
    return [("In 1 hour", in_an_hour), ("Next 02:00", next_at(2, 0, now)), ("Next 08:00", next_at(8, 0, now))]


def parse_when(date_text: str, hour_text: str, minute_text: str) -> datetime:
    """Combine the date and time fields; raises ValueError with a message fit to show the user."""
    try:
        day = datetime.strptime(date_text.strip(), "%Y-%m-%d")
    except ValueError:
        raise ValueError("Enter the date as YYYY-MM-DD, for example 2026-11-20.") from None
    try:
        hour, minute = int(hour_text), int(minute_text)
    except ValueError:
        raise ValueError("Enter the time as hours (0-23) and minutes (0-59).") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Enter the time as hours (0-23) and minutes (0-59).")
    return day.replace(hour=hour, minute=minute)


def describe(when: datetime, now: datetime) -> str:
    """'Thu 19 Nov at 02:00 (in 8 h 12 min)'."""
    return f"{when:%a %d %b} at {when:%H:%M} (in {humanize_delta(when - now)})"
