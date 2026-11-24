"""Wygaszanie ekranu po bezczynności i budzenie dotykiem albo ruchem przed tabletem.

Galaxy Tab 3 10.1 (GT-P5210) nie ma czujnika ruchu ani zbliżenia - ruch wykrywa
przednia kamera (jak "Wykrywanie ruchu" w Fully Kiosk): porównanie kolejnych klatek
w niskiej rozdzielczości.

"Wyłączenie" ekranu = czarna nakładka + minimalne podświetlenie okna. Prawdziwe
wyłączenie wyświetlacza (blokada urządzenia) zatrzymałoby aplikację i kamerę,
a więc także budzenie ruchem. Kamera działa tylko, gdy ekran jest wygaszony.

Ustawienia (ekran Ustawienia -> local.json): screen_off_minutes (0 = nigdy),
motion_wake (bool).
"""
import time

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.logger import Logger
from kivy.uix.widget import Widget
from kivy.utils import platform

DEFAULT_MINUTES = 5
CHECK_SECONDS = 5               # jak często sprawdzać bezczynność
MOTION_INTERVAL = 0.5           # s między porównaniami klatek
MOTION_STEP = 8                 # co który piksel (w poziomie i pionie) porównywać
MOTION_PIXEL_DIFF = 28          # zmiana jasności piksela (0-255) uznawana za ruch
MOTION_RATIO = 0.04             # ułamek zmienionych pikseli = ruch przed tabletem
MOTION_WARMUP = 3               # pierwsze klatki po starcie kamery (auto-ekspozycja) pomijane
CAMERA_RESOLUTION = (320, 240)
FRONT_CAMERA = 1                # Android: 0 = tylna, 1 = przednia

# Odporność kamery. Sterownik kamery Galaxy Tab 3 (LineageOS) potrafi paść w usłudze
# aparatu (mediaserver, SIGSEGV w CamHAL_PREVIEW) przy szybkim zamykaniu i ponownym
# otwieraniu podglądu, a po kilku takich awariach tablet się restartuje. Dlatego kamera
# startuje z opóźnieniem, nie jest otwierana zaraz po zamknięciu, zawieszenie (brak klatek)
# wykrywa strażnik, a po kolejnych awariach budzenie ruchem wyłącza się do restartu
# aplikacji albo do ponownego włączenia w Ustawieniach.
MOTION_START_DELAY = 5.0        # s od wygaszenia do włączenia kamery
CAMERA_REOPEN_GAP = 20.0        # min. s od zamknięcia kamery do jej ponownego otwarcia
CAMERA_STALL = 10.0             # s bez klatki = kamera zawisła (np. padła usługa aparatu)
CAMERA_STABLE = 600.0           # s poprawnej pracy kamery zerujące licznik awarii
CAMERA_BACKOFF = (60, 300, 900)  # s przerwy po kolejnych awariach kamery
CAMERA_MAX_FAILURES = 3         # tyle awarii z rzędu = budzenie ruchem wyłączone


def sample(gray: bytes, width: int, height: int, step: int = MOTION_STEP) -> bytes:
    """Co step-ty piksel w co step-tym wierszu (szybko, bez numpy)."""
    return b"".join(gray[y * width:(y + 1) * width:step] for y in range(0, height, step))


def motion_ratio(prev: bytes, cur: bytes, threshold: int = MOTION_PIXEL_DIFF) -> float:
    """Ułamek próbek, których jasność zmieniła się o więcej niż threshold."""
    if not prev or len(prev) != len(cur):
        return 0.0
    changed = sum(1 for a, b in zip(prev, cur) if abs(a - b) > threshold)
    return changed / len(cur)


