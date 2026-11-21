"""Ekran "Ogrzewanie": termostaty grzejników + ogrzewanie podłogowe (bez wykresów i baterii).

Konfiguracja: settings.json -> entities.heating (wzór: settings.example.json).
Termostat może mieć "temperature_sensor": temperatura w pomieszczeniu jest wtedy brana
z tego czujnika zamiast z głowicy (np. głowica bez własnego pomiaru).
Odczyt: wszystkie encje jednym zapytaniem co REFRESH_SECONDS, tylko gdy ekran widoczny.
Sterowanie (usługi HA):
  - temperatura zadana: climate.set_temperature (kliknięcia +/- zbierane przez
    SEND_DELAY s i wysyłane raz - jak w HA),
  - termostat wł./wył.: climate.set_hvac_mode heat/off,
  - strefy, pompa, główny przełącznik: switch.turn_on / switch.turn_off.
"""
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import DictProperty, StringProperty
from kivy.uix.screenmanager import Screen

from kiosk import pl
from kiosk.ui import make

REFRESH_SECONDS = 10
SEND_DELAY = 1.5           # s po ostatnim +/- zanim temperatura pójdzie do HA
HOLD_AFTER_SEND = 6        # s ignorowania odczytów temperatury zadanej po wysłaniu

CLIMATE_ATTRS = ["current_temperature", "temperature", "hvac_action", "preset_mode",
                 "min_temp", "max_temp", "target_temp_step"]
OTHER_ATTRS = ["unit_of_measurement", "finishes_at", "remaining"]

