from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

MADRID_TZ = ZoneInfo("Europe/Madrid")


@dataclass(frozen=True)
class NotifyDecision:
    due: bool
    reason: str
    notify_time: str


def normalize_notify_time(value: str | None, default: str = "08:00") -> str:
    raw = (value or "").strip()
    if not raw:
        return default
    try:
        hh, mm = raw.split(":", 1)
        hour = int(hh)
        minute = int(mm)
    except Exception:
        return default
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return f"{hour:02d}:{minute:02d}"


def should_send_daily_notification(settings: dict | None, now: datetime | None = None) -> NotifyDecision:
    s = settings or {}
    notify_time_raw = (s.get("notify_time") or "").strip()
    if not notify_time_raw:
        return NotifyDecision(False, "disabled", "")

    notify_time = normalize_notify_time(notify_time_raw)
    now_madrid = (now or datetime.now(MADRID_TZ)).astimezone(MADRID_TZ)
    today = now_madrid.date().isoformat()

    if str(s.get("last_notify_date") or "").strip() == today:
        return NotifyDecision(False, "already_sent_today", notify_time)

    hh, mm = [int(x) for x in notify_time.split(":", 1)]
    if (now_madrid.hour, now_madrid.minute) < (hh, mm):
        return NotifyDecision(False, "too_early", notify_time)

    return NotifyDecision(True, "due", notify_time)
