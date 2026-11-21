"""Ogłaszanie pełnych godzin: gong i komunikat "Jest godzina ..." z nagrań.

Nagrania (assets/sounds/hour_07.ogg ... hour_22.ogg) to gong z komunikatem w jednym
pliku, polski głos neuronowy (edge-tts, pl-PL-ZofiaNeural). Ogłaszanie działa także
przy wygaszonym ekranie; głośność z suwaka głośności (strumień multimediów).

Godziny: poniedziałek-piątek od 7:00, sobota i niedziela od 9:00, do 22:00 włącznie.
Włączenie: przełącznik w Ustawieniach (local.json: hour_chime, domyślnie włączone).
"""
from datetime import datetime
from pathlib import Path

from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.logger import Logger

SOUNDS = Path(__file__).resolve().parent.parent / "assets" / "sounds"
WEEKDAY_START = 7
WEEKEND_START = 9
END = 22
CHECK_SECONDS = 10


def is_announced(now: datetime) -> bool:
    """Czy o tej pełnej godzinie (dzień tygodnia i godzina) ogłaszać czas."""
    start = WEEKDAY_START if now.weekday() < 5 else WEEKEND_START
    return start <= now.hour <= END


class HourChime:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._done = None               # (data, godzina) już ogłoszona
        self._sound = None
        Clock.schedule_interval(self._check, CHECK_SECONDS)

    def _check(self, _dt):
        now = datetime.now()
        if now.minute != 0 or not self.enabled or not is_announced(now):
            return
        key = (now.date(), now.hour)
        if key == self._done:
            return
        self._done = key
        self.play(now.hour)

    def play(self, hour: int = None):
        """Odtwarza komunikat danej godziny (domyślnie bieżącej - przycisk w Ustawieniach)."""
        hour = datetime.now().hour if hour is None else hour
        hour = min(max(hour, WEEKDAY_START), END)       # próba poza godzinami: najbliższe nagranie
        path = SOUNDS / f"hour_{hour:02d}.ogg"
        if not path.exists():
            Logger.warning(f"Godzina: brak nagrania {path.name}")
            return
        try:
            if self._sound is not None:
                self._sound.stop()
                self._sound.unload()
            self._sound = SoundLoader.load(str(path))
            if self._sound is None:
                Logger.warning(f"Godzina: nie udało się wczytać {path.name}")
                return
            Logger.info(f"Godzina: ogłoszenie {hour}:00")
            self._sound.play()
        except Exception as e:          # noqa: BLE001 - dźwięk nie może zatrzymać aplikacji
            Logger.warning(f"Godzina: błąd odtwarzania: {e}")
