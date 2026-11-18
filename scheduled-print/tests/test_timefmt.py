import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import timefmt  # noqa: E402

NOW = datetime(2026, 11, 18, 17, 30, 15)


@pytest.mark.parametrize(
    "delta, text",
    [
        (timedelta(seconds=30), "less than a minute"),
        (timedelta(minutes=45), "45 min"),
        (timedelta(hours=3, minutes=20), "3 h 20 min"),
        (timedelta(hours=3), "3 h"),
        (timedelta(hours=50), "2 days 2 h"),
        (timedelta(hours=48), "2 days"),
    ],
)
def test_humanize_delta(delta, text):
    assert timefmt.humanize_delta(delta) == text


def test_next_at_rolls_to_tomorrow_when_passed():
    assert timefmt.next_at(2, 0, NOW) == datetime(2026, 11, 19, 2, 0)
    assert timefmt.next_at(22, 0, NOW) == datetime(2026, 11, 18, 22, 0)
    assert timefmt.next_at(17, 30, NOW) == datetime(2026, 11, 19, 17, 30)  # equal to now is not "next"


def test_presets_are_in_the_future_and_whole_minutes():
    items = timefmt.presets(NOW)
    assert [label for label, _ in items] == ["In 1 hour", "Next 02:00", "Next 08:00"]
    for _, when in items:
        assert when > NOW and when.second == 0


def test_parse_when_ok_and_errors():
    assert timefmt.parse_when(" 2026-11-20 ", "2", "05") == datetime(2026, 11, 20, 2, 5)
    for date, h, m in [("20-11-2026", "1", "0"), ("2026-02-30", "1", "0"), ("2026-11-20", "24", "0"), ("2026-11-20", "x", "0"), ("2026-11-20", "1", "60")]:
        with pytest.raises(ValueError):
            timefmt.parse_when(date, h, m)


def test_describe():
    assert timefmt.describe(datetime(2026, 11, 19, 2, 0), NOW) == "Thu 19 Nov at 02:00 (in 8 h 29 min)"
