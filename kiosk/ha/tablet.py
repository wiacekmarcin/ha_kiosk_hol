"""Encje tabletu w Home Assistant: bateria, oświetlenie, jasność ekranu i głośność.

- sensor.tablet_kiosk_bateria (device_class battery, %) - aplikacja zapisuje stan co
  INTERVAL sekund przez POST /api/states (atrybuty: charging, temperature). Encja nie
  jest zapamiętywana przez HA - po restarcie HA wraca przy następnym zapisie.
- sensor.tablet_kiosk_oswietlenie (device_class illuminance, lx) - czujnik światła
  tabletu, zapisywany tak samo jak bateria.
- input_boolean.tablet_kiosk_jasnosc_auto - automatyczna jasność według czujnika światła.
- input_number.tablet_kiosk_jasnosc / input_number.tablet_kiosk_glosnosc (pomocnicy
  0-100 % w HA): zmiana w HA (dashboard, automatyzacja) ustawia tablet, zmiana na
  ekranie Ustawienia ustawia pomocnika.

Identyfikatory można zmienić w settings.json:
  "entities": {"tablet": {"battery": "...", "illuminance": "...", "brightness": "...",
                         "auto_brightness": "...", "volume": "..."}}
Pusty identyfikator wyłącza daną encję.
"""
import threading

from kivy.clock import Clock
from kivy.logger import Logger

from kiosk.ha.client import HAClient, HAError

INTERVAL = 30           # s - zapis baterii i odczyt pomocników
DEFAULTS = {
    "battery": "sensor.tablet_kiosk_bateria",
    "illuminance": "sensor.tablet_kiosk_oswietlenie",
    "auto_brightness": "input_boolean.tablet_kiosk_jasnosc_auto",
    "brightness": "input_number.tablet_kiosk_jasnosc",
    # moc gniazdka, z którego ładuje się tablet (Ładowarka do telefonu 2) - tylko odczyt
    "charger_power": "sensor.charger_2_power",
    "volume": "input_number.tablet_kiosk_glosnosc",
}


class TabletSync:
    def __init__(self, settings: dict, on_remote):
        """on_remote(kind, value) - wołane w wątku UI, gdy pomocnik zmienił się w HA."""
        cfg = dict(DEFAULTS)
        cfg.update(settings.get("entities", {}).get("tablet", {}))
        self.ids = cfg
        self.settings = settings
        self.on_remote = on_remote
        self._seen = {}             # ostatnia wartość pomocnika znana z HA
        self._pending = {}          # wartości z aplikacji do wysłania do HA
        self._battery = None
        self._lux = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ha-tablet", daemon=True)

    def start(self, brightness: int, volume: int, auto_brightness: bool):
        """Przy starcie wartości z tabletu trafiają do HA (aplikacja jest źródłem prawdy)."""
        self.push("brightness", brightness)
        self.push("volume", volume)
        self.push("auto_brightness", auto_brightness)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def set_battery(self, info):
        with self._lock:
            self._battery = info
        self._wake.set()

    def set_light(self, lux):
        with self._lock:
            self._lux = lux

    def push(self, kind: str, value):
        with self._lock:
            self._pending[kind] = bool(value) if kind == "auto_brightness" else int(value)
        self._wake.set()

    # --- wątek w tle ----------------------------------------------------------------
    def _run(self):
        client = HAClient(self.settings["url"], self.settings["token"])
        while not self._stop.is_set():
            self._wake.clear()
            self._cycle(client)
            self._wake.wait(INTERVAL)

    def _cycle(self, client):
        with self._lock:
            pending, self._pending = self._pending, {}
            battery = self._battery
            lux = self._lux
        for kind, value in pending.items():
            eid = self.ids.get(kind)
            if not eid:
                continue
            try:
                if kind == "auto_brightness":
                    client.call_service("input_boolean", "turn_on" if value else "turn_off",
                                        {"entity_id": eid})
                    self._seen[kind] = value
                else:
                    client.call_service("input_number", "set_value",
                                        {"entity_id": eid, "value": value})
                    self._seen[kind] = float(value)
            except HAError as e:
                Logger.warning(f"HA: tablet {kind} -> {eid}: {e}")
        if battery and self.ids.get("battery"):
            try:
                client.set_state(self.ids["battery"], battery["level"], {
                    "friendly_name": "Tablet kiosk bateria",
                    "unit_of_measurement": "%",
                    "device_class": "battery",
                    "state_class": "measurement",
                    "charging": battery["charging"],
                    "temperature": battery["temperature"],
                })
            except HAError as e:
                Logger.warning(f"HA: tablet bateria: {e}")
        if lux is not None and self.ids.get("illuminance"):
            try:
                client.set_state(self.ids["illuminance"], round(lux), {
                    "friendly_name": "Tablet kiosk oświetlenie",
                    "unit_of_measurement": "lx",
                    "device_class": "illuminance",
                    "state_class": "measurement",
                })
            except HAError as e:
                Logger.warning(f"HA: tablet oświetlenie: {e}")
        for kind in ("brightness", "volume", "auto_brightness"):
            eid = self.ids.get(kind)
            if not eid or self._stop.is_set():
                continue
            try:
                state = client.state(eid)["state"]
                if kind == "auto_brightness":
                    if state not in ("on", "off"):
                        continue
                    value = state == "on"
                else:
                    value = float(state)
            except (HAError, KeyError, ValueError):
                continue                    # brak pomocnika albo HA niedostępny
            if self._seen.get(kind) != value:
                self._seen[kind] = value
                Clock.schedule_once(lambda _dt, k=kind, v=value: self.on_remote(k, v))
        # moc gniazdka z ładowarką tabletu (W) - przy zegarze obok błyskawicy
        eid = self.ids.get("charger_power")
        if eid and not self._stop.is_set():
            try:
                power = float(client.state(eid)["state"])
            except (HAError, KeyError, ValueError):
                power = None
            Clock.schedule_once(lambda _dt, p=power: self.on_remote("charger_power", p))
