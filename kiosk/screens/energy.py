"""Ekran "Rozdzielnia elektryczna": 3 fazy + całkowite zużycie.

Konfiguracja: settings.json -> entities.energy (wzór: settings.example.json).
Odświeżanie co REFRESH_SECONDS, tylko gdy ekran jest widoczny; wszystkie
encje jednym zapytaniem (API szablonów HA).
"""
from kivy.app import App
from kivy.clock import Clock
from kivy.properties import BooleanProperty, DictProperty, StringProperty
from kivy.uix.screenmanager import Screen

from kiosk import pl
from kiosk.ui import make
from kiosk.widgets.history_dialog import HistoryDialog

REFRESH_SECONDS = 5

# pola fazy: (klucz w konfiguracji, etykieta, ikona)
PHASE_FIELDS = [
    ("voltage", "Napięcie", "sine-wave"),
    ("current", "Prąd", "current-ac"),
    ("power", "Moc", "flash"),
    ("power_factor", "Wsp. mocy", "angle-acute"),
]

# domyślna liczba miejsc po przecinku wg jednostki (jak w karcie HA)
DECIMALS = {"V": 2, "A": 2, "W": 2, "kW": 3, "kWh": 2, "Hz": 2, "PLN/h": 4, "PLN/kWh": 4, "": 2}


class EnergyScreen(Screen):
    config = DictProperty({})
    title = StringProperty("Rozdzielnia elektryczna")
    summary = StringProperty("")
    status = StringProperty("")
    built = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._metrics = {}          # entity_id -> [widget, ...]
        self._decimals = {}         # entity_id -> liczba miejsc (z konfiguracji)
        self._values = {}
        self._event = None
        self._busy = False

    # --- budowa z konfiguracji -------------------------------------------------------
    def build(self, config: dict):
        self.config = config or {}
        self.title = self.config.get("title", "Rozdzielnia elektryczna")
        phases_box, totals_grid = self.ids.phases, self.ids.totals
        phases_box.clear_widgets()
        totals_grid.clear_widgets()
        self._metrics.clear()

        for phase in self.config.get("phases", []):
            card = make("PhaseCard", title=phase.get("name", ""))
            for key, label, icon in PHASE_FIELDS:
                eid = phase.get(key)
                if eid:
                    card.ids.grid.add_widget(self._metric(eid, label, icon))
            phases_box.add_widget(card)

        for item in self.config.get("totals", []):
            eid = item["entity_id"]
            if "decimals" in item:
                self._decimals[eid] = item["decimals"]
            totals_grid.add_widget(self._metric(eid, item.get("name", eid), item.get("icon", "flash")))
        self.built = True

    def _metric(self, entity_id, label, icon):
        w = make("EnergyMetric", label=label, icon=icon, value="—", unit="")
        w.bind(on_release=lambda _w: self.open_history(entity_id, label, icon))
        self._metrics.setdefault(entity_id, []).append(w)
        return w

    def entity_ids(self):
        ids = list(self._metrics)
        ids += [e for e in self.config.get("summary", []) if e not in ids]
        return ids

    # --- odświeżanie tylko na widocznym ekranie ---------------------------------------
    def on_enter(self, *_):
        self.refresh()
        self._event = Clock.schedule_interval(lambda _dt: self.refresh(), REFRESH_SECONDS)

    def on_leave(self, *_):
        if self._event:
            self._event.cancel()
            self._event = None

    def refresh(self):
        if self._busy or not self._metrics:      # nie nakładaj zapytań, gdy HA odpowiada wolno
            return
        self._busy = True
        App.get_running_app().fetch_states(self.entity_ids(), self._on_states)

    def _on_states(self, values, error):
        self._busy = False
        if error and not values:
            self.status = f"Brak danych z HA: {error}"
            return
        self.status = ""
        self._values.update(values or {})
        for eid, widgets in self._metrics.items():
            v = self._values.get(eid, {})
            text, unit = self._format(eid, v)
            for w in widgets:
                w.value, w.unit = text, unit
        parts = [" ".join(self._format(e, self._values.get(e, {})))
                 for e in self.config.get("summary", [])]
        self.summary = "   ·   ".join(p for p in parts if p.strip())

    def _format(self, eid, v):
        unit = v.get("unit") or ""
        decimals = self._decimals.get(eid, DECIMALS.get(unit, 2))
        return pl.fixed(v.get("value"), decimals), unit

    def open_history(self, entity_id, label, icon):
        v = self._values.get(entity_id, {})
        HistoryDialog(title=label, series=[{
            "label": label, "entity_id": entity_id, "unit": v.get("unit") or "",
            "value": v.get("value"), "icon": icon}]).open()
