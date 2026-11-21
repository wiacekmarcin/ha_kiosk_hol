"""Okno szczegółów pogody - odpowiednik okna "more-info" encji weather w HA.

Okno otwiera się od razu (na cały ekran) ze wskaźnikiem "Trwa ładowanie". Dane i
prognoza godzinowa (48 kolumn z ikonami - na tablecie to najwolniejsza część)
budują się dopiero po narysowaniu okna, po kilka kolumn na klatkę, żeby ekran nie
zamarzał. Wskaźnik znika, gdy prognoza jest gotowa.
"""
from datetime import datetime

from kivy.clock import Clock
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty, StringProperty

from kiosk import pl
from kiosk.ui import make
from kiosk.weather_icons import is_night
from kiosk.widgets.dialog import KioskDialog

COLUMNS_PER_FRAME = 6           # kolumny prognozy budowane na jedną klatkę
SPINNER_STEP = 12               # stopnie obrotu wskaźnika ładowania na klatkę


class WeatherDialog(KioskDialog):
    screen = ObjectProperty(None)            # StartScreen - źródło danych

    loading = BooleanProperty(True)          # wskaźnik "Trwa ładowanie"
    spinner_angle = NumericProperty(0)
    title = StringProperty("")
    condition_text = StringProperty("")
    condition = StringProperty("")
    night = BooleanProperty(False)
    updated = StringProperty("")
    temperature = StringProperty("")
    temp_range = StringProperty("")
    pressure = StringProperty("")
    humidity = StringProperty("")
    wind = StringProperty("")
    attribution = StringProperty("")
    precip_total = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._build_event = None
        self._spinner_event = Clock.schedule_interval(self._spin, 1 / 30)
        self.screen.bind(weather=self._refresh)
        self._ago_event = Clock.schedule_interval(lambda _dt: self._update_ago(), 30)

    def on_open(self):
        super().on_open()
        # dane dopiero po narysowaniu okna - użytkownik od razu widzi wskaźnik ładowania
        Clock.schedule_once(lambda _dt: self._refresh(), 0.1)

    def on_dismiss(self):
        super().on_dismiss()
        self.screen.unbind(weather=self._refresh)
        self._ago_event.cancel()
        self._spinner_event.cancel()
        if self._build_event:
            self._build_event.cancel()

    def _spin(self, _dt):
        if self.loading:
            self.spinner_angle = (self.spinner_angle + SPINNER_STEP) % 360

    def on_loading(self, *_):
        if self.loading:
            self._spinner_event()
        else:
            self._spinner_event.cancel()

    # --- dane ----------------------------------------------------------------
    def _refresh(self, *_):
        w = self.screen.weather
        if not w:                               # brak danych z HA - czekamy na pierwsze
            return
        self.title = w.get("name", "Pogoda")
        self.condition = w.get("condition", "")
        self.condition_text = pl.WEATHER.get(self.condition, self.condition)
        self.night = is_night(datetime.now(), self.screen.sunrise, self.screen.sunset)
        unit = w.get("temperature_unit", "°C")
        self.temperature = f"{pl.num(w.get('temperature'))} {unit}"
        fc = w.get("forecast") or []
        self.temp_range = (f"{pl.num(fc[0]['high'])} {unit} / {pl.num(fc[0]['low'])} {unit}"
                           if fc else "")
        self.pressure = f"{pl.num(w.get('pressure'))} {w.get('pressure_unit', 'hPa')}"
        self.humidity = f"{pl.num(w.get('humidity'), 0)}%"
        direction = pl.wind_dir(w.get("wind_bearing"))
        self.wind = (f"{pl.num(w.get('wind_speed'), 2)} {w.get('wind_speed_unit', 'm/s')}"
                     + (f" ({direction})" if direction else ""))
        self.attribution = w.get("attribution", "")
        self._update_ago()
        self._render_forecast()

    def _update_ago(self):
        self.updated = pl.ago(self.screen.weather.get("last_changed"))

    def _render_forecast(self):
        """Prognoza godzinowa: godzina, ikona, temperatura, słupek i ilość opadów.
        Kolumny powstają partiami (COLUMNS_PER_FRAME na klatkę)."""
        w = self.screen.weather
        hourly = w.get("hourly") or []
        unit = w.get("precipitation_unit", "mm")
        wind_unit = w.get("wind_speed_unit", "m/s")
        amounts = [h.get("precipitation") or 0 for h in hourly]
        # skala słupków: najwyższy opad, ale min. 1 mm - żeby mżawka nie wyglądała jak ulewa
        scale = max([1.0] + amounts)
        total = sum(amounts[:24])
        self.precip_total = (f"Opady w ciągu 24 h: {pl.num(total)} {unit}" if hourly else "")

        columns, last_day = [], None
        for h, amount in zip(hourly, amounts):
            dt = h["datetime"]
            day = dt.date()
            columns.append(dict(
                top_text=pl.DAYS_SHORT[day.weekday()] if day != last_day else "",
                label=dt.strftime("%H:%M"),
                condition=h["condition"],
                night=is_night(dt, self.screen.sunrise, self.screen.sunset),
                temp=f"{pl.num(h['temperature'])}°",
                precip=amount,
                precip_ratio=amount / scale,
                precip_text=f"{pl.num(amount)} {unit}" if amount else "—",
                # wiatr: prędkość i strzałka kierunku (bearing = skąd wieje)
                wind=(f"{pl.num(h.get('wind_speed'))} {wind_unit}"
                      if h.get("wind_speed") is not None else ""),
                wind_bearing=h["wind_bearing"] if h.get("wind_bearing") is not None else -1))
            last_day = day

        box = self.ids.strip
        box.clear_widgets()
        self.ids.scroll.scroll_x = 0
        if self._build_event:
            self._build_event.cancel()
        if not columns:
            box.add_widget(make("Label", text="Brak prognozy godzinowej",
                                color=(0.6, 0.6, 0.6, 1),
                                size_hint_x=None, width=self.ids.scroll.width))
            self.loading = False
            return

        def build_part(_dt):
            for props in columns[:COLUMNS_PER_FRAME]:
                box.add_widget(make("ForecastColumn", **props))
            del columns[:COLUMNS_PER_FRAME]
            if not columns:
                self._build_event.cancel()
                self._build_event = None
                self.loading = False

        self._build_event = Clock.schedule_interval(build_part, 0)
