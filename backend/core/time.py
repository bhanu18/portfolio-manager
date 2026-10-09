"""Time helpers for the existing timezone-naive MySQL UTC columns."""

from datetime import UTC, datetime


def db_utc_now() -> datetime:
    """Read an aware UTC clock, then remove tzinfo for MySQL DATETIME storage.

    Database values are naive UTC on read; comparisons must use the same form.
    API serializers add the UTC offset when exposing these values to clients.
    """
    return datetime.now(UTC).replace(tzinfo=None)
