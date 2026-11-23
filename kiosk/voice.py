"""Wiadomości głosowe między tabletami przez Home Assistant (domofon).

Wysyłanie: nagranie (AAC w MP4, do MAX_SECONDS s) trafia do katalogu multimediów HA
(POST /api/media_source/local_source/upload) jako kiosk_glos_<tablet>.m4a - każdy
tablet nadpisuje swój jeden plik. Potem encja STATE_ENTITY dostaje nowy stan (id
wiadomości) i atrybuty: od kogo, nazwa pliku, czas, długość.

Odbiór: każdy tablet co POLL_SECONDS s czyta STATE_ENTITY; nowa wiadomość od innego
tabletu (nie starsza niż MAX_AGE s) jest pobierana (GET /media/local/<plik>) i
odtwarzana po zapowiedzi "Nowa wiadomość głosowa" (gong + głos).

Android: jeden MediaRecorder i jeden MediaPlayer na całe życie aplikacji (pyjnius) -
każde nowe obiekty Javy na głównym wątku zostawiałyby odwołania JNI.
Uprawnienie RECORD_AUDIO pytane przy pierwszym otwarciu okna nagrywania.
"""
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from kivy.clock import Clock
from kivy.logger import Logger
from kivy.utils import platform

ANDROID = platform == "android"
MAX_SECONDS = 30
MIN_SECONDS = 0.7                   # krótsze nagranie to przypadkowe dotknięcie
POLL_SECONDS = 3
MAX_AGE = 300                       # s - starszych wiadomości nie odtwarzamy (np. po starcie)
STATE_ENTITY = "sensor.kiosk_wiadomosc_glosowa"
INTRO = Path(__file__).resolve().parent.parent / "assets" / "sounds" / "message_intro.ogg"
STREAM_MUSIC = 3


def safe_id(name: str) -> str:
    """Nazwa tabletu -> fragment nazwy pliku (ASCII)."""
    table = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ ", "acelnoszzACELNOSZZ_")
    return "".join(c for c in name.translate(table).lower() if c.isalnum() or c == "_") or "tablet"


def cache_dir() -> str:
    """Katalog na nagrania: dane aplikacji; gdy niedostępny (komputer bez ~/.config) - tmp."""
    try:
        from kivy.app import App
        return App.get_running_app().user_data_dir
    except (OSError, AttributeError):
        import tempfile
        return tempfile.gettempdir()


def ensure_mic_permission(callback):
    """callback(granted: bool) - na komputerze zawsze False (brak nagrywania)."""
    if not ANDROID:
        callback(False)
        return
    try:
        from android.permissions import Permission, check_permission, request_permissions
        if check_permission(Permission.RECORD_AUDIO):
            callback(True)
            return

        def done(_perms, results):
            Clock.schedule_once(lambda _dt: callback(bool(results and all(results))))
        request_permissions([Permission.RECORD_AUDIO], done)
    except Exception as e:          # noqa: BLE001
        Logger.warning(f"Głos: uprawnienie mikrofonu: {e}")
        callback(False)


# --- nagrywanie -----------------------------------------------------------------------
class Recorder:
    def __init__(self):
        self._rec = None
        self._started = None
        self.path = None

    def start(self, path: str):
        if not ANDROID:
            raise RuntimeError("nagrywanie działa tylko na tablecie")
        if self._rec is None:
            from jnius import autoclass
            self._rec = autoclass("android.media.MediaRecorder")()
        rec = self._rec
        rec.reset()
        rec.setAudioSource(1)                   # MIC
        rec.setOutputFormat(2)                  # MPEG_4
        rec.setAudioEncoder(3)                  # AAC
        rec.setAudioChannels(1)
        rec.setAudioSamplingRate(22050)
        rec.setAudioEncodingBitRate(48000)
        rec.setMaxDuration(MAX_SECONDS * 1000 + 500)
        rec.setOutputFile(path)
        rec.prepare()
        rec.start()
        self.path = path
        self._started = time.monotonic()

    def stop(self) -> float:
        """Kończy nagrywanie; zwraca długość w sekundach (0 = błąd albo za krótko)."""
        if self._started is None:
            return 0.0
        length = time.monotonic() - self._started
        self._started = None
        try:
            self._rec.stop()
        except Exception as e:      # noqa: BLE001 - stop() zaraz po start() rzuca wyjątek
            Logger.info(f"Głos: nagranie przerwane: {e}")
            self._rec.reset()
            return 0.0
        self._rec.reset()
        return min(length, MAX_SECONDS)

    @property
    def recording(self) -> bool:
        return self._started is not None


