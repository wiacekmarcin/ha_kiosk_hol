"""Kolorowe ikony pogody Meteocons (Bas Milius, licencja MIT - assets/weather/LICENSE).

PNG wygenerowane ze statycznych SVG pakietu @bybas/weather-icons@2.0.0
(design/fill/export) w rozdzielczości 256x256.
"""
from datetime import datetime
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "weather"

# stan pogody HA -> (ikona dzienna, ikona nocna)
_MAP = {
    "clear-night": ("clear-night", "clear-night"),
    "cloudy": ("cloudy", "cloudy"),
    "exceptional": ("not-available", "not-available"),
    "fog": ("fog", "fog"),
    "hail": ("hail", "hail"),
    "lightning": ("thunderstorms", "thunderstorms"),
    "lightning-rainy": ("thunderstorms-rain", "thunderstorms-rain"),
    "partlycloudy": ("partly-cloudy-day", "partly-cloudy-night"),
    "pouring": ("rain", "rain"),
    "rainy": ("rain", "rain"),
    "snowy": ("snow", "snow"),
    "snowy-rainy": ("sleet", "sleet"),
    "sunny": ("clear-day", "clear-night"),
    "windy": ("wind", "wind"),
    "windy-variant": ("wind", "wind"),
}


def path(condition: str, night: bool = False) -> str:
    if not condition:
        return ""
    day_icon, night_icon = _MAP.get(condition, ("not-available", "not-available"))
    return str(ICON_DIR / f"{night_icon if night else day_icon}.png")


def is_night(when: datetime, sunrise: str, sunset: str) -> bool:
    """Noc = przed wschodem lub po zachodzie (godziny 'HH:MM' z sun.sun)."""
    try:
        hm = when.strftime("%H:%M")
        return hm < sunrise or hm >= sunset
    except (TypeError, ValueError):
        return False
