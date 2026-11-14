"""Localized Discord schedule; future dates are estimates, not confirmations."""
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo

JST = ZoneInfo('Asia/Tokyo')
EASTERN = ZoneInfo('America/New_York')

def discord_time(value, style='F'):
    return f'<t:{int(value.timestamp())}:{style}>'

def next_jp_estimate(last_jp, now=None):
    now = now or datetime.now(timezone.utc)
    if not last_jp:
        return None
    candidate = last_jp.astimezone(JST) + timedelta(days=14)
    return candidate if candidate > now else None

def english_window(jp_release):
    jp = jp_release.astimezone(JST)
    eastern = jp_release.astimezone(EASTERN)
    if jp.weekday() == 5 and jp.hour == 12 and jp.minute == 0:
        days = (1 - eastern.weekday()) % 7 or 7
        target = datetime.combine(eastern.date() + timedelta(days=days), time(22), EASTERN)
        return target, target, True
    dates = [eastern.date() + timedelta(days=d) for d in range(1, 5)]
    dates = [d for d in dates if d.weekday() < 5]
    if not dates:
        return None, None, False
    # Irregular English releases have no reliably known hour.
    return datetime.combine(dates[0], time.min, EASTERN), datetime.combine(dates[-1], time.max, EASTERN), False

def schedule_text(last_jp=None, last_en=None, now=None, english_hour_verified=False):
    now = now or datetime.now(timezone.utc)
    lines = ['**Choujin X — Chapter Release Schedule**']
    lines.append('Latest tracked Japanese release: ' + (discord_time(last_jp) if last_jp else '**Not yet verified**'))
    if last_en:
        if english_hour_verified:
            lines.append('Latest tracked English release: ' + discord_time(last_en))
        else:
            # Official VIZ listing verifies the date, not the hour.
            lines.append('Latest tracked English release: ' + last_en.astimezone(EASTERN).strftime('%B %d, %Y') + ' (date confirmed; time unverified)')
    else:
        lines.append('Latest tracked English release: **Not yet verified**')
    jp = next_jp_estimate(last_jp, now)
    lines.append('Next Japanese chapter (Estimated): ' + (f'{discord_time(jp)} ({discord_time(jp, "R")})' if jp else '**TBD**'))
    if jp:
        start, end, normal = english_window(jp)
        if normal and start > now:
            lines.append(f'Next English chapter (Estimated): {discord_time(start)} ({discord_time(start, "R")})')
        elif start and end and end > now:
            lines.append(f'Next English chapter (Estimated window): {start.astimezone(EASTERN):%b %d}–{end.astimezone(EASTERN):%b %d, %Y} (Eastern dates; time TBD)')
        else:
            lines.append('Next English chapter (Estimated): **TBD**')
    else:
        lines.append('Next English chapter (Estimated): **TBD**')
    return '\n'.join(lines)
