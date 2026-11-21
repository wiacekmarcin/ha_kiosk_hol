"""Okno "Słońce w roku" (pełny ekran): wykres wschodów i zachodów dla każdego dnia roku
z zaznaczonym dniem dzisiejszym oraz opisy długości dnia.

Dane liczy kiosk/sun_year.py dla położenia domu z HA; wykres rysowany jest raz
(przy otwarciu okna i zmianie rozmiaru), dotknięcie wykresu pokazuje wybrany dzień.
"""
from datetime import date, timedelta

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Mesh, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.widget import Widget

from kiosk import config, pl, sun_year
from kiosk.widgets.dialog import KioskDialog
from kiosk.widgets.line_chart import text_texture

PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 64, 20, 40, 40
SUN = config.COLOR_SUN_ICON
SET_COLOR = (1.0, 0.50, 0.25, 1)
JUMP_MINUTES = 30            # skok wykresu przy zmianie czasu letni/zimowy - przerwa w linii


def _hm(dt) -> str:
    return dt.strftime("%H:%M") if dt else "--:--"


def _day_text(d: date) -> str:
    return f"{d.day} {pl.MONTHS_GEN[d.month - 1]}"


class SunYearChart(Widget):
    days = ListProperty([])              # sun_year.sun_year(...)
    today = ObjectProperty(None)
    cursor = NumericProperty(-1)         # indeks dnia pod palcem, -1 = brak

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._redraw = Clock.create_trigger(self.draw)
        self.bind(pos=self._redraw, size=self._redraw, days=self._redraw,
                  today=self._redraw, cursor=self._redraw)

    # --- dotyk: pokaż wybrany dzień -------------------------------------------------
    def _index_at(self, x):
        x0, x1 = self.x + dp(PAD_LEFT), self.right - dp(PAD_RIGHT)
        i = round((x - x0) / (x1 - x0) * (len(self.days) - 1))
        return min(max(i, 0), len(self.days) - 1)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and self.days:
            touch.grab(self)
            self.cursor = self._index_at(touch.x)
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            self.cursor = self._index_at(touch.x)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            return True
        return super().on_touch_up(touch)

    # --- rysowanie --------------------------------------------------------------------
    def draw(self, *_):
        self.canvas.clear()
        days = [d for d in self.days if d["rise"] and d["set"]]
        if not days or self.width < 200:
            return
        x0, x1 = self.x + dp(PAD_LEFT), self.right - dp(PAD_RIGHT)
        y0, y1 = self.y + dp(PAD_BOTTOM), self.top - dp(PAD_TOP)
        rises = [sun_year.minutes_of_day(d["rise"]) for d in days]
        sets = [sun_year.minutes_of_day(d["set"]) for d in days]
        lo = max(0, (min(rises) // 60 - 1) * 60)
        hi = min(1440, (max(sets) // 60 + 2) * 60)
        n = len(self.days)

        def px(i):
            return x0 + i / (n - 1) * (x1 - x0)

        def py(minutes):
            return y0 + (minutes - lo) / (hi - lo) * (y1 - y0)

        index = {d["date"]: i for i, d in enumerate(self.days)}
        with self.canvas:
            # tło nocy
            Color(*config.COLOR_BG)
            Rectangle(pos=(x0, y0), size=(x1 - x0, y1 - y0))

            # siatka godzin + etykiety osi Y
            for m in range(int(lo), int(hi) + 1, 120):
                y = py(m)
                Color(*config.COLOR_DIVIDER)
                Line(points=[x0, y, x1, y], width=1)
                tex = text_texture(f"{m // 60}:00", 14)
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, size=tex.size, pos=(x0 - dp(8) - tex.width, y - tex.height / 2))

            # dzień: pasmo między wschodem a zachodem
            vertices, indices = [], []
            for k, d in enumerate(days):
                x = px(index[d["date"]])
                vertices += [x, py(rises[k]), 0, 0, x, py(sets[k]), 0, 0]
                indices += [2 * k, 2 * k + 1]
            Color(*SUN[:3], 0.22)
            Mesh(vertices=vertices, indices=indices, mode="triangle_strip")

            # linie wschodu i zachodu (przerwa przy zmianie czasu)
            for values, color in ((rises, SUN), (sets, SET_COLOR)):
                Color(*color)
                seg = []
                for k, d in enumerate(days):
                    if seg and abs(values[k] - values[k - 1]) > JUMP_MINUTES:
                        Line(points=seg, width=dp(2), joint="round")
                        seg = []
                    seg += [px(index[d["date"]]), py(values[k])]
                Line(points=seg, width=dp(2), joint="round")

            # miesiące: separatory i nazwy pośrodku
            year = self.days[0]["date"].year
            for month in range(1, 13):
                first = index[date(year, month, 1)]
                last = index[date(year, month + 1, 1) - timedelta(days=1)] if month < 12 else n - 1
                xa = px(first)
                Color(*config.COLOR_DIVIDER[:3], 0.6)
                Line(points=[xa, y0, xa, y1], width=1, dash_length=4, dash_offset=4)
                tex = text_texture(pl.MONTHS_SHORT[month - 1], 15)
                Color(1, 1, 1, 1)
                xc = (xa + px(last)) / 2
                Rectangle(texture=tex, size=tex.size, pos=(xc - tex.width / 2, y0 - dp(10) - tex.height))

            # najdłuższy i najkrótszy dzień
            longest = max(days, key=lambda d: d["length"])
            shortest = min(days, key=lambda d: d["length"])
            for d, label in ((longest, "najdłuższy"), (shortest, "najkrótszy")):
                i = index[d["date"]]
                Color(*config.COLOR_TEXT_DIM[:3], 0.8)
                bottom = y0 if d is shortest else py(sun_year.minutes_of_day(d["rise"]))
                Line(points=[px(i), bottom,
                             px(i), py(sun_year.minutes_of_day(d["set"]))], width=1,
                     dash_length=3, dash_offset=3)
                tex = text_texture(f"{label} {sun_year.duration(d['length'])}", 13)
                if d is longest:      # nad zachodem
                    ty = py(sun_year.minutes_of_day(d["set"])) + dp(6)
                else:                 # najkrótszy: na dole wykresu (przy zachodzie jest etykieta "dziś")
                    ty = y0 + dp(6)
                tx = min(max(px(i) - tex.width / 2, x0 + dp(4)), x1 - tex.width - dp(4))
                Color(0.067, 0.071, 0.086, 0.85)        # tło - etykieta czytelna na liniach
                RoundedRectangle(pos=(tx - dp(4), ty - dp(2)),
                                 size=(tex.width + dp(8), tex.height + dp(4)), radius=[dp(4)])
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, size=tex.size, pos=(tx, ty))

            # dziś
            if self.today in index:
                self._marker(index[self.today], px, py, y0, y1, x0, x1, config.COLOR_ACCENT, "dziś")
            # dzień wybrany palcem
            if 0 <= self.cursor < n and self.days[self.cursor]["rise"]:
                self._marker(self.cursor, px, py, y0, y1, x0, x1, config.COLOR_TEXT,
                             _day_text(self.days[self.cursor]["date"]), box=True)

    def _marker(self, i, px, py, y0, y1, x0, x1, color, title, box=False):
        d = self.days[i]
        x = px(i)
        yr, ys = py(sun_year.minutes_of_day(d["rise"])), py(sun_year.minutes_of_day(d["set"]))
        Color(*color)
        Line(points=[x, y0, x, y1], width=dp(1.5))
        for y in (yr, ys):
            Ellipse(pos=(x - dp(6), y - dp(6)), size=(dp(12), dp(12)))
        side = 1 if x + dp(140) < x1 else -1           # etykiety po prawej, przy brzegu po lewej

        def put(tex, y):
            tx = x + dp(10) if side > 0 else x - dp(10) - tex.width
            Color(0.067, 0.071, 0.086, 0.85)
            RoundedRectangle(pos=(tx - dp(4), y - dp(2)), size=(tex.width + dp(8), tex.height + dp(4)),
                             radius=[dp(4)])
            Color(1, 1, 1, 1)
            Rectangle(texture=tex, size=tex.size, pos=(tx, y))

        put(text_texture(_hm(d["rise"]), 16, config.COLOR_TEXT, bold=True), yr - dp(26))
        put(text_texture(_hm(d["set"]), 16, config.COLOR_TEXT, bold=True), ys + dp(6))
        head = text_texture(title, 15, color, bold=True)
        put(head, y1 + dp(8) if not box else y1 - head.height - dp(4))
        if box:
            put(text_texture(sun_year.duration(d["length"]), 15, config.COLOR_TEXT),
                (yr + ys) / 2 - dp(10))


class SunDialog(KioskDialog):
    title = StringProperty("Słońce w roku")
    length_text = StringProperty("")
    rise_text = StringProperty("--:--")
    set_text = StringProperty("--:--")
    noon_text = StringProperty("--:--")
    change_text = StringProperty("")
    longest_text = StringProperty("")
    shortest_text = StringProperty("")
    solstice_title = StringProperty("Przesilenie")
    solstice_text = StringProperty("")
    days = ListProperty([])
    today = ObjectProperty(None)

    def __init__(self, location: dict = None, **kwargs):
        super().__init__(**kwargs)
        self.location = location or sun_year.DEFAULT_LOCATION
        Clock.schedule_once(lambda _dt: self._compute(), 0.05)

    def _compute(self):
        today = date.today()
        loc = self.location
        s = sun_year.summary(today, loc["latitude"], loc["longitude"], loc.get("elevation", 0))
        now, longest, shortest = s["today"], s["longest"], s["shortest"]
        self.title = f"Słońce w roku {today.year}"
        self.length_text = sun_year.duration(now["length"])
        self.rise_text, self.set_text, self.noon_text = _hm(now["rise"]), _hm(now["set"]), _hm(now["noon"])

        diff = now["length"] - s["yesterday"]["length"]
        if abs(diff) < 1 / 60:
            self.change_text = "tyle samo co wczoraj"
        else:
            color = "#4ccc66" if diff > 0 else "#f5544d"
            word = "dłuższy" if diff > 0 else "krótszy"
            self.change_text = (f"niż wczoraj: [color={color}][b]{word} o "
                                f"{sun_year.duration(diff, seconds=True)}[/b][/color]")

        to_long = longest["length"] - now["length"]
        to_short = now["length"] - shortest["length"]
        self.longest_text = (f"[b]{_day_text(longest['date'])}[/b] - {sun_year.duration(longest['length'])}\n"
                             + ("[color=#f5c13f]to dziś![/color]" if to_long < 0.5 else
                                f"dziś krótszy o [b]{sun_year.duration(to_long)}[/b]"))
        self.shortest_text = (f"[b]{_day_text(shortest['date'])}[/b] - {sun_year.duration(shortest['length'])}\n"
                              + ("[color=#4db3fa]to dziś![/color]" if to_short < 0.5 else
                                 f"dziś dłuższy o [b]{sun_year.duration(to_short)}[/b]"))

        nxt = s["next_solstice"]
        if nxt:
            left = (nxt - today).days
            summer = nxt.month == 6
            self.solstice_title = "Przesilenie letnie" if summer else "Przesilenie zimowe"
            when = "[b]dziś![/b]" if left == 0 else \
                f"[b]za {left} {pl.plural(left, 'dzień', 'dni', 'dni')}[/b] - {_day_text(nxt)}"
            after = "potem dni będą coraz krótsze" if summer else "potem dni będą coraz dłuższe"
            self.solstice_text = f"{when}\n{after}"
        self.today = today
        self.days = s["year"]
