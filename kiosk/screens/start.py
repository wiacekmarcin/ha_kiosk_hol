"""Ekran startowy: zegar, pogoda, czujniki, wschód/zachód, kalendarz."""
import math
from collections import defaultdict
from datetime import date, datetime, timedelta

from kivy.clock import Clock
from kivy.factory import Factory
from kivy.properties import (BooleanProperty, DictProperty, ListProperty, NumericProperty,
                             StringProperty)
from kivy.uix.screenmanager import Screen

from kiosk import calendars, pl
from kiosk.ui import make
from kiosk.weather_icons import is_night
from kiosk.widgets.history_dialog import HistoryDialog, sensor_series
from kiosk.widgets.rooms_dialog import RoomsDialog
from kiosk.widgets.weather_dialog import WeatherDialog
from kiosk.widgets.calendar_dialogs import EventsDialog, MonthDialog

DIM = "#949ba8"
RED = "#f5544d"
BLUE = "#4db3fa"


def two_lines(text: str, limit: int = 12) -> str:
    """Długi opis (np. "Częściowe zachmurzenie") dzieli na 2 wiersze przy spacji najbliżej środka."""
    if len(text) <= limit or " " not in text:
        return text
    middle = len(text) / 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    cut = min(spaces, key=lambda i: abs(i - middle))
    return text[:cut] + "\n" + text[cut + 1:]


def apparent_temperature(temp, humidity, wind, wind_unit: str = "m/s"):
    """Temperatura odczuwalna (°C) wg Steadmana (Australian Bureau of Meteorology):
    AT = T + 0,33*e - 0,70*v - 4,00, gdzie e to ciśnienie pary wodnej (hPa), v to wiatr w m/s.
    Brak danych -> None."""
    if temp is None or humidity is None or wind is None:
        return None
    unit = (wind_unit or "m/s").lower()
    if unit in ("km/h", "kmh"):
        wind = wind / 3.6
    elif unit == "mph":
        wind = wind * 0.44704
    elif unit in ("kn", "kt", "knots"):
        wind = wind * 0.514444
    vapour = humidity / 100 * 6.105 * math.exp(17.27 * temp / (237.7 + temp))
    return temp + 0.33 * vapour - 0.70 * wind - 4.00


def daily_precipitation(forecast: list, hourly: list, now: datetime = None) -> dict:
    """Suma opadów dla każdego dnia prognozy: {date: mm | None}.

    Dzień w pełni pokryty prognozą godzinową (dziś: od bieżącej godziny do 23:00)
    -> suma z godzin. W przeciwnym razie (dni poza 48 h, niepełne pojutrze)
    -> suma dzienna z prognozy dziennej HA.
    """
    now = now or datetime.now()
    by_day = defaultdict(list)
    for h in hourly:
        by_day[h["datetime"].date()].append(h)
    result = {}
    for day in forecast:
        d = day["date"]
        hours = sorted(by_day.get(d, []), key=lambda h: h["datetime"])
        first_needed = now.hour if d == now.date() else 0
        covered = (hours and hours[0]["datetime"].hour <= first_needed
                   and hours[-1]["datetime"].hour == 23)
        if covered:
            result[d] = sum(h.get("precipitation") or 0 for h in hours)
        else:
            result[d] = day.get("precipitation")
    return result


# Progi dobowej sumy opadów (mm) -> liczba kropli: słabe / umiarkowane / silne
RAIN_LEVELS = (0, 2, 10)


def rain_drops(amount) -> int:
    """0 mm -> 0 kropli, <2 mm -> 1, 2-10 mm -> 2, >=10 mm -> 3."""
    if not amount or amount <= 0:
        return 0
    return sum(1 for limit in RAIN_LEVELS if amount >= limit)


