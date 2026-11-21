"""Okna kalendarza (pełny ekran, przycisk "Wstecz"):

- MonthDialog  - tabela miesiąca, przewijanie miesięcy, święta i wydarzenia na dniach;
                 dotknięcie dnia otwiera listę wydarzeń tego dnia,
- EventsDialog - lista wydarzeń z pełnym opisem (kalendarz, nazwa, godziny, miejsce,
                 opis) i przycisk "Dodaj",
- EventFormDialog - formularz nowego wydarzenia (usługa HA calendar.create_event).

Wydarzenia spoza zakresu odświeżanego przez HAProvider pobiera App.fetch_events.
"""
from datetime import date, datetime, time, timedelta

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty, ObjectProperty,
                             StringProperty)

from kiosk import calendars, pl
from kiosk.ui import make
from kiosk.widgets.dialog import KioskDialog

EVENTS_DAYS = 30                # lista z kartki: dziś + 30 dni
FORM_AUTO_CLOSE = 600           # formularz: pisanie na klawiaturze nie jest dotykiem ekranu
TIME_STEP = 15                  # minuty - krok godziny w formularzu


def _app():
    return App.get_running_app()


# --------------------------------------------------------------------------------------
# Tabela miesiąca
# --------------------------------------------------------------------------------------
class MonthDialog(KioskDialog):
    title = StringProperty("")
    loading = BooleanProperty(False)
    year = NumericProperty(0)
    month = NumericProperty(0)

    def __init__(self, day: date = None, **kwargs):
        super().__init__(**kwargs)
        day = day or date.today()
        self.year, self.month = day.year, day.month
        self._events = []
        Clock.schedule_once(lambda _dt: self._load(), 0.05)

    def prev_month(self):
        self.year, self.month = calendars.shift_month(self.year, self.month, -1)
        self._load()

    def next_month(self):
        self.year, self.month = calendars.shift_month(self.year, self.month, +1)
        self._load()

    def this_month(self):
        today = date.today()
        self.year, self.month = today.year, today.month
        self._load()

    def _load(self):
        self.title = f"{pl.MONTHS_NOM[self.month - 1]} {self.year}"
        days = calendars.month_grid(self.year, self.month)
        self._render(days, [])                    # siatka od razu, wydarzenia po pobraniu
        self.loading = True
        start = datetime.combine(days[0], time.min)
        end = datetime.combine(days[-1] + timedelta(days=1), time.min)
        key = (self.year, self.month)

        def done(events, error):
            if key != (self.year, self.month):    # użytkownik zdążył przewinąć dalej
                return
            self.loading = False
            self._events = events or []
            self._render(days, self._events)

        _app().fetch_events(start, end, done)

    def _render(self, days, events):
        grid = self.ids.grid
        grid.clear_widgets()
        today = date.today()
        for d in days:
            day_events = calendars.events_on(events, d)
            holiday = any(calendars.is_holiday_calendar(e.get("calendar", "")) for e in day_events)
            lines = []
            for ev in day_events[:3]:
                color = calendars.hex_color(calendars.style(ev.get("calendar", ""))[2])
                title = ev["title"] if len(ev["title"]) <= 22 else ev["title"][:21] + "…"
                lines.append(f"[color={color}]{title}[/color]")
            if len(day_events) > 3:
                lines.append(f"+{len(day_events) - 3} więcej")
            cell = make("MonthCell", number=str(d.day), other_month=(d.month != self.month),
                        today=(d == today), red=(d.weekday() == 6 or holiday),
                        events_text="\n".join(lines))
            cell.bind(on_release=lambda _c, day=d: self.open_day(day))
            grid.add_widget(cell)

    def open_day(self, day: date):
        EventsDialog(start_day=day, days=1, events=self._events).open()


# --------------------------------------------------------------------------------------
# Lista wydarzeń
# --------------------------------------------------------------------------------------
class EventsDialog(KioskDialog):
    title = StringProperty("Wydarzenia")
    subtitle = StringProperty("")
    loading = BooleanProperty(False)
    start_day = ObjectProperty(None)
    days = NumericProperty(EVENTS_DAYS)

    def __init__(self, start_day: date = None, days: int = EVENTS_DAYS, events=None, **kwargs):
        super().__init__(**kwargs)
        self.start_day = start_day or date.today()
        self.days = days
        self._preloaded = events
        Clock.schedule_once(lambda _dt: self._load(), 0.05)

    def _range(self):
        start = datetime.combine(self.start_day, time.min)
        return start, start + timedelta(days=self.days)

    def _load(self, force=False):
        start, end = self._range()
        last = (end - timedelta(days=1)).date()
        self.subtitle = (pl.long_date(self.start_day) if self.days == 1
                         else f"{pl.full_date(self.start_day)} - {pl.full_date(last)}")
        if self._preloaded is not None and not force:
            self._render(self._preloaded)
            return
        self.loading = True
        _app().fetch_events(start, end, lambda events, error: self._on_events(events, error))

    def _on_events(self, events, error):
        self.loading = False
        if events is None:
            self._render([], error=f"Brak danych z HA: {error}")
        else:
            self._render(events)

    def _render(self, events, error=""):
        box = self.ids.list
        box.clear_widgets()
        if error:
            box.add_widget(make("EventsEmpty", text=error))
            return
        shown = 0
        for i in range(self.days):
            day = self.start_day + timedelta(days=i)
            day_events = calendars.events_on(events, day)
            if not day_events:
                continue
            box.add_widget(make("EventsDayHeader", text=pl.long_date(day).capitalize(),
                                today=(day == date.today())))
            for ev in day_events:
                kind, icon, color = calendars.style(ev.get("calendar", ""))
                box.add_widget(make(
                    "EventCard", icon=icon, color=color, title=ev["title"],
                    time_text=calendars.time_text(ev),
                    calendar_text=_app().calendar_name(ev.get("calendar", "")) or kind,
                    location=ev.get("location") or "", description=ev.get("description") or ""))
                shown += 1
        if not shown:
            box.add_widget(make("EventsEmpty", text="Brak wydarzeń w tym okresie"))

    def add_event(self):
        EventFormDialog(day=self.start_day, on_saved=lambda: self._load(force=True)).open()


