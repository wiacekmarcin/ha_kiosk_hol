"""Księżyc: rysunek fazy (MoonDisc) i okno pełnoekranowe z fazami (MoonDialog).

MoonDisc rysuje tarczę z oświetloną częścią dokładnie wg fazy (nie ikonę z 8 stanów).
MoonDialog: dziś (faza, oświetlenie, wiek, wschód i zachód), najbliższe główne fazy
oraz kalendarz faz na cały miesiąc z przewijaniem miesięcy.
"""
import math
from datetime import date, datetime, timedelta

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Mesh
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.widget import Widget

from kiosk import calendars, moon, pl, sun_year
from kiosk.ui import make
from kiosk.widgets.dialog import KioskDialog

DARK = (0.20, 0.21, 0.25, 1)
LIGHT = (0.96, 0.93, 0.80, 1)
SEGMENTS = 48


class MoonDisc(Widget):
    """Tarcza Księżyca; phase 0-1 (0 nów, 0,25 I kwadra, 0,5 pełnia, 0,75 III kwadra)."""
    phase = NumericProperty(0.0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._redraw = Clock.create_trigger(self.draw)
        self.bind(pos=self._redraw, size=self._redraw, phase=self._redraw)

    def draw(self, *_):
        self.canvas.clear()
        r = min(self.width, self.height) / 2
        if r < 2:
            return
        cx, cy = self.center
        side = 1 if self.phase < 0.5 else -1        # przybywa: jasna prawa strona
        k = math.cos(2 * math.pi * self.phase)      # położenie terminatora
        vertices, indices = [], []
        for i in range(SEGMENTS + 1):
            t = -math.pi / 2 + math.pi * i / SEGMENTS
            x, y = r * math.cos(t), cy + r * math.sin(t)
            vertices += [cx + side * x, y, 0, 0, cx + side * x * k, y, 0, 0]
            indices += [2 * i, 2 * i + 1]
        with self.canvas:
            Color(*DARK)
            Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r))
            Color(*LIGHT)
            Mesh(vertices=vertices, indices=indices, mode="triangle_strip")
            Color(1, 1, 1, 0.12)
            Line(circle=(cx, cy, r), width=1)


def _hm(dt) -> str:
    return dt.strftime("%H:%M") if dt else "--:--"


def _in_days(when: datetime, now: datetime) -> str:
    days = (when.date() - now.date()).days
    if days == 0:
        return "dziś"
    if days == 1:
        return "jutro"
    return f"za {days} {pl.plural(days, 'dzień', 'dni', 'dni')}"


class MoonDialog(KioskDialog):
    title = StringProperty("Księżyc")
    phase = NumericProperty(0.0)
    phase_name = StringProperty("")
    details = StringProperty("")
    rise_text = StringProperty("--:--")
    set_text = StringProperty("--:--")
    month_title = StringProperty("")
    year = NumericProperty(0)
    month = NumericProperty(0)

    def __init__(self, location: dict = None, **kwargs):
        super().__init__(**kwargs)
        self.location = location or sun_year.DEFAULT_LOCATION
        today = date.today()
        self.year, self.month = today.year, today.month
        self._last_shift = 0.0
        Clock.schedule_once(lambda _dt: self._load(), 0.05)

    def _load(self):
        now = datetime.now()
        info = moon.phase_info(now)
        self.phase = info["phase"]
        self.phase_name = info["name"]
        self.details = (f"Oświetlenie [b]{round(info['illumination'] * 100)} %[/b]\n"
                        f"Wiek [b]{pl.num(info['age'])}[/b] dnia")
        rs = moon.rise_set(now.date(), self.location["latitude"], self.location["longitude"])
        self.rise_text, self.set_text = _hm(rs["rise"]), _hm(rs["set"])

        box = self.ids.next_phases
        box.clear_widgets()
        for when, name, k in moon.next_phases(now, 4):
            row = make("MoonPhaseRow", phase=k / 4, name=name,
                       when=f"{pl.DAYS_SHORT[when.weekday()]} {when.day} "
                            f"{pl.MONTHS_GEN[when.month - 1]}, {when:%H:%M}",
                       left=_in_days(when, now))
            box.add_widget(row)
        self._render_month()

    # --- kalendarz faz ---------------------------------------------------------------
    def _shift(self, delta):
        now = Clock.get_time()
        if now - self._last_shift < 0.3:            # drugie zdarzenie tego samego dotknięcia
            return
        self._last_shift = now
        self.year, self.month = calendars.shift_month(self.year, self.month, delta)
        self._render_month()

    def prev_month(self):
        self._shift(-1)

    def next_month(self):
        self._shift(+1)

    def _render_month(self):
        self.month_title = f"{pl.MONTHS_NOM[self.month - 1]} {self.year}"
        first = date(self.year, self.month, 1)
        # główne fazy w tym miesiącu (od kilku dni przed początkiem)
        main = {}
        for when, name, _k in moon.next_phases(datetime.combine(first, datetime.min.time())
                                               - timedelta(days=1), 6):
            if when.month == self.month and when.year == self.year:
                main[when.date()] = f"{name}\n{when:%H:%M}"
        grid = self.ids.month_grid
        grid.clear_widgets()
        for _ in range(first.weekday()):
            grid.add_widget(Widget())
        today = date.today()
        for d, info in moon.month_phases(self.year, self.month):
            grid.add_widget(make("MoonDayCell", number=str(d.day), phase=info["phase"],
                                 today=(d == today), main=main.get(d, ""),
                                 red=(d.weekday() == 6)))
