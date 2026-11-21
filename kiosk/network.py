"""Stan połączenia sieciowego urządzenia (ikona Wi-Fi obok zegara).

Android: ConnectivityManager (czy jest sieć i czy to Wi-Fi) + WifiManager (siła
sygnału, wymaga uprawnienia ACCESS_WIFI_STATE). Komputer: czy system ma trasę do
internetu (gniazdo UDP bez wysyłania danych) - bez rozróżnienia Wi-Fi / kabel.
"""
import socket

from kivy.logger import Logger
from kivy.utils import platform

# siła sygnału 0-4 -> ikona MDI
WIFI_ICONS = ["wifi-strength-outline", "wifi-strength-1", "wifi-strength-2",
              "wifi-strength-3", "wifi-strength-4"]


def status() -> dict:
    """{"connected": bool, "kind": "wifi"|"other"|"none", "level": 0-4 | None, "name": str}"""
    if platform == "android":
        try:
            return _android_status()
        except Exception as e:      # noqa: BLE001
            Logger.warning(f"Sieć: nie udało się odczytać stanu: {e}")
            return {"connected": False, "kind": "none", "level": None, "name": ""}
    return _desktop_status()


def icon_for(st: dict) -> str:
    if not st["connected"]:
        return "wifi-off"
    if st["kind"] == "wifi" and st["level"] is not None:
        return WIFI_ICONS[max(0, min(4, st["level"]))]
    return "wifi" if st["kind"] == "wifi" else "lan"


def _desktop_status() -> dict:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))         # adres testowy (RFC 5737) - nic nie jest wysyłane
        connected = not s.getsockname()[0].startswith("127.")
    except OSError:
        connected = False
    finally:
        s.close()
    return {"connected": connected, "kind": "wifi" if connected else "none",
            "level": None, "name": ""}


def _android_status() -> dict:
    from jnius import autoclass
    context = autoclass("org.kivy.android.PythonActivity").mActivity
    Context = autoclass("android.content.Context")
    ConnectivityManager = autoclass("android.net.ConnectivityManager")
    cm = context.getSystemService(Context.CONNECTIVITY_SERVICE)
    info = cm.getActiveNetworkInfo()
    if info is None or not info.isConnected():
        return {"connected": False, "kind": "none", "level": None, "name": ""}
    if info.getType() != ConnectivityManager.TYPE_WIFI:
        return {"connected": True, "kind": "other", "level": None, "name": ""}
    level, name = None, ""
    try:
        WifiManager = autoclass("android.net.wifi.WifiManager")
        wm = context.getApplicationContext().getSystemService(Context.WIFI_SERVICE)
        conn = wm.getConnectionInfo()
        level = WifiManager.calculateSignalLevel(conn.getRssi(), 5)     # 0-4
        name = (conn.getSSID() or "").strip('"')
    except Exception as e:          # noqa: BLE001 - brak uprawnienia itp.
        Logger.info(f"Sieć: brak siły sygnału Wi-Fi: {e}")
    return {"connected": True, "kind": "wifi", "level": level, "name": name}