class _Blackout(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas:
            Color(0, 0, 0, 1)
            self._rect = Rectangle(pos=(0, 0), size=Window.size)
        Window.bind(size=lambda _w, size: setattr(self._rect, "size", size))


class ScreenSaver:
    def __init__(self, on_wake):
        self.on_wake = on_wake          # wołane po wybudzeniu (np. ekran startowy)
        self.minutes = DEFAULT_MINUTES
        self.motion_wake = True
        self.blanked = False
        self._last_activity = time.monotonic()
        self._overlay = None
        self._camera = None
        self._motion_event = None
        self._start_event = None        # zaplanowane (opóźnione) włączenie kamery
        self._prev = None
        self._frames = 0
        self._camera_started_at = 0.0
        self._camera_closed_at = -CAMERA_REOPEN_GAP
        self._last_frame_at = 0.0
        self._failures = 0              # kolejne awarie kamery
        self._motion_disabled = False   # po CAMERA_MAX_FAILURES awariach
        Window.bind(on_touch_down=self._on_touch, on_key_down=self._on_key)
        Clock.schedule_interval(self._check, CHECK_SECONDS)

    def configure(self, minutes, motion_wake):
        self.minutes = max(0, int(minutes))
        motion_wake = bool(motion_wake)
        if motion_wake and not self.motion_wake:
            self._failures, self._motion_disabled = 0, False    # ponowne włączenie w Ustawieniach
        self.motion_wake = motion_wake
        self.activity()
        if self.blanked and not self.motion_wake:
            self._stop_camera()

    # --- aktywność ------------------------------------------------------------------
    def idle_seconds(self) -> float:
        """Sekundy od ostatniego dotyku / klawisza."""
        return time.monotonic() - self._last_activity

    def activity(self):
        self._last_activity = time.monotonic()

    def _on_touch(self, _window, _touch):
        self.activity()
        if self.blanked:
            self.wake("dotyk")
            return True                 # pierwszy dotyk tylko budzi - nic nie klika
        return False

    def _on_key(self, *_args):
        self.activity()
        if self.blanked:
            self.wake("klawisz")
            return True
        return False

    def _check(self, _dt):
        if (not self.blanked and self.minutes
                and time.monotonic() - self._last_activity >= self.minutes * 60):
            self.blank()

    # --- wygaszanie / budzenie --------------------------------------------------------
    def blank(self):
        if self.blanked:
            return
        Logger.info("Ekran: wygaszanie po bezczynności")
        self.blanked = True
        from kivy.uix.modalview import ModalView
        for w in list(Window.children):          # otwarte okna nie wiszą do rana
            if isinstance(w, ModalView):
                w.dismiss(animation=False)
        self._overlay = _Blackout()
        Window.add_widget(self._overlay)
        set_brightness(0.0)
        self._schedule_camera(MOTION_START_DELAY)

    def wake(self, reason=""):
        if not self.blanked:
            return
        Logger.info(f"Ekran: wybudzenie ({reason})")
        self.blanked = False
        self._stop_camera()
        if self._overlay is not None:
            Window.remove_widget(self._overlay)
            self._overlay = None
        from kiosk import device
        set_brightness(device.window_brightness())      # jasność z Ustawień albo systemowa
        self.activity()
        self.on_wake()

    # --- kamera (wykrywanie ruchu) ------------------------------------------------------
    def _schedule_camera(self, delay):
        """Włączenie kamery po delay s, ale nie wcześniej niż CAMERA_REOPEN_GAP od zamknięcia."""
        if self._start_event:
            self._start_event.cancel()
            self._start_event = None
        if not (self.blanked and self.motion_wake) or self._motion_disabled:
            return
        gap = CAMERA_REOPEN_GAP - (time.monotonic() - self._camera_closed_at)
        self._start_event = Clock.schedule_once(lambda _dt: self._start_camera(),
                                                max(delay, gap))

    def _start_camera(self):
        self._start_event = None

        def start(granted):
            if (not granted or not self.blanked or not self.motion_wake
                    or self._motion_disabled or self._camera is not None):
                return
            try:
                from kivy.core.camera import Camera as CoreCamera
                if CoreCamera is None:
                    raise RuntimeError("brak obsługi kamery")
                index = FRONT_CAMERA if platform == "android" else 0
                self._camera = CoreCamera(index=index, resolution=CAMERA_RESOLUTION,
                                          stopped=True)
                self._camera.start()
            except Exception as e:      # noqa: BLE001 - brak kamery / zajęta / padła usługa
                self._camera_failed(f"start: {e}")
                return
            now = time.monotonic()
            self._camera_started_at = self._last_frame_at = now
            self._prev, self._frames = None, 0
            self._motion_event = Clock.schedule_interval(self._detect, MOTION_INTERVAL)

        from kiosk.widgets.qr_scanner import ensure_camera_permission
        ensure_camera_permission(start)

    def _stop_camera(self):
        if self._start_event:
            self._start_event.cancel()
            self._start_event = None
        if self._motion_event:
            self._motion_event.cancel()
            self._motion_event = None
        if self._camera is not None:
            try:
                self._camera.stop()
                if hasattr(self._camera, "_release_camera"):
                    self._camera._release_camera()      # Android: zwolnij urządzenie
            except Exception as e:      # noqa: BLE001
                Logger.warning(f"Ekran: zamykanie kamery: {e}")
            self._camera = None
            self._camera_closed_at = time.monotonic()
        self._prev = None

    def _camera_failed(self, reason):
        """Awaria kamery: zamknięcie, przerwa coraz dłuższa, po CAMERA_MAX_FAILURES - koniec."""
        self._failures += 1
        self._stop_camera()
        if self._failures >= CAMERA_MAX_FAILURES:
            self._motion_disabled = True
            Logger.error(f"Ekran: kamera ({reason}) - {self._failures}. awaria z rzędu, "
                         "budzenie ruchem wyłączone do restartu aplikacji")
            return
        delay = CAMERA_BACKOFF[min(self._failures, len(CAMERA_BACKOFF)) - 1]
        Logger.warning(f"Ekran: kamera ({reason}) - awaria {self._failures}, "
                       f"ponowna próba za {delay} s")
        self._schedule_camera(delay)

    def _frame(self):
        cam = self._camera
        if platform == "android" and hasattr(cam, "grab_frame"):
            buf = cam.grab_frame()
            if not buf:
                return None
            w, h = cam._resolution
            return bytes(buf[:w * h]), w, h                  # NV21: płaszczyzna Y
        tex = cam.texture
        if tex is None:
            return None
        w, h = tex.size
        return bytes(tex.pixels[1::4]), w, h

    def _detect(self, _dt):
        if self._camera is None:
            return
        now = time.monotonic()
        try:
            frame = self._frame()
        except Exception as e:          # noqa: BLE001
            Logger.warning(f"Ekran: błąd odczytu kamery: {e}")
            frame = None
        if not frame:
            if now - self._last_frame_at > CAMERA_STALL:     # strażnik: kamera zawisła
                self._camera_failed(f"brak klatek od {CAMERA_STALL:.0f} s")
            return
        self._last_frame_at = now
        if self._failures and now - self._camera_started_at > CAMERA_STABLE:
            self._failures = 0                               # kamera znów pracuje stabilnie
        cur = sample(*frame)
        self._frames += 1
        ratio = motion_ratio(self._prev, cur) if self._frames > MOTION_WARMUP else 0.0
        self._prev = cur
        if ratio >= MOTION_RATIO:
            self.wake(f"ruch {ratio:.0%}")


# Jeden obiekt Runnable na całe życie aplikacji. Wcześniej każda zmiana jasności
# (run_on_ui_thread) tworzyła nowy obiekt pośredni Javy i zostawiała na głównym
# wątku odwołanie JNI; po ~500 zmianach (automatyczna jasność, wygaszanie) Android
# zamykał aplikację: "local reference table overflow (max=512)".
_brightness_runner = None


def _runner():
    global _brightness_runner
    if _brightness_runner is None:
        from jnius import PythonJavaClass, autoclass, java_method

        class BrightnessRunnable(PythonJavaClass):
            __javainterfaces__ = ["java/lang/Runnable"]
            __javacontext__ = "app"

            def __init__(self):
                super().__init__()
                self.value = None
                self.activity = autoclass("org.kivy.android.PythonActivity").mActivity
                self.none = autoclass("android.view.WindowManager$LayoutParams") \
                    .BRIGHTNESS_OVERRIDE_NONE

            @java_method("()V")
            def run(self):                      # wątek UI Androida
                try:
                    window = self.activity.getWindow()
                    params = window.getAttributes()
                    params.screenBrightness = (self.none if self.value is None
                                               else float(self.value))
                    window.setAttributes(params)
                except Exception as e:          # noqa: BLE001
                    Logger.warning(f"Ekran: nie udało się zmienić jasności: {e}")

        _brightness_runner = BrightnessRunnable()
    return _brightness_runner


def set_brightness(value):
    """Android: jasność okna 0.0-1.0; None = jasność systemowa. Na komputerze nic."""
    if platform != "android":
        return
    try:
        runner = _runner()
        runner.value = value
        runner.activity.runOnUiThread(runner)
    except Exception as e:              # noqa: BLE001
        Logger.warning(f"Ekran: nie udało się zmienić jasności: {e}")
