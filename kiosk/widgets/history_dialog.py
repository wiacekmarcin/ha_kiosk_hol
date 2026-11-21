"""Okno z wykresem historii (domyślnie 24 h), z zakładkami dla kilku serii.

series: [{"label": "Temperatura", "entity_id": "sensor.x", "unit": "°C",
          "value": 21.5, "icon": "thermometer"}, ...]
Przy jednej serii zakładki są ukryte.
"""
from datetime import datetime, timedelta

from kivy.app import App
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             StringProperty)

from kiosk import pl
from kiosk.ui import make
from kiosk.widgets.dialog import KioskDialog
from kiosk.widgets.line_chart import LineChart  # noqa: F401  (używany w .kv)


def stats(points, end):
    """Min/maks (z czasem) i średnia ważona czasem trwania wartości."""
    valid = [(t, v) for t, v in points if v is not None]
    if not valid:
        return None
    t_min, v_min = min(valid, key=lambda p: p[1])
    t_max, v_max = max(valid, key=lambda p: p[1])
    total = weighted = 0.0
    for (t, v), (t_next, _) in zip(valid, valid[1:] + [(end, None)]):
        dt = (t_next - t).total_seconds()
        total += dt
        weighted += v * dt
    avg = weighted / total if total else valid[-1][1]
    return {"min": (t_min, v_min), "max": (t_max, v_max), "avg": avg}


def sensor_series(sensor: dict) -> list:
    """Kafelek/pomieszczenie -> serie dla okna: temperatura (+ wilgotność, jeśli jest)."""
    series = [{"label": "Temperatura", "entity_id": sensor["entity_id"],
               "unit": sensor.get("unit") or "°C", "value": sensor.get("value"),
               "icon": sensor.get("icon") or "thermometer"}]
    hum = sensor.get("humidity")
    if hum and hum.get("entity_id"):
        series.append({"label": "Wilgotność", "entity_id": hum["entity_id"],
                       "unit": hum.get("unit") or "%", "value": hum.get("value"),
                       "icon": "water-percent"})
    return series


class HistoryDialog(KioskDialog):
    title = StringProperty("")
    series = ListProperty([])
    tab = NumericProperty(0)            # indeks aktywnej serii
    hours = NumericProperty(24)

    icon = StringProperty("")
    unit = StringProperty("")
    points = ListProperty([])
    loading = BooleanProperty(True)
    message = StringProperty("Wczytywanie…")
    current = StringProperty("")
    min_text = StringProperty("—")
    max_text = StringProperty("—")
    avg_text = StringProperty("—")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._cache = {}                # tab -> punkty (żeby przełączanie nie pobierało ponownie)
        self._tab_buttons = []
        if len(self.series) > 1:
            for i, s in enumerate(self.series):
                btn = make("TabButton", text=s["label"], selected=(i == self.tab))
                btn.bind(on_release=lambda _b, idx=i: setattr(self, "tab", idx))
                self.ids.tabs.add_widget(btn)
                self._tab_buttons.append(btn)
        self.end = datetime.now()
        self.start = self.end - timedelta(hours=self.hours)
        self.ids.chart.start, self.ids.chart.end = self.start, self.end
        self.on_tab()

    def on_tab(self, *_):
        for i, btn in enumerate(self._tab_buttons):
            btn.selected = (i == self.tab)
        s = self.series[self.tab]
        self.icon, self.unit = s.get("icon", ""), s.get("unit", "")
        self.current = f"{pl.num(s.get('value'))} {self.unit}"
        self.ids.chart.cursor_x = None
        self.min_text = self.max_text = self.avg_text = "—"
        if self.tab in self._cache:
            self._show(self._cache[self.tab])
            return
        self.points = []
        self.loading, self.message = True, "Wczytywanie…"
        tab = self.tab
        App.get_running_app().fetch_history(
            s["entity_id"], self.start, self.end,
            lambda pts, err: self._on_history(tab, pts, err))

    def _on_history(self, tab, points, error):
        if error:
            if tab == self.tab:
                self.loading = False
                self.message = f"Nie udało się pobrać historii: {error}"
            return
        points = points or []
        # ostatnią wartość przeciągamy do "teraz", jak w HA
        if points and points[-1][0] < self.end and points[-1][1] is not None:
            points = points + [(self.end, points[-1][1])]
        self._cache[tab] = points
        if tab == self.tab:
            self._show(points)

    def _show(self, points):
        self.loading = False
        if not points:
            self.points = []
            self.message = "Brak danych z tego okresu"
            return
        self.message = ""
        self.points = points
        last_valid = next((v for _, v in reversed(points) if v is not None), None)
        if last_valid is not None:
            self.current = f"{pl.num(last_valid)} {self.unit}"
        st = stats(points, self.end)
        if st:
            self.min_text = f"{pl.num(st['min'][1])} {self.unit}  ·  {st['min'][0]:%H:%M}"
            self.max_text = f"{pl.num(st['max'][1])} {self.unit}  ·  {st['max'][0]:%H:%M}"
            self.avg_text = f"{pl.num(st['avg'])} {self.unit}"
