"""Połączenie tabletu z Kiosk Center (aplikacja HA ha_kiosk_center) - TCP/UDP, bez HA.

Odnalezienie: rozgłoszenie UDP {"type": "discover"} na port DISCOVERY_PORT, centrum
odpowiada portem TCP; albo adres z ustawień ("center": "adres[:port]").
Ramki: linia JSON (nagłówek) i - gdy nagłówek ma "size" - tyle bajtów danych (nagranie).
Opis protokołu: ha_kiosk_center/kiosk_center/center/protocol.py.

Wątki: odbiór (połączenie, odczyt ramek) i zapis (kolejka ramek) - wątek interfejsu nigdy
nie czeka na sieć. Obsługa ramek (on(typ, fn)) i odpowiedzi (request) w wątku interfejsu.
Status tabletu (bateria, ładowanie) co STATUS_SECONDS s z wątku interfejsu (pyjnius).
"""
import json
import queue
import socket
import threading
import time

from kivy.clock import Clock
from kivy.logger import Logger

DISCOVERY_PORT = 47701
TCP_PORT = 47700
STATUS_SECONDS = 30
PING_SECONDS = 45
MAX_HEADER = 256 * 1024


class CenterLink:
    def __init__(self, name: str, app: str, settings: dict | None = None, formats=("m4a",)):
        self.name = name
        self.app = app
        self.formats = list(formats)
        self.address = (settings or {}).get("center", "")   # "adres[:port]" albo odnajdywanie
        self.tablet = {}                # konfiguracja z centrum (welcome / config)
        self.connected = False
        self._handlers: dict[str, list] = {}
        self._replies: dict[int, object] = {}
        self._req = 0
        self._sock = None
        self._out = queue.Queue()
        self._stop = threading.Event()
        self._status_ev = None

    # --- API -------------------------------------------------------------------------------
    def on(self, kind: str, fn):
        """fn(nagłówek, dane | None) w wątku interfejsu dla ramek typu kind."""
        self._handlers.setdefault(kind, []).append(fn)

    def start(self):
        threading.Thread(target=self._run, name="center-rx", daemon=True).start()
        threading.Thread(target=self._writer, name="center-tx", daemon=True).start()
        self._status_ev = Clock.schedule_interval(lambda _dt: self.send_status(), STATUS_SECONDS)

    def stop(self):
        self._stop.set()
        if self._status_ev:
            self._status_ev.cancel()
        self._close()

    def send(self, header: dict, data: bytes | None = None) -> bool:
        """Ramka do kolejki; False, gdy brak połączenia z centrum."""
        if not self.connected:
            return False
        self._out.put((header, data))
        return True

    def request(self, header: dict, data: bytes | None, callback, timeout=60) -> bool:
        """Ramka z numerem req; callback(odpowiedź | None) w wątku interfejsu
        (None - brak odpowiedzi w timeout s)."""
        self._req += 1
        req = self._req
        self._replies[req] = callback

        def expire(_dt):
            cb = self._replies.pop(req, None)
            if cb:
                cb(None)
        if not self.send({**header, "req": req}, data):
            self._replies.pop(req, None)
            return False
        Clock.schedule_once(expire, timeout)
        return True

    def send_status(self):
        if not self.connected:
            return
        try:
            from kiosk import device
            info = device.battery() or {}
            status = {"type": "status", "battery": info.get("level"),
                      "charging": info.get("charging"), "temperature": info.get("temperature"),
                      "version": device.app_version()}
            self.send(status)
        except Exception as e:      # noqa: BLE001
            Logger.debug(f"Centrum: status: {e}")

    # --- wątki ------------------------------------------------------------------------------
    def _discover(self):
        if self.address:
            host, _, port = self.address.partition(":")
            return host, int(port or TCP_PORT)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.settimeout(2)
            s.sendto(json.dumps({"type": "discover", "name": self.name}).encode(),
                     ("255.255.255.255", DISCOVERY_PORT))
            data, addr = s.recvfrom(2048)
            reply = json.loads(data)
            if reply.get("type") == "center":
                return addr[0], int(reply.get("tcp", TCP_PORT))
        except (OSError, ValueError):
            return None
        finally:
            s.close()
        return None

    def _run(self):
        delay = 3
        while not self._stop.is_set():
            target = self._discover()
            if target:
                try:
                    self._session(*target)
                    delay = 3
                except Exception as e:      # noqa: BLE001
                    Logger.info(f"Centrum: {target[0]}: {e}")
                self._close()
            self._stop.wait(delay)
            delay = min(delay * 2, 60)

    def _session(self, host, port):
        sock = socket.create_connection((host, port), timeout=10)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.settimeout(PING_SECONDS * 2)
        self._sock = sock
        from kiosk import device
        self._write({"type": "hello", "name": self.name, "app": self.app,
                     "version": device.app_version(), "formats": self.formats,
                     "model": _model()}, None)
        f = sock.makefile("rb")
        header, _ = self._read(f)
        if header.get("type") != "welcome":
            raise ConnectionError(f"centrum odpowiedziało {header.get('type')}")
        self.tablet = header.get("tablet", {})
        self.connected = True
        Logger.info(f"Centrum: połączono z {host}:{port} jako {self.tablet.get('name')}")
        self._dispatch(header, None)
        Clock.schedule_once(lambda _dt: self.send_status(), 1)
        while not self._stop.is_set():
            try:
                header, data = self._read(f)
            except socket.timeout:      # centrum odpowiada na ping - cisza to zerwane łącze
                raise ConnectionError("centrum nie odpowiada") from None
            if header.get("type") in ("welcome", "config"):
                self.tablet = header.get("tablet", self.tablet)
            self._dispatch(header, data)

    @staticmethod
    def _read(f):
        line = f.readline(MAX_HEADER)
        if not line:
            raise ConnectionError("centrum zamknęło połączenie")
        header = json.loads(line)
        size = header.pop("size", 0) or 0
        data = f.read(size) if size else None
        if size and (data is None or len(data) != size):
            raise ConnectionError("niepełna ramka")
        return header, data

    def _dispatch(self, header, data):
        req = header.get("req")
        cb = self._replies.pop(req, None) if req is not None and header.get("type") != "game" else None
        fns = list(self._handlers.get(header.get("type"), []))

        def run(_dt):
            if cb:
                cb(header)
            for fn in fns:
                try:
                    fn(header, data)
                except Exception as e:      # noqa: BLE001
                    Logger.warning(f"Centrum: obsługa {header.get('type')}: {e}")
        Clock.schedule_once(run)

    def _write(self, header, data):
        h = dict(header)
        if data:
            h["size"] = len(data)
        line = json.dumps(h, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        self._sock.sendall(line + (data or b""))

    def _writer(self):
        """Kolejka ramek i ping co PING_SECONDS s - niezależnie od innych ramek (status nie
        dostaje odpowiedzi, a odbiór uznaje ciszę dłuższą niż 2 * PING_SECONDS za zerwanie)."""
        last_ping = time.monotonic()
        while not self._stop.is_set():
            try:
                item = self._out.get(timeout=5)
            except queue.Empty:
                item = None
            if not self.connected or self._sock is None:
                last_ping = time.monotonic()
                continue
            frames = [item] if item else []
            if time.monotonic() - last_ping >= PING_SECONDS:
                frames.append(({"type": "ping"}, None))
                last_ping = time.monotonic()
            try:
                for header, data in frames:
                    self._write(header, data)
            except OSError as e:
                Logger.info(f"Centrum: błąd wysyłania: {e}")
                self._close()

    def _close(self):
        was = self.connected
        self.connected = False
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        if was:
            Logger.info("Centrum: rozłączono")


def _model() -> str:
    try:
        from kivy.utils import platform
        if platform == "android":
            from jnius import autoclass
            return str(autoclass("android.os.Build").MODEL)
    except Exception:       # noqa: BLE001
        pass
    return "PC"