# --------------------------------------------------------------------------------------
# Formularz nowego wydarzenia
# --------------------------------------------------------------------------------------
class EventFormDialog(KioskDialog):
    writable_calendars = ListProperty([])  # [(entity_id, nazwa)] - tylko z zapisem
    calendar_id = StringProperty("")
    day = ObjectProperty(None)
    day_text = StringProperty("")
    all_day = BooleanProperty(False)
    start_min = NumericProperty(10 * 60)  # minuty od północy
    end_min = NumericProperty(11 * 60)
    start_text = StringProperty("")
    end_text = StringProperty("")
    result = StringProperty("")
    result_ok = BooleanProperty(False)
    busy = BooleanProperty(False)

    def __init__(self, day: date = None, on_saved=None, **kwargs):
        super().__init__(**kwargs)
        self._auto_close = Clock.create_trigger(lambda _dt: self.dismiss(), FORM_AUTO_CLOSE)
        self.on_saved = on_saved
        self.day = day or date.today()
        now = datetime.now()
        if self.day == now.date():                # dziś: najbliższy pełny kwadrans + 1 h
            self.start_min = min(23 * 60, (now.hour * 60 + now.minute) // TIME_STEP * TIME_STEP
                                 + TIME_STEP)
            self.end_min = min(24 * 60 - TIME_STEP, self.start_min + 60)
        self._update_texts()
        _app().fetch_writable_calendars(self._on_calendars)

    def _on_calendars(self, items, error):
        if not items:
            self._show(f"Brak kalendarzy z możliwością zapisu{': ' + error if error else ''}",
                       False)
            return
        self.writable_calendars = items
        self.calendar_id = items[0][0]
        box = self.ids.calendars
        box.clear_widgets()
        for eid, name in items:
            _kind, icon, color = calendars.style(eid)
            chip = make("CalendarChip", text=name, icon=icon, color=color, entity_id=eid,
                        selected=(eid == self.calendar_id))
            chip.bind(on_release=lambda c: self._select(c.entity_id))
            box.add_widget(chip)

    def _select(self, eid):
        self.calendar_id = eid
        for chip in self.ids.calendars.children:
            chip.selected = chip.entity_id == eid

    # --- data i godziny -----------------------------------------------------------
    def change_day(self, delta):
        self.day = self.day + timedelta(days=delta)
        self._update_texts()

    def change_time(self, which, delta):
        step = TIME_STEP * delta
        if which == "start":
            duration = self.end_min - self.start_min
            self.start_min = max(0, min(24 * 60 - TIME_STEP, self.start_min + step))
            self.end_min = min(24 * 60 - 1, self.start_min + max(TIME_STEP, duration))
        else:
            self.end_min = max(self.start_min + TIME_STEP, min(24 * 60 - 1, self.end_min + step))
        self._update_texts()

    def _update_texts(self):
        self.day_text = pl.long_date(self.day)
        self.start_text = f"{self.start_min // 60:02d}:{self.start_min % 60:02d}"
        self.end_text = f"{self.end_min // 60:02d}:{self.end_min % 60:02d}"

    def _show(self, text, ok):
        self.result, self.result_ok = text, ok

    # --- zapis --------------------------------------------------------------------
    def save(self):
        summary = self.ids.summary.text.strip()
        if not self.calendar_id:
            self._show("Wybierz kalendarz.", False)
            return
        if not summary:
            self._show("Podaj nazwę wydarzenia.", False)
            return
        data = {"entity_id": self.calendar_id, "summary": summary}
        location = self.ids.location.text.strip()
        description = self.ids.description.text.strip()
        if location:
            data["location"] = location
        if description:
            data["description"] = description
        if self.all_day:
            data["start_date"] = self.day.isoformat()
            data["end_date"] = (self.day + timedelta(days=1)).isoformat()
        else:
            data["start_date_time"] = f"{self.day.isoformat()} {self.start_text}:00"
            data["end_date_time"] = f"{self.day.isoformat()} {self.end_text}:00"
        self.busy = True
        self._show("Zapisywanie…", True)
        _app().call_service("calendar", "create_event", data, self._on_saved)

    def _on_saved(self, _result, error):
        self.busy = False
        if error:
            self._show(f"Nie udało się zapisać: {error}", False)
            return
        _app().refresh_events()
        if self.on_saved:
            # HA potrzebuje chwili, zanim nowe wydarzenie pojawi się w odczycie kalendarza
            Clock.schedule_once(lambda _dt: self.on_saved(), 1.5)
        self.dismiss()
