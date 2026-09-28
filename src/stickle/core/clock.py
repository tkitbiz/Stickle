"""Timestamps are stored as ISO 8601 in UTC, whatever the user's locale."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

type Clock = Callable[[], str]


def _format(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def utc_now() -> str:
    """For example 2026-09-26T03:41:07.123Z (millisecond precision, sortable as text)."""
    return _format(datetime.now(UTC))


def days_before(stamp: str, days: int) -> str:
    """The timestamp that many days before another, in the same form."""
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return _format(moment - timedelta(days=days))
