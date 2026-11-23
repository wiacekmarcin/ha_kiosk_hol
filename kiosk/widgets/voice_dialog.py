"""Okno wiadomości głosowej (pełny ekran, czarne tło): "Przytrzymaj i mów".

Nagrywanie trwa, dopóki przycisk jest wciśnięty, najwyżej voice.MAX_SECONDS s
(licznik w dół na ekranie); po puszczeniu nagranie idzie przez HA do pozostałych
tabletów. Krótkie dotknięcie na starcie włącza tryb dotknij-mów-dotknij (nagrywanie
bez trzymania, drugie dotknięcie wysyła). Ekran tabletu w holu gubi długi dotyk po
około 1,5 s - puszczenie kończy nagranie dopiero po GRACE_SECONDS, jeśli dotyk nie wróci.
Niżej ostatnia odebrana wiadomość z przyciskiem "Odtwórz ponownie".

TalkMixin to wspólna logika przycisku - używa jej okno kiosku (VoiceDialog) i ekran
aplikacji testowej domofonu (ha_intercom). Klasa korzystająca z mieszanki deklaruje
właściwości: status, remaining, recording, can_record, max_seconds. Aplikacja musi mieć
atrybuty voice (VoiceLink), voice_recorder (Recorder) i voice_player (Player).
"""
import math
import time
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import BooleanProperty, NumericProperty, StringProperty

from kiosk import voice
from kiosk.widgets.dialog import KioskDialog


class TalkMixin:
    _tick = None
    _t0 = 0.0
    _grace = None
    _latched = False                # tryb dotknij-mów-dotknij
    _pressed_at = 0.0
    TAP_SECONDS = 0.6               # krótsze wciśnięcie na starcie = nagrywanie bez trzymania
    GRACE_SECONDS = 0.8             # tyle czekamy na powrót zgubionego dotyku

    def init_talk(self):
        self.status = "Sprawdzanie mikrofonu…"
        voice.ensure_mic_permission(self._on_permission)

    def _on_permission(self, granted):
        self.can_record = granted
        self.status = ("Przytrzymaj i mów albo dotknij, mów i dotknij ponownie" if granted
                       else "Brak dostępu do mikrofonu (zgoda na nagrywanie)")

    # --- przycisk -----------------------------------------------------------------
    def press(self):
        """Wciśnięcie: start nagrywania; po zgubionym dotyku - dalej; w trybie
        dotknij-mów-dotknij - koniec i wysłanie."""
        self._pressed_at = time.monotonic()
        if not self.recording:
            self._latched = False
            self.start()
        elif self._grace is not None:   # palec "wrócił" - nagrywamy dalej
            self._grace.cancel()
            self._grace = None
        elif self._latched:
            self.stop()

    def release(self):
        """Puszczenie: krótkie dotknięcie na starcie przełącza w tryb bez trzymania;
        dłuższe kończy nagranie po GRACE_SECONDS (chyba że dotyk wróci)."""
        if not self.recording or self._latched:
            return
        now = time.monotonic()
        if now - self._pressed_at < self.TAP_SECONDS and now - self._t0 < self.TAP_SECONDS + 0.2:
            self._latched = True
            self.status = "Nagrywanie - dotknij ponownie, aby wysłać"
            return
        self._grace = Clock.schedule_once(lambda _dt: self.stop(), self.GRACE_SECONDS)

    # --- nagrywanie i wysyłanie ------------------------------------------------------
    def start(self):
        app = App.get_running_app()
        if app.voice is None:
            self.status = "Brak połączenia z Home Assistant"
            return
        if not self.can_record or self.recording:
            return
        path = str(Path(voice.cache_dir()) / "nagranie.m4a")
        try:
            app.voice_recorder.start(path)
        except Exception as e:          # noqa: BLE001
            self.status = f"Nie udało się włączyć mikrofonu: {e}"
            return
        self.recording = True
        self.status = "Nagrywanie - puść przycisk, aby wysłać"
        self._t0 = time.monotonic()
        self.remaining = voice.MAX_SECONDS
        self._tick = Clock.schedule_interval(self._countdown, 0.1)

    def _countdown(self, _dt):
        left = voice.MAX_SECONDS - (time.monotonic() - self._t0)
        self.remaining = max(0, math.ceil(left))
        if left <= 0:
            self.stop()

    def stop(self, send: bool = True):
        if self._grace is not None:
            self._grace.cancel()
            self._grace = None
        self._latched = False
        if not self.recording:
            return
        self.recording = False
        if self._tick is not None:
            self._tick.cancel()
            self._tick = None
        app = App.get_running_app()
        seconds = app.voice_recorder.stop()
        self.remaining = voice.MAX_SECONDS
        if not send:
            self.status = ""
            return
        if seconds < voice.MIN_SECONDS:
            self.status = "Za krótko - przytrzymaj przycisk i mów"
            return
        self.status = f"Wysyłanie ({seconds:.0f} s)…"
        app.voice.send(app.voice_recorder.path, seconds, self._on_sent)

    def _on_sent(self, ok, error):
        self.status = ("Wysłano do pozostałych tabletów" if ok
                       else f"Nie udało się wysłać: {error[:80]}")

    def replay(self):
        app = App.get_running_app()
        if app.voice is not None and app.voice.last:
            app.voice_player.play([app.voice.last[1]])


class VoiceDialog(TalkMixin, KioskDialog):
    status = StringProperty("")
    remaining = NumericProperty(voice.MAX_SECONDS)
    recording = BooleanProperty(False)
    can_record = BooleanProperty(False)
    max_seconds = NumericProperty(voice.MAX_SECONDS)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.init_talk()

    def on_dismiss(self):
        self.stop(send=False)           # zamknięcie okna w trakcie nagrywania - bez wysyłania
        super().on_dismiss()
