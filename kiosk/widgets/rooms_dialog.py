"""Okno z temperaturą i wilgotnością we wszystkich pomieszczeniach."""
from kivy.app import App
from kivy.clock import Clock
from kivy.properties import ListProperty, StringProperty

from kiosk import pl
from kiosk.ui import make
from kiosk.widgets.dialog import KioskDialog
from kiosk.widgets.history_dialog import HistoryDialog, sensor_series

REFRESH_SECONDS = 30


class RoomsDialog(KioskDialog):
    rooms = ListProperty([])     # [{"name", "temperature": entity_id, "humidity": entity_id}]
    message = StringProperty("Wczytywanie…")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._values = {}
        self._tiles = []
        for room in self.rooms:
            tile = make("RoomTile", name=room["name"])
            tile.bind(on_release=lambda _t, r=room: self.open_history(r))
            self.ids.grid.add_widget(tile)
            self._tiles.append((room, tile))
        self._refresh_event = Clock.schedule_interval(lambda _dt: self.load(), REFRESH_SECONDS)
        self.load()

    def on_dismiss(self):
        super().on_dismiss()
        self._refresh_event.cancel()

    def load(self):
        ids = [eid for r in self.rooms for eid in (r.get("temperature"), r.get("humidity")) if eid]
        App.get_running_app().fetch_states(ids, self._on_states)

    def _on_states(self, values, error):
        if error and not self._values:
            self.message = f"Nie udało się pobrać danych: {error}"
            return
        self.message = ""
        self._values.update(values or {})
        for room, tile in self._tiles:
            t = self._values.get(room.get("temperature"), {})
            h = self._values.get(room.get("humidity"), {})
            tile.temp = pl.num(t.get("value"))
            tile.temp_unit = t.get("unit", "°C")
            tile.humidity = f"{pl.num(h.get('value'), 0)} {h.get('unit', '%')}"

    def open_history(self, room):
        """Dotknięcie pomieszczenia -> wykres 24 h z zakładkami Temperatura / Wilgotność."""
        eid = room.get("temperature")
        if not eid:
            return
        t = self._values.get(eid, {})
        h_id = room.get("humidity")
        h = self._values.get(h_id, {}) if h_id else {}
        sensor = {"entity_id": eid, "name": room["name"], "icon": "thermometer",
                  "value": t.get("value"), "unit": t.get("unit") or "°C",
                  "humidity": ({"entity_id": h_id, "value": h.get("value"),
                                "unit": h.get("unit") or "%"} if h_id else None)}
        HistoryDialog(title=room["name"], series=sensor_series(sensor)).open()
