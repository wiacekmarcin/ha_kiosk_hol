"""Formatowanie dat i liczb po polsku (bez zależności od locale systemu)."""
from datetime import date, datetime

DAYS = ["poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota", "niedziela"]
DAYS_SHORT = ["pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."]
MONTHS_GEN = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca",
              "sierpnia", "września", "października", "listopada", "grudnia"]
MONTHS_NOM = ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec", "Lipiec",
              "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"]
MONTHS_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź",
                "lis", "gru"]

# Stany pogody z Home Assistant -> opis jak w polskim HA
# (ikony: kiosk/weather_icons.py)
WEATHER = {
    "clear-night": "pogodna noc",
    "cloudy": "pochmurno",
    "exceptional": "warunki nadzwyczajne",
    "fog": "mgła",
    "hail": "grad",
    "lightning": "burza",
    "lightning-rainy": "burza z deszczem",
    "partlycloudy": "częściowe zachmurzenie",
    "pouring": "ulewa",
    "rainy": "deszczowo",
    "snowy": "śnieg",
    "snowy-rainy": "śnieg z deszczem",
    "sunny": "słonecznie",
    "windy": "wietrznie",
    "windy-variant": "wietrznie, pochmurno",
}


_SORT = str.maketrans({"ą": "a~", "ć": "c~", "ę": "e~", "ł": "l~", "ń": "n~", "ó": "o~",
                       "ś": "s~", "ź": "z~", "ż": "z~~"})


def sort_key(text: str) -> str:
    """Klucz sortowania wg polskiego alfabetu (Ł po L, Ż po Z itd.)."""
    return text.lower().translate(_SORT)


def num(value, decimals=1) -> str:
    """9.6 -> '9,6';  10.0 -> '10';  None -> '—'."""
    if value is None:
        return "—"
    text = f"{value:.{decimals}f}".replace(".", ",")
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    return text


def fixed(value, decimals=2) -> str:
    """Stała liczba miejsc po przecinku (jak w HA): 239.2 -> '239,20';  None -> '—'."""
    if value is None:
        return "—"
    return f"{value:.{decimals}f}".replace(".", ",")


def long_date(d: date) -> str:
    """'środa, 18 listopada 2026'"""
    return f"{DAYS[d.weekday()]}, {d.day} {MONTHS_GEN[d.month - 1]} {d.year}"


def full_date(d: date) -> str:
    """'20 listopada 2026'"""
    return f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year}"


def date_range(start: date, end: date) -> str:
    """'18–24 lis 2026' albo '28 lis – 4 gru 2026'"""
    if start.month == end.month and start.year == end.year:
        return f"{start.day}–{end.day} {MONTHS_SHORT[end.month - 1]} {end.year}"
    if start.year == end.year:
        return (f"{start.day} {MONTHS_SHORT[start.month - 1]} – "
                f"{end.day} {MONTHS_SHORT[end.month - 1]} {end.year}")
    return (f"{start.day} {MONTHS_SHORT[start.month - 1]} {start.year} – "
            f"{end.day} {MONTHS_SHORT[end.month - 1]} {end.year}")


WIND_DIRS = ["płn.", "płn.-płn.-wsch.", "płn.-wsch.", "wsch.-płn.-wsch.",
             "wsch.", "wsch.-płd.-wsch.", "płd.-wsch.", "płd.-płd.-wsch.",
             "płd.", "płd.-płd.-zach.", "płd.-zach.", "zach.-płd.-zach.",
             "zach.", "zach.-płn.-zach.", "płn.-zach.", "płn.-płn.-zach."]


def wind_dir(bearing) -> str:
    """Kierunek, z którego wieje wiatr: 227.4 -> 'płd.-zach.'"""
    if bearing is None:
        return ""
    return WIND_DIRS[int((float(bearing) % 360) / 22.5 + 0.5) % 16]


def plural(n: int, one: str, few: str, many: str) -> str:
    """plural(4, 'godzina', 'godziny', 'godzin') -> 'godziny'"""
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def ago(when: datetime, now: datetime = None) -> str:
    """'przed chwilą', '5 minut temu', '4 godziny temu', '2 dni temu'"""
    if when is None:
        return ""
    seconds = ((now or datetime.now()) - when).total_seconds()
    if seconds < 60:
        return "przed chwilą"
    for size, forms in ((86400, ("dzień", "dni", "dni")),
                        (3600, ("godzinę", "godziny", "godzin")),
                        (60, ("minutę", "minuty", "minut"))):
        if seconds >= size:
            n = int(seconds // size)
            return f"{n} {plural(n, *forms)} temu"
