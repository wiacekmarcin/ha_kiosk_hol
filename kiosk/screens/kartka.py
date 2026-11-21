"""Ekran "Kartka z kalendarza" (dane: kalbi.pl przez cache, faza Księżyca liczona lokalnie)."""
from datetime import date, datetime, timedelta

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import BooleanProperty, ObjectProperty, StringProperty
from kivy.uix.screenmanager import Screen

from kiosk import kalbi, pl

IDLE_RETURN_SECONDS = 120     # powrót do ekranu startowego po 2 min bez dotyku


class KartkaScreen(Screen):
    day = ObjectProperty(None)
    is_today = BooleanProperty(True)
    is_sunday = BooleanProperty(False)

    # nagłówek kartki
    day_num = StringProperty("")
    weekday = StringProperty("")
    month = StringProperty("")
    year = StringProperty("")
    day_of_year = StringProperty("")
    week = StringProperty("")
    prev_text = StringProperty("")
    next_text = StringProperty("")

    # sekcje (puste = sekcja ukryta)
    namedays_main = StringProperty("")
    namedays_other = StringProperty("")
    church = StringProperty("")
    church_rank = StringProperty("")
    holidays = StringProperty("")
    proverbs = StringProperty("")
    sun_keys = StringProperty("")
    sun_values = StringProperty("")
    moon_icon = StringProperty("moon-new")
    moon_phase = StringProperty("")
    moon_details = StringProperty("")
    quote = StringProperty("")
    quote_author = StringProperty("")
    footer = StringProperty("")
    loading = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._idle = Clock.create_trigger(self._go_back, IDLE_RETURN_SECONDS)

    # --- nawigacja ------------------------------------------------------------------
    def on_enter(self, *_):
        self._idle()

    def on_leave(self, *_):
        self._idle.cancel()

    def on_touch_down(self, touch):
        self._idle.cancel()
        self._idle()
        return super().on_touch_down(touch)

    def _go_back(self, *_):
        App.get_running_app().go_to("start")

    def close(self):
        self._go_back()

    def prev_day(self):
        self.show(self.day - timedelta(days=1))

    def next_day(self):
        self.show(self.day + timedelta(days=1))

    def today(self):
        self.show(date.today())

    # --- dane -----------------------------------------------------------------------
    def show(self, day: date):
        self.day = day
        self.is_today = day == date.today()
        self.is_sunday = day.weekday() == 6
        self.prev_text = self._short(day - timedelta(days=1))
        self.next_text = self._short(day + timedelta(days=1))
        self._apply_local(day)
        self._clear_remote()
        stored = App.get_running_app().kalbi.cached(day)
        if stored:
            self._apply_remote(stored)
            return
        self.loading = True
        self.footer = "Pobieranie kartki z kalbi.pl…"
        App.get_running_app().kalbi.get_async(
            day, lambda s, e: Clock.schedule_once(lambda _dt: self._on_loaded(day, s, e)),
            force=True)

    def _on_loaded(self, day, stored, error):
        if day != self.day:                 # użytkownik zdążył przejść na inny dzień
            return
        self.loading = False
        if stored:
            self._apply_remote(stored)
        else:
            self.footer = f"Nie udało się pobrać kartki: {error}"

    @staticmethod
    def _short(d: date) -> str:
        return f"{d.day} {pl.MONTHS_SHORT[d.month - 1]}"

    def _apply_local(self, day):
        info = kalbi.local_info(day)
        self.day_num = str(day.day)
        self.weekday = info["weekday"]
        self.month = info["month"]
        self.year = str(day.year)
        self.day_of_year = info["day_of_year"]
        self.week = info["week"]
        moon = kalbi.moon_phase(day)
        self.moon_icon = moon["icon"]
        self.moon_phase = moon["name"].capitalize()
        self.moon_details = f"Oświetlenie {moon['illumination']} %  ·  wiek {pl.num(moon['age'])} dnia"

    def _clear_remote(self):
        for name in ("namedays_main", "namedays_other", "church", "church_rank", "holidays",
                     "proverbs", "sun_keys", "sun_values", "quote", "quote_author"):
            setattr(self, name, "")

    def _apply_remote(self, stored):
        d = stored["data"]
        self.namedays_main = ", ".join(d.get("namedays_main", []))
        other = d.get("namedays_other", [])
        self.namedays_other = ("oraz: " + ", ".join(other)) if other else ""
        self.church = d.get("church", {}).get("text", "")
        self.church_rank = d.get("church", {}).get("rank", "")
        self.holidays = "\n".join(f"•  {h}" for h in d.get("holidays", []))
        self.proverbs = "\n".join(d.get("proverbs", []))

        sun = d.get("sun", {})
        rows = [("Świt", sun.get("dawn")), ("Wschód", sun.get("rise")),
                ("Górowanie", sun.get("noon")), ("Zachód", sun.get("set")),
                ("Zmierzch", sun.get("dusk")), ("Długość dnia", sun.get("length")),
                ("Znak zodiaku", sun.get("sign"))]
        rows = [(k, v) for k, v in rows if v]
        self.sun_keys = "\n".join(k for k, _ in rows)
        self.sun_values = "\n".join(f"[b]{v}[/b]" for _, v in rows)

        moon = d.get("moon", {})
        extra = list(moon.get("lines", [])) + ([moon["sign"]] if moon.get("sign") else [])
        phase = kalbi.moon_phase(self.day)
        self.moon_details = "\n".join(
            [f"Oświetlenie {phase['illumination']} %  ·  wiek {pl.num(phase['age'])} dnia"]
            + extra)

        q = d.get("quote", {})
        self.quote = q.get("text", "")
        self.quote_author = f"— {q['author']}" if q.get("author") else ""

        fetched = stored.get("fetched_at", "")
        try:
            fetched = datetime.fromisoformat(fetched).strftime("%d.%m %H:%M")
        except ValueError:
            pass
        loc = d.get("location") or "Warszawa"
        self.footer = f"Źródło: kalbi.pl  ·  lokalizacja: {loc}  ·  pobrano {fetched}"
