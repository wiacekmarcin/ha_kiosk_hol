"""Wykres liniowy szeregu czasowego rysowany bezpośrednio na canvasie Kivy.

points: [(datetime, float | None), ...]  - None = brak danych (przerwa w linii)
Dotknięcie / przeciągnięcie pokazuje wartość najbliższego punktu.
"""
import math
from datetime import timedelta

from kivy.clock import Clock
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Color, Ellipse, Line, Mesh, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import (ListProperty, NumericProperty, ObjectProperty,
                             StringProperty)
from kivy.uix.widget import Widget

from kiosk import config, pl

PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 56, 16, 12, 32


def nice_step(raw: float) -> float:
    """Zaokrągla krok osi do 1/2/5 * 10^n."""
    if raw <= 0:
        return 1
    exp = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * exp:
            return m * exp
    return 10 * exp


def step_intervals(points, start, end):
    """Odczyty czujnika jako funkcja schodkowa: wartość trwa do następnego odczytu."""
    result = []
    for i, (t, v) in enumerate(points):
        t_next = points[i + 1][0] if i + 1 < len(points) else end
        s, e = max(t, start), min(t_next, end)
        if e > s:
            result.append((s, e, v))
    return result


def resample(points, start, end, buckets: int):
    """Średnia ważona czasem w `buckets` równych przedziałach -> [(środek, wartość|None)].

    Wygładza czujniki, które raportują bardzo często i "drgają" o 0,1.
    """
    intervals = step_intervals(points, start, end)
    width = (end - start) / buckets
    out, j = [], 0
    for k in range(buckets):
        b0 = start + width * k
        b1 = b0 + width
        while j < len(intervals) and intervals[j][1] <= b0:
            j += 1
        acc = dur = 0.0
        jj = j
        while jj < len(intervals) and intervals[jj][0] < b1:
            s, e, v = intervals[jj]
            overlap = (min(e, b1) - max(s, b0)).total_seconds()
            if overlap > 0 and v is not None:
                acc += v * overlap
                dur += overlap
            jj += 1
        out.append((b0 + width / 2, acc / dur if dur else None))
    return out


def text_texture(text, size=14, color=config.COLOR_TEXT_DIM, bold=False):
    lbl = CoreLabel(text=text, font_size=sp(size), color=color, bold=bold)
    lbl.refresh()
    return lbl.texture


