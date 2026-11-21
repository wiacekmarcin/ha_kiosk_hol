"""Okno skanowania kodu QR kamerą urządzenia (token / adres Home Assistant).

Dekodowanie: pyzbar (w APK: recepty pyzbar + libzbar), a gdy go brak - OpenCV
(cv2.QRCodeDetector, typowo na komputerze). Na Androidzie klatka jest brana
wprost z podglądu kamery (NV21 - pierwsze w*h bajtów to obraz w skali szarości).
"""
import json

from kivy.clock import Clock
from kivy.logger import Logger
from kivy.properties import ObjectProperty, StringProperty
from kivy.utils import platform

from kiosk.widgets.dialog import KioskDialog

SCAN_INTERVAL = 0.4          # s między próbami dekodowania klatki
CAMERA_RESOLUTION = (640, 480)


def parse_qr(text: str) -> dict:
    """Treść kodu -> {"url": ..., "token": ...} (tylko znalezione pola).

    Obsługiwane: sam token, sam adres (http...), JSON {"url", "token"},
    adres z tokenem w parametrze (...?token=...).
    """
    text = (text or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return {k: str(data[k]).strip() for k in ("url", "token") if data.get(k)}
        except ValueError:
            pass
    if text.lower().startswith(("http://", "https://")):
        from urllib.parse import parse_qs, urlsplit, urlunsplit
        parts = urlsplit(text)
        token = parse_qs(parts.query).get("token", [""])[0]
        url = urlunsplit((parts.scheme, parts.netloc, "", "", "")) if token else text
        result = {"url": url.rstrip("/")}
        if token:
            result["token"] = token
        return result
    return {"token": "".join(text.split())}     # token bez spacji / nowych linii


def _decoder():
    """Funkcja (gray_bytes, w, h) -> [tekst] albo None, gdy brak biblioteki."""
    try:
        if platform == "android":
            # ctypes.util.find_library nie widzi bibliotek APK - ładujemy libzbar.so wprost
            import ctypes
            from pyzbar import zbar_library
            zbar_library.load = lambda: (ctypes.cdll.LoadLibrary("libzbar.so"), [])
        from pyzbar import pyzbar

        def decode(gray, w, h):
            return [s.data.decode("utf-8", "replace")
                    for s in pyzbar.decode((gray, w, h), symbols=[pyzbar.ZBarSymbol.QRCODE])]
        return decode
    except Exception as e:          # noqa: BLE001 - brak pyzbar / libzbar
        Logger.info(f"QR: pyzbar niedostępny ({e})")
    try:
        import cv2
        import numpy as np
        detector = cv2.QRCodeDetector()

        def decode(gray, w, h):
            img = np.frombuffer(gray, dtype=np.uint8).reshape(h, w)
            text, _pts, _ = detector.detectAndDecode(img)
            return [text] if text else []
        return decode
    except Exception as e:          # noqa: BLE001
        Logger.info(f"QR: OpenCV niedostępny ({e})")
    return None


def ensure_camera_permission(on_result):
    """Android 6+: zgoda na kamerę w czasie działania. on_result(bool)."""
    if platform != "android":
        on_result(True)
        return
    try:
        from android.permissions import Permission, check_permission, request_permissions
        if check_permission(Permission.CAMERA):
            on_result(True)
            return
        request_permissions([Permission.CAMERA],
                            lambda _perms, grants: Clock.schedule_once(
                                lambda _dt: on_result(all(grants))))
    except Exception as e:          # noqa: BLE001
        Logger.warning(f"QR: nie udało się zapytać o zgodę na kamerę: {e}")
        on_result(True)


class QRScannerDialog(KioskDialog):
    message = StringProperty("Uruchamianie kamery…")
    on_result = ObjectProperty(None, allownone=True)    # callback(dict z parse_qr, tekst)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._camera = None
        self._event = None
        self._decode = None

    def on_open(self):
        super().on_open()
        self._decode = _decoder()
        if self._decode is None:
            self.message = ("Brak biblioteki do odczytu kodów QR (pyzbar albo OpenCV).\n"
                            "Wpisz token ręcznie.")
            return
        ensure_camera_permission(self._start_camera)

    def _start_camera(self, granted):
        if not granted:
            self.message = "Brak zgody na użycie kamery."
            return
        try:
            from kivy.uix.camera import Camera
            cam = Camera(play=False, resolution=CAMERA_RESOLUTION, index=0,   # tylna kamera
                         pos_hint={"x": 0, "y": 0})
            if cam._camera is None:
                raise RuntimeError("nie znaleziono kamery")
            self.ids.preview.add_widget(cam)
            cam.play = True
        except Exception as e:      # noqa: BLE001 - brak kamery / sterownika
            Logger.warning(f"QR: kamera niedostępna: {e}")
            self.message = f"Kamera niedostępna ({e}).\nWpisz token ręcznie."
            return
        self._camera = cam
        self.message = "Skieruj kamerę na kod QR z tokenem"
        self._event = Clock.schedule_interval(self._scan, SCAN_INTERVAL)

    def _frame(self):
        """Klatka w skali szarości: (bytes, w, h) albo None."""
        core = self._camera._camera
        if platform == "android" and hasattr(core, "grab_frame"):
            buf = core.grab_frame()
            if not buf:
                return None
            w, h = core._resolution
            return bytes(buf[:w * h]), w, h               # NV21: płaszczyzna Y
        tex = self._camera.texture
        if tex is None:
            return None
        w, h = tex.size
        return bytes(tex.pixels[1::4]), w, h              # RGBA -> kanał G

    def _scan(self, _dt):
        if not self._camera:
            return
        try:
            frame = self._frame()
            texts = self._decode(*frame) if frame else []
        except Exception as e:      # noqa: BLE001
            Logger.warning(f"QR: błąd dekodowania: {e}")
            return
        for text in texts:
            result = parse_qr(text)
            if result:
                Logger.info(f"QR: odczytano kod ({', '.join(result)})")   # bez treści tokenu
                if self.on_result:
                    self.on_result(result)
                self.dismiss()
                return

    def on_dismiss(self):
        super().on_dismiss()
        if self._event:
            self._event.cancel()
            self._event = None
        if self._camera:
            self._camera.play = False
            try:
                self._camera._camera.stop()
            except Exception:       # noqa: BLE001
                pass
            self._camera = None
