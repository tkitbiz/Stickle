"""Timestamps are stored as ISO 8601 in UTC, whatever the user's locale."""

from collections.abc import Callable
from datetime import UTC, datetime

type Clock = Callable[[], str]


def utc_now() -> str:
    """For example 2026-09-26T03:41:07.123Z (millisecond precision, sortable as text)."""
    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