ACTIONS = {"heating": "grzeje", "idle": "bezczynny", "off": "wyłączony", "preheating": "nagrzewa"}
PRESETS = {"away": "poza domem", "eco": "eko", "sleep": "sen", "comfort": "komfort",
           "home": "w domu", "boost": "boost", "activity": "aktywność"}


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class HeatingScreen(Screen):
    config = DictProperty({})
    title = StringProperty("Ogrzewanie")
    summary = StringProperty("")
    status = StringProperty("")
    timer_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._thermostats = {}      # entity_id -> karta
        self._temp_sensor = {}      # entity_id termostatu -> czujnik temperatury w pomieszczeniu
        self._switches = {}         # entity_id -> kafelek
        self._data = {}
        self._pending = {}          # entity_id -> temperatura czekająca na wysłanie
        self._hold_until = {}       # entity_id -> czas, do kiedy ignorować odczyt zadanej
        self._send_events = {}
        self._event = None
        self._busy = False
        self._timer_finishes = None

    # --- budowa z konfiguracji -------------------------------------------------------
    def build(self, config: dict):
        self.config = config or {}
        self.title = self.config.get("title", "Ogrzewanie")
        box = self.ids.thermostats
        box.clear_widgets()
        self._thermostats.clear()
        self._temp_sensor = {t["entity_id"]: t["temperature_sensor"]
                             for t in self.config.get("thermostats", []) if t.get("temperature_sensor")}
        for t in self.config.get("thermostats", []):
            card = make("ThermostatCard", name=t.get("name", t["entity_id"]))
            eid = t["entity_id"]
            card.ids.minus.bind(on_release=lambda _b, e=eid: self.change_target(e, -1))
            card.ids.plus.bind(on_release=lambda _b, e=eid: self.change_target(e, +1))
            card.ids.power.bind(on_release=lambda _b, e=eid: self.toggle_hvac(e))
            box.add_widget(card)
            self._thermostats[eid] = card

        floor = self.config.get("floor", {})
        self._switches.clear()
        # pompa: tylko podgląd stanu (readonly w heating.kv), bez przełączania
        for key, holder, name, icon in (("switch", "main_switch", "Główny przełącznik", "power"),
                                        ("pump", "pump_switch", "Pompa", "pump")):
            tile = self.ids[holder]
            tile.name, tile.icon = name, icon
            if floor.get(key):
                if not tile.readonly:
                    tile.bind(on_release=lambda _t, e=floor[key]: self.toggle_switch(e))
                self._switches[floor[key]] = tile
        zones = self.ids.zones
        zones.clear_widgets()
        for z in floor.get("zones", []):
            tile = make("SwitchTile", name=z.get("name", z["entity_id"]), icon="heating-coil")
            tile.bind(on_release=lambda _t, e=z["entity_id"]: self.toggle_switch(e))
            zones.add_widget(tile)
            self._switches[z["entity_id"]] = tile

    def _entity_ids(self):
        floor = self.config.get("floor", {})
        ids = list(self._thermostats) + list(self._temp_sensor.values()) + list(self._switches)
        ids += [floor.get(k) for k in ("pump_timer", "power", "energy") if floor.get(k)]
        ids += [e for e in self.config.get("summary", []) if e not in ids]
        return list(dict.fromkeys(ids))

    # --- odświeżanie ----------------------------------------------------------------
    def on_enter(self, *_):
        self.refresh()
        self._event = Clock.schedule_interval(self._tick, 1)
        self._tick_count = 0

    def on_leave(self, *_):
        if self._event:
            self._event.cancel()
            self._event = None

    def _tick(self, _dt):
        self._tick_count += 1
        self._update_timer()
        if self._tick_count % REFRESH_SECONDS == 0:
            self.refresh()

    def refresh(self):
        if self._busy or not self.config:
            return
        self._busy = True
        App.get_running_app().fetch_entities(self._entity_ids(), CLIMATE_ATTRS + OTHER_ATTRS,
                                             self._on_data)

    def _on_data(self, data, error):
        self._busy = False
        if error and not data:
            self.status = f"Brak danych z HA: {error}"
            return
        self.status = ""
        self._data.update(data or {})
        now = datetime.now().timestamp()
        for eid, card in self._thermostats.items():
            self._render_thermostat(eid, card, now)
        for eid, tile in self._switches.items():
            st = self._data.get(eid, {}).get("state")
            tile.on = st == "on"
            tile.sub = {"on": "włączone", "off": "wyłączone"}.get(st, "niedostępne")
        floor = self.config.get("floor", {})
        timer = self._data.get(floor.get("pump_timer"), {})
        self._timer_finishes = None
        if timer.get("state") == "active" and timer.get("attributes", {}).get("finishes_at"):
            try:
                self._timer_finishes = datetime.fromisoformat(
                    timer["attributes"]["finishes_at"].replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        self._update_timer(timer.get("state"))
        parts = []
        for eid in self.config.get("summary", []):
            d = self._data.get(eid, {})
            unit = d.get("attributes", {}).get("unit_of_measurement") or ""
            parts.append(f"{pl.num(to_float(d.get('state')), 2)} {unit}".strip())
        self.summary = "   ·   ".join(parts)

    def _update_timer(self, state=None):
        if not self.config.get("floor", {}).get("pump_timer"):
            self.timer_text = ""
            return
        if self._timer_finishes:
            left = max(0, int(self._timer_finishes - datetime.now().timestamp()))
            self.timer_text = f"Opóźnienie pompy: {left // 60}:{left % 60:02d}"
        elif state is not None:
            self.timer_text = "Opóźnienie pompy: nieaktywne" if state == "idle" else ""

    def _render_thermostat(self, eid, card, now):
        d = self._data.get(eid, {})
        a = d.get("attributes", {})
        mode = d.get("state")
        card.mode = mode or ""
        sensor = self._temp_sensor.get(eid)
        current = (to_float(self._data.get(sensor, {}).get("state")) if sensor
                   else to_float(a.get("current_temperature")))
        card.current = pl.fixed(current, 1)
        if eid not in self._pending and now >= self._hold_until.get(eid, 0):
            card.target_value = to_float(a.get("temperature")) or 0
        card.target = pl.fixed(card.target_value, 1)
        card.step = to_float(a.get("target_temp_step")) or 0.5
        card.min_temp = to_float(a.get("min_temp")) or 5
        card.max_temp = to_float(a.get("max_temp")) or 30
        action = a.get("hvac_action") or ("off" if mode == "off" else None)
        card.heating = action in ("heating", "preheating")
        bits = [ACTIONS.get(action, action or ("wyłączony" if mode == "off" else ""))]
        if a.get("preset_mode") and a.get("preset_mode") != "none":
            bits.append(PRESETS.get(a["preset_mode"], a["preset_mode"]))
        if mode == "unavailable":
            bits = ["niedostępny"]
        card.info = "  ·  ".join(b for b in bits if b)

    # --- sterowanie -----------------------------------------------------------------
    def change_target(self, eid, direction):
        card = self._thermostats[eid]
        if card.mode in ("off", "unavailable", ""):
            return
        value = round((card.target_value + direction * card.step) / card.step) * card.step
        value = max(card.min_temp, min(card.max_temp, value))
        card.target_value = value
        card.target = pl.fixed(value, 1)
        self._pending[eid] = value
        if eid in self._send_events:
            self._send_events[eid].cancel()
        self._send_events[eid] = Clock.schedule_once(lambda _dt: self._send_target(eid), SEND_DELAY)

    def _send_target(self, eid):
        value = self._pending.pop(eid, None)
        if value is None:
            return
        self._hold_until[eid] = datetime.now().timestamp() + HOLD_AFTER_SEND
        self._call("climate", "set_temperature", {"entity_id": eid, "temperature": value})

    def toggle_hvac(self, eid):
        card = self._thermostats[eid]
        new_mode = "off" if card.mode == "heat" else "heat"
        card.mode = new_mode                              # od razu na ekranie
        self._call("climate", "set_hvac_mode", {"entity_id": eid, "hvac_mode": new_mode})

    def toggle_switch(self, eid):
        tile = self._switches[eid]
        if tile.readonly:
            return
        service = "turn_off" if tile.on else "turn_on"
        tile.on = not tile.on                             # od razu na ekranie
        self._call("switch", service, {"entity_id": eid})

    def _call(self, domain, service, data):
        def done(_result, error):
            if error:
                self.status = f"Nie udało się: {domain}.{service} ({error})"
            Clock.schedule_once(lambda _dt: self.refresh(), 1.5)
        App.get_running_app().call_service(domain, service, data, done)
