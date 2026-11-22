"""Ogłaszanie pełnych godzin: gong i komunikat "Jest godzina ..." z nagrań.

Nagrania (assets/sounds/hour_07.ogg ... hour_22.ogg) to gong z komunikatem w jednym
pliku, polski głos neuronowy (edge-tts, pl-PL-ZofiaNeural). Ogłaszanie działa także
przy wygaszonym ekranie; głośność z suwaka głośności (strumień multimediów).

Godziny: poniedziałek-piątek od 7:00, sobota i niedziela od 9:00, do 22:00 włącznie.
Włączenie: przełącznik w Ustawieniach (local.json: hour_chime, domyślnie włączone).

Android: systemowy MediaPlayer wołany bezpośrednio przez pyjnius, jeden obiekt na całe
życie aplikacji (reset -> setDataSource -> prepare -> start). Dostawca dźwięku Kivy
wybierał na tablecie audio_sdl2, które nie wydawało dźwięku (audio_android "ignored").
Komputer: SoundLoader z Kivy.
"""
from datetime import datetime
from pathlib import Path

from kivy.clock import Clock
from kivy.logger import Logger
from kivy.utils import platform

SOUNDS = Path(__file__).resolve().parent.parent / "assets" / "sounds"
WEEKDAY_START = 7
WEEKEND_START = 9
END = 22
CHECK_SECONDS = 10
STREAM_MUSIC = 3                # android.media.AudioManager.STREAM_MUSIC


def is_announced(now: datetime) -> bool:
    """Czy o tej pełnej godzinie (dzień tygodnia i godzina) ogłaszać czas."""
    start = WEEKDAY_START if now.weekday() < 5 else WEEKEND_START
    return start <= now.hour <= END


class HourChime:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._done = None               # (data, godzina) już ogłoszona
        self._sound = None              # komputer: dźwięk Kivy
        self._player = None             # Android: jeden MediaPlayer
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
            if platform == "android":
                self._play_android(str(path))
            else:
                self._play_kivy(str(path))
            Logger.info(f"Godzina: ogłoszenie {hour}:00")
        except Exception as e:          # noqa: BLE001 - dźwięk nie może zatrzymać aplikacji
            Logger.warning(f"Godzina: błąd odtwarzania: {e}")

    def _play_android(self, path: str):
        if self._player is None:
            from jnius import autoclass
            self._player = autoclass("android.media.MediaPlayer")()
        player = self._player
        player.reset()                  # także przerywa poprzedni komunikat
        player.setAudioStreamType(STREAM_MUSIC)
        player.setDataSource(path)
        player.prepare()
        player.start()

    def _play_kivy(self, path: str):
        from kivy.core.audio import SoundLoader
        if self._sound is not None:
            self._sound.stop()
            self._sound.unload()
        self._sound = SoundLoader.load(path)
        if self._sound is None:
            raise RuntimeError(f"nie udało się wczytać {Path(path).name}")
        self._sound.play()