class LineChart(Widget):
    points = ListProperty([])
    start = ObjectProperty(None)        # początek osi X (datetime)
    end = ObjectProperty(None)          # koniec osi X (datetime)
    unit = StringProperty("")
    hour_step = NumericProperty(3)      # co ile godzin etykieta na osi X
    cursor_x = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._redraw = Clock.create_trigger(self.draw)
        self.bind(pos=self._redraw, size=self._redraw, points=self._redraw,
                  start=self._redraw, end=self._redraw, cursor_x=self._redraw)

    # --- dotyk: pokaż wartość pod palcem --------------------------------------------
    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and self.points:
            touch.grab(self)
            self.cursor_x = touch.x
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            self.cursor_x = min(max(touch.x, self.x + PAD_LEFT), self.right - PAD_RIGHT)
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
        values = [v for _, v in self.points if v is not None]
        if not values or not self.start or not self.end or self.width < 100:
            return

        x0, x1 = self.x + dp(PAD_LEFT), self.right - dp(PAD_RIGHT)
        y0, y1 = self.y + dp(PAD_BOTTOM), self.top - dp(PAD_TOP)
        span = (self.end - self.start).total_seconds()

        lo, hi = min(values), max(values)
        if hi - lo < 1:
            mid = (hi + lo) / 2
            lo, hi = mid - 0.5, mid + 0.5
        step = nice_step((hi - lo) / 5)
        lo, hi = math.floor(lo / step) * step, math.ceil(hi / step) * step
        decimals = 0 if step >= 1 else 1

        def px(t):
            return x0 + (t - self.start).total_seconds() / span * (x1 - x0)

        def py(v):
            return y0 + (v - lo) / (hi - lo) * (y1 - y0)

        with self.canvas:
            # siatka pozioma + etykiety osi Y
            v = lo
            while v <= hi + step / 2:
                y = py(v)
                Color(*config.COLOR_DIVIDER)
                Line(points=[x0, y, x1, y], width=1)
                tex = text_texture(pl.num(v, decimals))
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, size=tex.size,
                          pos=(x0 - dp(8) - tex.width, y - tex.height / 2))
                v += step

            # etykiety osi X co hour_step godzin, na pełnych godzinach
            t = self.start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            while t.hour % self.hour_step:
                t += timedelta(hours=1)
            while t <= self.end:
                x = px(t)
                Color(*config.COLOR_DIVIDER[:3], 0.5)
                Line(points=[x, y0, x, y1], width=1, dash_length=4, dash_offset=4)
                tex = text_texture(t.strftime("%H:%M"))
                Color(1, 1, 1, 1)
                Rectangle(texture=tex, size=tex.size,
                          pos=(x - tex.width / 2, y0 - dp(8) - tex.height))
                t += timedelta(hours=self.hour_step)

            # seria: dużo odczytów -> uśrednienie w przedziałach (~4 px),
            # mało odczytów -> schodki (wartość trwa do następnego odczytu)
            buckets = max(int((x1 - x0) / dp(4)), 10)
            if len(self.points) > buckets:
                series = [(px(t), v) for t, v in resample(self.points, self.start,
                                                           self.end, buckets)]
            else:
                series = []
                for s, e, v in step_intervals(self.points, self.start, self.end):
                    series += [(px(s), v), (px(e), v)]
            segments, current = [], []
            for x, v in series:
                if v is None:
                    if current:
                        segments.append(current)
                    current = []
                else:
                    current.append((x, py(v)))
            if current:
                segments.append(current)

            for seg in segments:
                if len(seg) == 1:
                    seg = seg + [(seg[0][0] + 1, seg[0][1])]
                vertices, indices = [], []
                for i, (x, y) in enumerate(seg):
                    vertices += [x, y, 0, 0, x, y0, 0, 0]
                    indices += [2 * i, 2 * i + 1]
                Color(*config.COLOR_ACCENT[:3], 0.15)
                Mesh(vertices=vertices, indices=indices, mode="triangle_strip")
                Color(*config.COLOR_ACCENT)
                Line(points=[c for p in seg for c in p], width=dp(1.6), joint="round")

            self._draw_cursor(px, py, x0, x1, y0, y1)

    def _draw_cursor(self, px, py, x0, x1, y0, y1):
        if self.cursor_x is None:
            return
        candidates = [(abs(px(t) - self.cursor_x), t, v) for t, v in self.points
                      if v is not None]
        if not candidates:
            return
        _, t, v = min(candidates, key=lambda c: c[0])
        x, y = px(t), py(v)

        Color(*config.COLOR_TEXT_DIM)
        Line(points=[x, y0, x, y1], width=1)
        Color(*config.COLOR_ACCENT)
        Ellipse(pos=(x - dp(5), y - dp(5)), size=(dp(10), dp(10)))

        t_tex = text_texture(t.strftime("%d.%m %H:%M"), 13)
        v_tex = text_texture(f"{pl.num(v)} {self.unit}", 17, config.COLOR_TEXT, bold=True)
        w = max(t_tex.width, v_tex.width) + dp(20)
        h = t_tex.height + v_tex.height + dp(14)
        bx = x + dp(12) if x + dp(12) + w <= x1 else x - dp(12) - w
        by = min(max(y - h / 2, y0), y1 - h)
        Color(0.18, 0.19, 0.23, 0.95)
        RoundedRectangle(pos=(bx, by), size=(w, h), radius=[dp(8)])
        Color(1, 1, 1, 1)
        Rectangle(texture=t_tex, size=t_tex.size,
                  pos=(bx + dp(10), by + h - dp(6) - t_tex.height))
        Rectangle(texture=v_tex, size=v_tex.size, pos=(bx + dp(10), by + dp(6)))