# --- odtwarzanie ----------------------------------------------------------------------
class Player:
    """Zapowiedź i wiadomość jedna po drugiej, jeden MediaPlayer."""

    def __init__(self):
        self._player = None
        self._next = None
        self._sound = None

    def play(self, paths):
        paths = [str(p) for p in paths if p and Path(p).exists()]
        if self._next is not None:
            self._next.cancel()
            self._next = None
        if not paths:
            return
        try:
            seconds = self._play_one(paths[0])
        except Exception as e:      # noqa: BLE001
            Logger.warning(f"Głos: błąd odtwarzania {paths[0]}: {e}")
            seconds = 0
        if len(paths) > 1:
            self._next = Clock.schedule_once(lambda _dt: self.play(paths[1:]), seconds + 0.3)

    def _play_one(self, path: str) -> float:
        if ANDROID:
            if self._player is None:
                from jnius import autoclass
                self._player = autoclass("android.media.MediaPlayer")()
            p = self._player
            p.reset()
            p.setAudioStreamType(STREAM_MUSIC)
            p.setDataSource(path)
            p.prepare()
            p.start()
            return max(p.getDuration(), 0) / 1000
        from kivy.core.audio import SoundLoader
        if self._sound is not None:
            self._sound.stop()
        self._sound = SoundLoader.load(path)
        if self._sound is None:
            return 0
        self._sound.play()
        return self._sound.length or 0


# --- wysyłanie i odbiór przez HA -----------------------------------------------------
class VoiceLink:
    def __init__(self, settings: dict, name: str, cache_dir: str, on_message=None):
        """on_message(info, path) - w wątku UI po pobraniu nowej wiadomości."""
        self.base = settings["url"].rstrip("/")
        self.headers = {"Authorization": f"Bearer {settings['token']}"}
        self.name = name
        self.file_name = f"kiosk_glos_{safe_id(name)}.m4a"
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.on_message = on_message
        self.last = None                # ostatnia odebrana wiadomość (info, ścieżka)
        self._seen = None
        self._first = True
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ha-voice", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    # wysyłanie (wątek w tle, callback w wątku UI)
    def send(self, path: str, seconds: float, callback):
        def work():
            try:
                with open(path, "rb") as f:
                    files = {"file": (self.file_name, f, "audio/mp4")}
                    data = {"media_content_id": "media-source://media_source/local/."}
                    r = requests.post(f"{self.base}/api/media_source/local_source/upload",
                                      headers=self.headers, files=files, data=data, timeout=30)
                r.raise_for_status()
                msg_id = uuid.uuid4().hex[:12]
                self._seen = msg_id             # własnej wiadomości nie odtwarzamy
                r = requests.post(f"{self.base}/api/states/{STATE_ENTITY}", headers=self.headers,
                                  json={"state": msg_id, "attributes": {
                                      "friendly_name": "Wiadomość głosowa (tablety)",
                                      "icon": "mdi:phone-message",
                                      "from": self.name, "file": self.file_name,
                                      "time": datetime.now(timezone.utc).isoformat(),
                                      "duration": round(seconds, 1)}}, timeout=15)
                r.raise_for_status()
                Logger.info(f"Głos: wysłano {seconds:.1f} s ({self.file_name})")
                Clock.schedule_once(lambda _dt: callback(True, ""))
            except Exception as e:      # noqa: BLE001
                Logger.warning(f"Głos: błąd wysyłania: {e}")
                Clock.schedule_once(lambda _dt, err=str(e): callback(False, err))
        threading.Thread(target=work, name="ha-voice-send", daemon=True).start()

    # odbiór
    def _run(self):
        while not self._stop.is_set():
            try:
                self._poll()
            except Exception as e:      # noqa: BLE001
                Logger.debug(f"Głos: odczyt {STATE_ENTITY}: {e}")
            self._stop.wait(POLL_SECONDS)

    def _poll(self):
        r = requests.get(f"{self.base}/api/states/{STATE_ENTITY}", headers=self.headers, timeout=10)
        if r.status_code == 404:
            self._first = False
            return
        r.raise_for_status()
        st = r.json()
        msg_id, attrs = st.get("state"), st.get("attributes", {})
        if msg_id == self._seen:
            return
        self._seen = msg_id
        if self._first:                 # wiadomość sprzed startu - tylko zapamiętujemy
            self._first = False
            return
        if attrs.get("from") == self.name or not attrs.get("file"):
            return
        try:
            sent = datetime.fromisoformat(attrs["time"])
            if (datetime.now(timezone.utc) - sent).total_seconds() > MAX_AGE:
                return
        except (KeyError, ValueError):
            pass
        media = requests.get(f"{self.base}/media/local/{attrs['file']}", headers=self.headers,
                             timeout=30)
        media.raise_for_status()
        path = self.cache / "odebrana.m4a"
        path.write_bytes(media.content)
        info = {"from": attrs.get("from", "?"), "duration": attrs.get("duration"),
                "time": datetime.now().strftime("%H:%M")}
        self.last = (info, str(path))
        Logger.info(f"Głos: wiadomość od {info['from']} ({info['duration']} s)")
        if self.on_message:
            Clock.schedule_once(lambda _dt: self.on_message(info, str(path)))
