"""Wczytywanie ustawień połączenia z Home Assistant.

Plik: ha_kiosk/settings.json (nie trafia do gita, wzór: settings.example.json).
Adres i token zapisane na ekranie Ustawienia (local.json w katalogu danych
aplikacji) mają pierwszeństwo przed settings.json. Zmienne środowiskowe
HA_URL / HA_TOKEN mają pierwszeństwo przed wszystkim.
"""
import json
import os
from pathlib import Path

SETTINGS_PATH = Path(__file__).resolve().parents[2] / "settings.json"
LOCAL_FILE = "local.json"


def _android_external_dir():
    """Android: /sdcard/Android/data/<pakiet>/files - zapisywalny przez "adb push"."""
    try:
        from jnius import autoclass   # dostępne tylko w APK
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        ext = activity.getExternalFilesDir(None)
        return Path(ext.getAbsolutePath()) if ext is not None else None
    except Exception:       # noqa: BLE001 - nie Android
        return None


def _user_data_dir():
    try:
        from kivy.app import App
        app = App.get_running_app()
        return Path(app.user_data_dir) if app is not None else None
    except Exception:       # noqa: BLE001 - poza aplikacją Kivy (np. narzędzia)
        return None


def settings_path() -> Path:
    """Plik w katalogu danych aplikacji (np. wgrany na Androidzie przez adb) ma
    pierwszeństwo przed plikiem obok kodu (wbudowanym w APK)."""
    override = os.environ.get("HA_KIOSK_SETTINGS")
    if override:
        return Path(override)
    for folder in (_android_external_dir(), _user_data_dir()):
        if folder is not None and (folder / "settings.json").exists():
            return folder / "settings.json"
    return SETTINGS_PATH


def local_path():
    """Plik z ustawieniami z ekranu Ustawienia: adres, token, wygaszanie ekranu
    (prywatny katalog aplikacji - na Androidzie niedostępny dla innych aplikacji)."""
    folder = _user_data_dir()
    return folder / LOCAL_FILE if folder is not None else None


def load_local() -> dict:
    path = local_path()
    if path is None or not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_local(**updates) -> Path:
    """Dopisuje/zmienia klucze w pliku lokalnych ustawień (zapis atomowy, prawa 0600)."""
    path = local_path()
    if path is None:
        raise OSError("brak katalogu danych aplikacji")
    data = load_local()
    data.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    try:
        os.chmod(tmp, 0o600)                  # token - tylko dla właściciela
    except OSError:
        pass
    os.replace(tmp, path)
    return path


def save_connection(url: str, token: str) -> Path:
    return save_local(url=url.strip().rstrip("/"), token=token.strip())


def load_raw_settings(path: Path = None) -> dict:
    """settings.json + connection.json bez sprawdzania kompletności (np. dla ekranu Ustawienia)."""
    path = path or settings_path()
    settings = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            settings = json.load(f)
    conn = {k: v for k, v in load_local().items() if k in ("url", "token") and isinstance(v, str)}
    settings["url"] = os.environ.get("HA_URL", conn.get("url") or settings.get("url", ""))
    settings["token"] = os.environ.get("HA_TOKEN", conn.get("token") or settings.get("token", ""))
    settings["url"] = settings["url"].strip().rstrip("/")
    settings["token"] = settings["token"].strip()
    return settings


def load_settings(path: Path = None):
    """Zwraca słownik ustawień albo None, gdy brak konfiguracji."""
    settings = load_raw_settings(path)
    if not settings["url"] or not settings["token"] or "WKLEJ" in settings["token"]:
        return None
    return settings
