"""
market_calendar.py — NYSE market hours and earnings blackout detection.

All times are handled in UTC. NYSE is UTC-5 (EST) or UTC-4 (EDT).
Market hours in CET (UTC+1): 15:30–22:00 (winter) / 14:30–21:00 (summer / DST).
We use a simple UTC-based check: NYSE open = 13:30–20:00 UTC.
"""

import logging
from datetime import datetime, time, date, timedelta
from typing import Optional

logger = logging.getLogger("MarketCalendar")

# NYSE regular session in UTC (works year-round, slightly conservative)
NYSE_OPEN_UTC = time(13, 30)   # 09:30 ET = 13:30 UTC (EST offset; EDT = 13:30 still works)
NYSE_CLOSE_UTC = time(20, 0)   # 16:00 ET = 20:00 UTC

# NYSE holidays 2025 (add 2026 when needed)
NYSE_HOLIDAYS_2025 = {
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 20),  # Martin Luther King Jr. Day
    date(2025, 2, 17),  # Presidents' Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),   # Independence Day
    date(2025, 9, 1),   # Labor Day
    date(2025, 11, 27), # Thanksgiving Day
    date(2025, 12, 25), # Christmas Day
}

NYSE_HOLIDAYS_2026 = {
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # Martin Luther King Jr. Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving Day
    date(2026, 12, 25), # Christmas Day
}

NYSE_HOLIDAYS = NYSE_HOLIDAYS_2025 | NYSE_HOLIDAYS_2026


def is_market_open(now: Optional[datetime] = None) -> bool:
    """Return True if NYSE is currently open (UTC-based check)."""
    if now is None:
        now = datetime.utcnow()
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    if now.date() in NYSE_HOLIDAYS:
        return False
    current_time = now.time().replace(second=0, microsecond=0)
    return NYSE_OPEN_UTC <= current_time < NYSE_CLOSE_UTC


def is_trading_day(d: Optional[date] = None) -> bool:
    """Return True if d is a NYSE trading day (weekday, not holiday)."""
    if d is None:
        d = datetime.utcnow().date()
    if d.weekday() >= 5:
        return False
    return d not in NYSE_HOLIDAYS


def is_sunday() -> bool:
    return datetime.utcnow().weekday() == 6


def minutes_until_market_open(now: Optional[datetime] = None) -> int:
    """Return minutes until NYSE opens. 0 if already open."""
    if now is None:
        now = datetime.utcnow()
    if is_market_open(now):
        return 0
    # Find next trading day open
    check = now.replace(hour=NYSE_OPEN_UTC.hour, minute=NYSE_OPEN_UTC.minute, second=0, microsecond=0)
    if now.time() >= NYSE_CLOSE_UTC:
        check += timedelta(days=1)
    # Advance past weekends and holidays
    while check.weekday() >= 5 or check.date() in NYSE_HOLIDAYS:
        check += timedelta(days=1)
        check = check.replace(hour=NYSE_OPEN_UTC.hour, minute=NYSE_OPEN_UTC.minute)
    delta = check - now
    return max(0, int(delta.total_seconds() / 60))


def is_near_market_open(window_minutes: int = 35, now: Optional[datetime] = None) -> bool:
    """Return True if market opens within window_minutes (for pre-market screening)."""
    mins = minutes_until_market_open(now)
    return 0 < mins <= window_minutes


def is_daily_screening_time(now: Optional[datetime] = None) -> bool:
    """
    Return True once per day around 13:00 UTC (14:00 CET winter / 15:00 CET summer),
    which is ~30 min before NYSE open — the daily full-universe screening window.
    """
    if now is None:
        now = datetime.utcnow()
    if not is_trading_day(now.date()):
        return False
    # 13:00–13:15 UTC = daily screening window
    return time(13, 0) <= now.time() < time(13, 15)