class StartScreen(Screen):
    time_text = StringProperty("")
    date_text = StringProperty("")

    weather = DictProperty({})
    weather_text = StringProperty("")
    weather_temp = StringProperty("")
    weather_feels = StringProperty("")      # temperatura odczuwalna (markup z kolorem)
    weather_range = StringProperty("")
    weather_name = StringProperty("")
    weather_condition = StringProperty("")
    weather_night = BooleanProperty(False)
    sensors = ListProperty([])
    sunrise = StringProperty("--:--")
    sunset = StringProperty("--:--")

    events = ListProperty([])
    week_offset = NumericProperty(0)
    calendar_title = StringProperty("")
    calendar_view = StringProperty("list")   # "month" | "week" | "list"
    status_text = StringProperty("")         # komunikat o błędzie połączenia

    # kartka z kalendarza (prawa kolumna)
    kartka_weekday = StringProperty("")
    kartka_day = StringProperty("")
    kartka_month = StringProperty("")
    kartka_red = BooleanProperty(False)      # niedziela albo święto
    kartka_text = StringProperty("")         # święta, wydarzenia, imieniny, przysłowia

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Clock.schedule_once(self._post_init)

    def _post_init(self, _dt):
        self._tick(0)
        Clock.schedule_interval(self._tick, 1)
        # kartka: imieniny i przysłowia z cache kalbi.pl dostępne po starcie aplikacji
        Clock.schedule_once(self.refresh_kartka, 12)

    # --- zegar ---------------------------------------------------------------
    def _tick(self, _dt):
        now = datetime.now()
        # sekundy mniejszą, przygaszoną czcionką
        self.time_text = (f"{now:%H:%M}[size=40sp][color=#949ba8]:{now:%S}[/color][/size]")
        self.weather_night = is_night(now, self.sunrise, self.sunset)
        new_date = pl.long_date(now.date())
        if new_date != self.date_text:          # zmiana doby -> odśwież kalendarz
            first_run = not self.date_text
            self.date_text = new_date
            self._render_calendar()
            self._kalbi_pending = False
            self.refresh_kartka()
            if not first_run:                  # po północy: nowa kartka z kalendarza
                from kivy.app import App
                App.get_running_app().prefetch_kartka()

    # --- dane ----------------------------------------------------------------
    def set_data(self, data: dict):
        """Jedno wejście dla danych - później wołane przez klienta HA."""
        if "weather" in data:
            self.weather = data["weather"]
        if "sensors" in data:
            self.sensors = data["sensors"]
        if "sun" in data:
            self.sunrise = data["sun"]["rising"]
            self.sunset = data["sun"]["setting"]
        if "events" in data:
            self.events = data["events"]

    def on_weather(self, _inst, w):
        self.weather_text = two_lines(pl.WEATHER.get(w.get("condition"), w.get("condition", "")))
        self.weather_condition = w.get("condition", "")
        self.weather_name = w.get("name", "")
        temp = w.get("temperature")
        feels = w.get("apparent_temperature")
        if feels is None:
            feels = apparent_temperature(temp, w.get("humidity"), w.get("wind_speed"),
                                         w.get("wind_speed_unit", "m/s"))
        self.weather_temp = f"{pl.num(temp)} °C"
        self.weather_feels = ""
        if feels is not None and temp is not None:
            diff = feels - temp                 # różnica poniżej 1 °C - kolor neutralny
            color = BLUE if diff <= -1 else RED if diff >= 1 else DIM
            feels = round(feels)
            self.weather_feels = f"[color={color}]{pl.num(feels)}°[/color]"
        fc = w.get("forecast") or []
        if fc:
            self.weather_range = f"{pl.num(fc[0]['high'])} °C / {pl.num(fc[0]['low'])} °C"
        rain = daily_precipitation(fc, w.get("hourly") or [])
        box = self.ids.forecast
        box.clear_widgets()
        for day in fc[:5]:
            amount = rain.get(day["date"])
            box.add_widget(make("ForecastDay",
                day=pl.DAYS_SHORT[day["date"].weekday()],
                condition=day["condition"],
                high=f"{pl.num(day['high'])}°",
                low=f"{pl.num(day['low'])}°",
                drops=rain_drops(amount),
            ))

    def on_sensors(self, _inst, sensors):
        """Siatka 2x2: kafelki czujników, a na końcu kafelek wschodu/zachodu słońca."""
        grid = self.ids.sensors
        grid.clear_widgets()
        for s in sensors:
            hum = s.get("humidity") or {}
            tile = make("SensorTile",
                        name=s["name"], value=pl.num(s["value"]), unit=s["unit"],
                        icon=s["icon"], more=(s.get("action") == "rooms"),
                        humidity=(f"{pl.num(hum.get('value'), 0)} {hum.get('unit') or '%'}"
                                  if hum else ""))
            if s.get("action") == "rooms":
                # cały kafelek (i kropki) -> okno pomieszczeń
                tile.bind(on_release=lambda _t: self.open_rooms())
            else:
                tile.bind(on_release=lambda _t, sensor=s: self.open_sensor_history(sensor))
            tile.ids.more.bind(on_release=lambda _b: self.open_rooms())
            grid.add_widget(tile)
        grid.add_widget(self._sun_tile())

    def _sun_tile(self):
        if not hasattr(self, "_sun"):
            self._sun = make("SunTile", rising=self.sunrise, setting=self.sunset)
            self.bind(sunrise=lambda _i, v: setattr(self._sun, "rising", v),
                      sunset=lambda _i, v: setattr(self._sun, "setting", v))
        if self._sun.parent:
            self._sun.parent.remove_widget(self._sun)
        return self._sun

    def on_events(self, *_):
        self._render_calendar()
        self.refresh_kartka()

    # --- kartka z kalendarza ---------------------------------------------------------
    _kalbi_pending = False

    def refresh_kartka(self, *_):
        """Kartka na dziś: dzień, święta (kalendarz świąt HA), wydarzenia z kalendarzy HA,
        imieniny, inne święta i przysłowia (kalbi.pl, cache na dysku)."""
        from kivy.app import App
        app = App.get_running_app()
        today = date.today()
        day_events = calendars.events_on(self.events, today)
        holidays = [e for e in day_events if calendars.is_holiday_calendar(e.get("calendar", ""))]
        others = [e for e in day_events if e not in holidays
                  and "workday" not in e.get("calendar", "")]
        self.kartka_weekday = pl.DAYS[today.weekday()].capitalize()
        self.kartka_day = str(today.day)
        self.kartka_month = f"{pl.MONTHS_NOM[today.month - 1]} {today.year}"
        self.kartka_red = today.weekday() == 6 or bool(holidays)

        kalbi = None
        cache = getattr(app, "kalbi", None)
        if cache is not None:
            stored = cache.cached(today)
            kalbi = stored["data"] if stored else None
            if not stored and not self._kalbi_pending:
                self._kalbi_pending = True
                self._kalbi_error = ""

                def loaded(_stored, error):
                    self._kalbi_error = error or ""
                    Clock.schedule_once(self.refresh_kartka)
                cache.get_async(today, loaded)

        parts = []
        for ev in holidays:
            parts.append(f"[size=26sp][b][color={RED}]{ev['title']}[/color][/b][/size]")
        if others:
            lines = []
            for ev in others:
                color = calendars.hex_color(calendars.style(ev.get("calendar", ""))[2])
                when = "" if ev.get("all_day") else f"{ev['start']:%H:%M}  "
                lines.append(f"[color={color}][b]•[/b][/color]  [b]{when}[/b]{ev['title']}")
            parts.append(self._section("Wydarzenia", "\n".join(lines)))
        if kalbi:
            names = ", ".join(kalbi.get("namedays_main", []))
            other = ", ".join(kalbi.get("namedays_other", []))
            if names:
                parts.append(self._section("Imieniny", f"[b]{names}[/b]"
                                           + (f"\n[size=16sp][color={DIM}]oraz: {other}[/color][/size]"
                                              if other else "")))
            if kalbi.get("holidays"):
                parts.append(self._section("Inne święta", ", ".join(kalbi["holidays"])))
            if kalbi.get("proverbs"):
                parts.append(self._section("Przysłowia",
                                           "\n".join(f"[i]{p}[/i]" for p in kalbi["proverbs"])))
        elif cache is not None:
            state = ("brak połączenia z kalbi.pl" if getattr(self, "_kalbi_error", "")
                     else "pobieranie z kalbi.pl…")
            parts.append(f"[color={DIM}]Imieniny i przysłowia: {state}[/color]")
        self.kartka_text = "\n\n".join(parts)

    @staticmethod
    def _section(title, body):
        return f"[size=15sp][color={DIM}]{title.upper()}[/color][/size]\n{body}"

    def open_month(self):
        """Górna część kartki -> tabela miesiąca."""
        MonthDialog().open()

    def open_events(self):
        """Dolna część kartki -> lista wydarzeń (dziś + 30 dni) z przyciskiem Dodaj."""
        EventsDialog().open()

    def on_week_offset(self, *_):
        self._render_calendar()

    # --- szczegóły pogody ----------------------------------------------------------
    def open_weather_details(self):
        WeatherDialog(screen=self).open()

    def open_sensor_history(self, sensor: dict):
        """Dotknięcie kafelka -> wykres 24 h z zakładkami Temperatura / Wilgotność."""
        if sensor.get("entity_id"):
            HistoryDialog(title=sensor["name"], series=sensor_series(sensor)).open()

    def open_rooms(self):
        """Trzy kropki na kafelku -> temperatura i wilgotność we wszystkich pomieszczeniach."""
        from kivy.app import App
        RoomsDialog(rooms=App.get_running_app().rooms).open()

    # --- kalendarz -----------------------------------------------------------
    def calendar_prev(self):
        self.week_offset -= 1

    def calendar_next(self):
        self.week_offset += 1

    def calendar_today(self):
        self.week_offset = 0

    def _render_calendar(self):
        if "calendar_list" not in self.ids:
            return
        start = date.today() + timedelta(weeks=self.week_offset)
        end = start + timedelta(days=6)
        self.calendar_title = pl.date_range(start, end)

        box = self.ids.calendar_list
        box.clear_widgets()
        in_range = sorted((e for e in self.events if start <= e["start"].date() <= end),
                          key=lambda e: e["start"])
        if not in_range:
            box.add_widget(Factory.CalendarEmpty())
            return

        current_day = None
        for ev in in_range:
            d = ev["start"].date()
            if d != current_day:
                current_day = d
                box.add_widget(Factory.Divider())
                box.add_widget(make("CalendarDayHeader",
                    day=pl.DAYS[d.weekday()], date_text=pl.full_date(d)))
            box.add_widget(make("CalendarEvent",
                time_text=("Cały dzień" if ev.get("all_day")
                           else f"{ev['start']:%H:%M} - {ev['end']:%H:%M}"),
                title=ev["title"]))
