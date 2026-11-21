"""Ekran "Baterie": wszystkie sensory baterii z HA (device_class: battery).

Kolor ikony w menu (status całości):
  czerwony - choć jedna bateria < 30 %
  żółty    - choć jedna bateria < 60 % (i żadna < 30 %)
  zielony  - wszystkie >= 60 %
Baterie niedostępne (unavailable) są pokazywane na końcu i nie wpływają na kolor.
"""
import re

from kivy.app import App
from kivy.properties import DictProperty, ListProperty, StringProperty
from kivy.uix.screenmanager import Screen

from kiosk import pl
from kiosk.ui import make

LOW, WARN = 30, 60
COLORS = {
    "low": (0.95, 0.33, 0.30, 1),
    "warn": (0.98, 0.78, 0.20, 1),
    "ok": (0.33, 0.80, 0.45, 1),
    "unknown": (0.58, 0.61, 0.66, 1),
}


def level_status(value) -> str:
    if value is None:
        return "unknown"
    if value < LOW:
        return "low"
    if value < WARN:
        return "warn"
    return "ok"


def overall_status(batteries: list) -> str:
    levels = [b["value"] for b in batteries if b.get("value") is not None]
    if not levels:
        return "unknown"
    if min(levels) < LOW:
        return "low"
    if min(levels) < WARN:
        return "warn"
    return "ok"


def battery_icon(value) -> str:
    if value is None:
        return "battery-unknown"
    if value >= 95:
        return "battery"
    step = max(10, min(90, int(round(value / 10.0)) * 10))
    return "battery-outline" if value < 5 else f"battery-{step}"


def clean_name(name: str) -> str:
    """Nazwa urządzenia bez technicznego dopisku encji, np.
    'Jadalnia-grzejnik Jadalnia-Grzejnik_battery_level' -> 'Jadalnia-grzejnik',
    'Pracownia grzejnik Pracownia-Pracownia grzej_battery_level' -> 'Pracownia grzejnik',
    'SM-A325F Battery level' -> 'SM-A325F'."""
    original = name
    name = re.sub(r"\s+(battery level|bateria|battery|poziom baterii)$", "", name, flags=re.I)
    if re.search(r"_battery(_level)?$", name, flags=re.I):
        name = re.sub(r"_battery(_level)?$", "", name, flags=re.I)
        words = name.split()
        half = len(words) // 2
        if len(words) % 2 == 0 and half and \
                [w.lower() for w in words[:half]] == [w.lower() for w in words[half:]]:
            name = " ".join(words[:half])                 # "A B A B" -> "A B"
        else:
            # nazwa urządzenia kończy się przed pierwszym członem technicznym (z '-' lub '_')
            cut = next((i for i, w in enumerate(words) if i > 0 and ("-" in w or "_" in w)), None)
            if cut:
                name = " ".join(words[:cut])
    return name.strip() or original


class BatteryScreen(Screen):
    batteries = ListProperty([])
    names = DictProperty({})        # entity_id -> własna nazwa (settings: battery.names)
    summary = StringProperty("")
    status = StringProperty("")

    def on_enter(self, *_):
        App.get_running_app().check_batteries()

    def on_batteries(self, *_):
        grid = self.ids.grid
        grid.clear_widgets()
        known = sorted((b for b in self.batteries if b.get("value") is not None),
                       key=lambda b: b["value"])
        unknown = [b for b in self.batteries if b.get("value") is None]
        for b in known + unknown:
            st = level_status(b.get("value"))
            grid.add_widget(make(
                "BatteryTile", name=self.names.get(b["entity_id"]) or clean_name(b["name"]), icon=battery_icon(b.get("value")),
                level=(f"{pl.num(b['value'], 0)} %" if b.get("value") is not None
                       else "niedostępna"),
                tint=COLORS[st]))
        low = sum(1 for b in known if b["value"] < LOW)
        warn = sum(1 for b in known if LOW <= b["value"] < WARN)
        parts = [f"{len(self.batteries)} urządzeń"]
        if low:
            parts.append(f"{low} poniżej {LOW} %")
        if warn:
            parts.append(f"{warn} poniżej {WARN} %")
        if unknown:
            parts.append(f"{len(unknown)} niedostępne")
        self.summary = "   ·   ".join(parts)
