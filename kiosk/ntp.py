"""NTP clock for the kiosk UI and Android's automatic system-time service."""
import logging
import re
import socket
import struct
import threading
import time
from datetime import datetime

DEFAULT_SERVER = "pool.ntp.org"
NTP_EPOCH = 2_208_988_800
NTP_TIMEOUT = 5
SYNC_SECONDS = 6 * 60 * 60
RETRY_SECONDS = 60

_LOG = logging.getLogger(__name__)


def _offset_from_packet(packet: bytes, sent_at: float, received_at: float) -> float:
    if len(packet) < 48:
        raise OSError("NTP response is shorter than 48 bytes")
    if packet[1] == 0:
        raise OSError("NTP server is unsynchronized")
    seconds, fraction = struct.unpack("!II", packet[40:48])
    server_time = seconds - NTP_EPOCH + fraction / 2**32
    return server_time - (sent_at + received_at) / 2


def _query_offset(server: str) -> float:
    addresses = socket.getaddrinfo(server, 123, type=socket.SOCK_DGRAM)
    last_error = None
    for family, socktype, proto, _, address in addresses:
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(NTP_TIMEOUT)
                sent_at = time.time()
                sock.sendto(b"\x23" + 47 * b"\0", address)
                packet, _ = sock.recvfrom(512)
                received_at = time.time()
            return _offset_from_packet(packet, sent_at, received_at)
        except OSError as exc:
            last_error = exc
    if last_error:
        raise last_error
    raise OSError(f"No NTP address found for {server}")


class NtpClock:
    def __init__(self):
        self.server = DEFAULT_SERVER
        self._offset = 0.0
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._android = False

    def now(self) -> datetime:
        with self._lock:
            offset = self._offset
        return datetime.fromtimestamp(time.time() + offset)

    def set_server(self, server: str) -> bool:
        host = str(server or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", host):
            _LOG.error("Rejected invalid NTP server received from Kiosk Center: %r", server)
            return False
        with self._lock:
            if self.server == host:
                return True
            self.server = host
        _LOG.info("NTP server changed to %s", host)
        if self._android:
            from kivy.clock import Clock
            Clock.schedule_once(lambda _dt: self._configure_android())
        self._wake.set()
        return True

    def start(self):
        from kivy.utils import platform

        if platform != "android" or self._thread is not None:
            return
        self._android = True
        self._configure_android()
        self._wake.clear()
        self._thread = threading.Thread(target=self._run, name="kiosk-ntp", daemon=True)
        self._thread.start()

    def _configure_android(self):
        try:
            from jnius import autoclass

            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            settings = autoclass("android.provider.Settings$Global")
            resolver = activity.getContentResolver()
            with self._lock:
                server = self.server
            if not settings.putString(resolver, "ntp_server", server):
                _LOG.error("Android rejected NTP server setting %s", server)
            if not settings.putInt(resolver, "auto_time", 1):
                _LOG.error("Android rejected automatic-time setting")
        except Exception:
            _LOG.exception("Could not configure Android automatic time; check WRITE_SECURE_SETTINGS")

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                server = self.server
            try:
                offset = _query_offset(server)
                with self._lock:
                    self._offset = offset
                _LOG.info("NTP synchronized with %s (offset %.3f s)", server, offset)
                delay = SYNC_SECONDS
            except OSError as exc:
                _LOG.warning("NTP synchronization with %s failed: %s", server, exc)
                delay = RETRY_SECONDS
            self._wake.wait(delay)
            self._wake.clear()


_clock = NtpClock()


def now() -> datetime:
    return _clock.now()


def set_server(server: str) -> bool:
    return _clock.set_server(server)


def start():
    _clock.start()
