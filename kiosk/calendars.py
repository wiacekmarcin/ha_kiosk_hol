"""Kalendarze Home Assistanta: wygląd (ikona, kolor), święta i pomocnicze funkcje dat.

Rodzaj kalendarza rozpoznawany po entity_id (słowa kluczowe w KINDS); kolejność ma
znaczenie - pierwsze dopasowanie wygrywa. Kalendarz świąt (np. calendar.swieta_w_polsce)
wyróżnia dni na czerwono na kartce i w tabeli miesiąca.
"""
from datetime import date, datetime, time, timedelta

# słowo w entity_id -> (rodzaj, ikona MDI, kolor RGBA)
KINDS = [
    (("swieta", "holiday", "swiat"), "święta", "church", (0.96, 0.33, 0.30, 1)),
    (("birthday", "urodzin"), "urodziny", "cake-variant", (0.95, 0.45, 0.70, 1)),
    (("dzieci", "child", "kids"), "dzieci", "heart", (0.70, 0.50, 0.98, 1)),
    (("famil", "rodzin", "dom"), "rodzina", "home", (0.40, 0.80, 0.45, 1)),
    (("gmail", "google", "outlook"), "konto", "email", (0.30, 0.70, 0.98, 1)),
    (("workday", "prac"), "dni pracujące", "briefcase", (0.58, 0.61, 0.66, 1)),
]
DEFAULT_COLORS = [(0.98, 0.76, 0.25, 1), (0.35, 0.85, 0.85, 1), (0.98, 0.58, 0.20, 1)]


def style(entity_id: str):
    """(rodzaj, ikona, kolor) kalendarza."""
    eid = (entity_id or "").lower()
    for keys, kind, icon, color in KINDS:
        if any(k in eid for k in keys):
            return kind, icon, color
    return "kalendarz", "calendar", DEFAULT_COLORS[sum(map(ord, eid)) % len(DEFAULT_COLORS)]


def is_holiday_calendar(entity_id: str) -> bool:
    return style(entity_id)[0] == "święta"


def hex_color(rgba) -> str:
    """(r, g, b, a) 0..1 -> '#rrggbb' (dla znaczników [color] w tekście)."""
    return "#" + "".join(f"{int(c * 255):02x}" for c in rgba[:3])


def events_on(events: list, day: date) -> list:
    """Wydarzenia trwające w danym dniu (wielodniowe też), posortowane: całodniowe, potem godziny.
    Koniec wydarzenia całodniowego jest wyłączny (HA: end = następny dzień)."""
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)
    out = [e for e in events if e["start"] < end and e["end"] > start
           or (e["start"] == e["end"] and e["start"].date() == day)]
    return sorted(out, key=lambda e: (not e.get("all_day"), e["start"]))


def time_text(ev: dict) -> str:
    if ev.get("all_day"):
        days = (ev["end"].date() - ev["start"].date()).days
        return "cały dzień" if days <= 1 else f"{days} dni"
    if ev["start"].date() != ev["end"].date():
        return f"{ev['start']:%d.%m %H:%M} - {ev['end']:%d.%m %H:%M}"
    return f"{ev['start']:%H:%M} - {ev['end']:%H:%M}"


def month_grid(year: int, month: int) -> list:
    """42 dni (6 tygodni od poniedziałku) obejmujące miesiąc."""
    first = date(year, month, 1)
    start = first - timedelta(days=first.weekday())
    return [start + timedelta(days=i) for i in range(42)]


def shift_month(year: int, month: int, delta: int):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1
