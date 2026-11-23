"""Wiadomości głosowe między tabletami przez Home Assistant (domofon).

Wysyłanie: nagranie (AAC w MP4, do MAX_SECONDS s) trafia do katalogu multimediów HA
(POST /api/media_source/local_source/upload) jako kiosk_glos_<tablet>.m4a - każdy
tablet nadpisuje swój jeden plik. Potem encja STATE_ENTITY dostaje nowy stan (id
wiadomości) i atrybuty: od kogo, nazwa pliku, czas, długość.

Odbiór: każdy tablet co POLL_SECONDS s czyta STATE_ENTITY; nowa wiadomość od innego
tabletu (nie starsza niż MAX_AGE s) jest pobierana (GET /media/local/<plik>) i
odtwarzana po zapowiedzi "Nowa wiadomość głosowa" (gong + głos).
Wiadomość może też przyjść z karty "kiosk-voice-card" na dashboardzie HA (nagranie
z przeglądarki, .webm albo .m4a).

Komunikaty tekstowe: TEXT_ENTITY (input_text, ustawiany przez script.kiosk_komunikat
z automatyzacji albo z karty) - tablet zamienia tekst na mowę (TTS_ENGINE w HA)
i odtwarza po zapowiedzi.

Android: jeden MediaRecorder i jeden MediaPlayer na całe życie aplikacji (pyjnius) -
każde nowe obiekty Javy na głównym wątku zostawiałyby odwołania JNI.
Uprawnienie RECORD_AUDIO pytane przy pierwszym otwarciu okna nagrywania.
"""
import threading
from collections import deque
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
TEXT_ENTITY = "input_text.kiosk_komunikat"      # komunikat tekstowy z HA (script.kiosk_komunikat)
TTS_ENGINE = "tts.home_assistant_cloud"         # Nabu Casa - polski głos
TTS_LANGUAGE = "pl-PL"
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
    """Kolejka komunikatów: wszystko, co aplikacja chce powiedzieć (zapowiedź i wiadomość
    głosowa, ogłoszenie godziny, komunikat pory dnia), gra po kolei na jednym MediaPlayerze.
    Nowy komunikat nie przerywa bieżącego, tylko czeka na swoją kolej.

    Nagrania z mikrofonu tabletu (.m4a) są ciche - przy ich odtwarzaniu działa wzmacniacz
    Androida LoudnessEnhancer (+BOOST_MB milibeli, z ogranicznikiem, bez przesterowania).
    Zapowiedź i nagrania z karty HA (.wav, znormalizowane w przeglądarce) idą bez wzmocnienia.

    Wzmacniacz jest włączany raz i zostaje włączony - zmienia się tylko jego wzmocnienie.
    Włączenie efektu w chwili startu odtwarzania wyciszało ok. 2 s początku nagrania
    (ogranicznik startuje od pełnego tłumienia)."""
    BOOST_MB = 1500                     # +15 dB
    NO_BOOST = (".wav", ".ogg", ".mp3")  # pliki już znormalizowane
    GAP = 0.3                           # s przerwy między komunikatami
    MAX_QUEUE = 12                      # zabezpieczenie przed zaległościami

    def __init__(self):
        self._player = None
        self._enhancer = None
        self._next = None               # zaplanowane przejście do kolejnego komunikatu
        self._sound = None
        self._queue = deque()

    def play(self, paths):
        """Dopisuje pliki na koniec kolejki (w podanej kolejności) i startuje, jeśli cisza."""
        for p in paths:
            if p and Path(p).exists():
                if len(self._queue) >= self.MAX_QUEUE:
                    Logger.warning(f"Głos: kolejka pełna, pomijam {Path(p).name}")
                    continue
                self._queue.append(str(p))
        if self._next is None:
            self._play_next()

    def _play_next(self, _dt=None):
        self._next = None
        if self._still_playing():       # czas trwania był niedoszacowany - poczekaj
            self._next = Clock.schedule_once(self._play_next, 0.2)
            return
        while self._queue:
            path = self._queue.popleft()
            boost = Path(path) != INTRO and Path(path).suffix.lower() not in self.NO_BOOST
            try:
                seconds = self._play_one(path, boost=boost)
            except Exception as e:      # noqa: BLE001
                Logger.warning(f"Głos: błąd odtwarzania {path}: {e}")
                continue
            self._next = Clock.schedule_once(self._play_next, max(seconds, 0.5) + self.GAP)
            return

    def _still_playing(self) -> bool:
        try:
            if ANDROID and self._player is not None:
                return bool(self._player.isPlaying())
            return self._sound is not None and self._sound.state == "play"
        except Exception:               # noqa: BLE001
            return False
    def _play_one(self, path: str, boost: bool) -> float:
        if ANDROID:
            if self._player is None:
                from jnius import autoclass
                self._player = autoclass("android.media.MediaPlayer")()
            p = self._player
            p.reset()
            p.setAudioStreamType(STREAM_MUSIC)
            p.setDataSource(path)
            p.prepare()
            self._set_boost(boost)
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

    def _set_boost(self, enabled: bool):
        """LoudnessEnhancer na sesji audio odtwarzacza (jeden obiekt, stale włączony)."""
        if self._enhancer is False:
            return
        try:
            if self._enhancer is None:
                from jnius import autoclass
                enhancer_cls = autoclass("android.media.audiofx.LoudnessEnhancer")
                self._enhancer = enhancer_cls(self._player.getAudioSessionId())
                self._enhancer.setTargetGain(0)
                self._enhancer.setEnabled(True)
            self._enhancer.setTargetGain(self.BOOST_MB if enabled else 0)
        except Exception as e:      # noqa: BLE001 - brak efektu na urządzeniu: gramy bez wzmocnienia
            Logger.warning(f"Głos: wzmacniacz niedostępny: {e}")
            self._enhancer = False

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
        self._text_seen = None
        self._text_first = True
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
            for poll in (self._poll_voice, self._poll_text):
                try:
                    poll()
                except Exception as e:  # noqa: BLE001
                    Logger.debug(f"Głos: odczyt ({poll.__name__}): {e}")
            self._stop.wait(POLL_SECONDS)

    def _deliver(self, info: dict, path: Path):
        self.last = (info, str(path))
        if self.on_message:
            Clock.schedule_once(lambda _dt: self.on_message(info, str(path)))

    def _poll_voice(self):
        """Nagranie z innego tabletu albo z karty na dashboardzie HA."""
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
        # rozszerzenie jak u nadawcy: tablet .m4a, przeglądarka .webm albo .m4a
        path = self.cache / ("odebrana" + (Path(attrs["file"]).suffix or ".m4a"))
        path.write_bytes(media.content)
        info = {"from": attrs.get("from", "?"), "duration": attrs.get("duration"),
                "time": datetime.now().strftime("%H:%M")}
        Logger.info(f"Głos: wiadomość od {info['from']} ({info['duration']} s)")
        self._deliver(info, path)

    def _poll_text(self):
        """Komunikat tekstowy z HA (skrypt / automatyzacja / karta): TEXT_ENTITY -> mowa
        z silnika TTS_ENGINE (POST /api/tts_get_url) -> odtworzenie po zapowiedzi."""
        r = requests.get(f"{self.base}/api/states/{TEXT_ENTITY}", headers=self.headers, timeout=10)
        if r.status_code == 404:
            self._text_first = False
            return
        r.raise_for_status()
        st = r.json()
        text, changed = (st.get("state") or "").strip(), st.get("last_changed")
        if changed == self._text_seen:
            return
        self._text_seen = changed
        if self._text_first:
            self._text_first = False
            return
        if not text or text in ("unknown", "unavailable"):
            return
        try:
            if (datetime.now(timezone.utc) - datetime.fromisoformat(changed)).total_seconds() > MAX_AGE:
                return
        except (TypeError, ValueError):
            pass
        r = requests.post(f"{self.base}/api/tts_get_url", headers=self.headers, timeout=30,
                          json={"engine_id": TTS_ENGINE, "message": text, "language": TTS_LANGUAGE})
        r.raise_for_status()
        url = r.json()["url"]
        if url.startswith("/"):
            url = self.base + url
        audio = requests.get(url, headers=self.headers, timeout=30)
        audio.raise_for_status()
        path = self.cache / "komunikat.mp3"
        path.write_bytes(audio.content)
        info = {"from": "Home Assistant", "text": text, "duration": None,
                "time": datetime.now().strftime("%H:%M")}
        Logger.info(f"Głos: komunikat z HA: {text[:60]}")
        self._deliver(info, path)
