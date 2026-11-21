"""Ekran "Ustawienia": adres Home Assistant i token (wpisany albo zeskanowany z kodu QR).

Zapis: local.json w prywatnym katalogu danych aplikacji (kiosk/ha/settings.py),
ma pierwszeństwo przed adresem i tokenem z settings.json. Po zapisie aplikacja
od razu łączy się ponownie (KioskApp.apply_settings) - bez restartu.

Sekcja "Ekran": wygaszanie po bezczynności (minuty, 0 = nigdy) i budzenie ruchem
(kiosk/screensaver.py) - zapisywane i stosowane od razu po każdej zmianie.
"""
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import BooleanProperty, NumericProperty, StringProperty
from kivy.uix.screenmanager import Screen

from kiosk.ha.client import HAClient, HAError
from kiosk.ha.settings import (load_local, load_raw_settings, local_path, save_connection, save_local,
                               settings_path)
from kiosk.widgets.confirm_dialog import ConfirmDialog
from kiosk.widgets.qr_scanner import QRScannerDialog
from kiosk import device


# wybór czasu wygaszania przyciskami -/+ (0 = nigdy)
MINUTE_STEPS = [0, 1, 2, 3, 5, 10, 15, 20, 30, 60]


def minutes_label(minutes: int) -> str:
    return "nigdy" if not minutes else f"{minutes} min"


def check_connection(url: str, token: str) -> str:
    """Zwraca opis serwera (wersja HA) albo rzuca HAError."""
    config = HAClient(url, token, timeout=10)._request("GET", "/api/config")
    name = config.get("location_name") or "Home Assistant"
    return f"{name}, wersja {config.get('version', '?')}"


def validate(url: str, token: str) -> str:
    """Komunikat błędu albo "" gdy dane wyglądają poprawnie."""
    if not url:
        return "Podaj adres Home Assistant."
    if not url.lower().startswith(("http://", "https://")):
        return "Adres musi zaczynać się od http:// albo https://"
    if not token:
        return "Podaj token dostępu."
    if any(c.isspace() for c in token):
        return "Token nie może zawierać spacji ani nowych linii."
    return ""


class SettingsScreen(Screen):
    show_token = BooleanProperty(False)
    busy = BooleanProperty(False)
    dirty = BooleanProperty(False)        # pola zmienione przez użytkownika
    result = StringProperty("")
    result_ok = BooleanProperty(False)
    info = StringProperty("")
    screen_minutes = NumericProperty(5)
    minutes_text = StringProperty("5 min")
    motion_wake = BooleanProperty(True)
    hour_chime = BooleanProperty(True)    # ogłaszanie pełnych godzin
    adb_on = BooleanProperty(False)       # ADB przez sieć nasłuchuje (port 5555)
    adb_text = StringProperty("")

    def on_pre_enter(self, *_):
        if not self.dirty:
            self._load()
        cfg = App.get_running_app().screen_settings()
        self.screen_minutes = cfg["screen_off_minutes"]
        self.motion_wake = cfg["motion_wake"]
        self.hour_chime = App.get_running_app().chime.enabled
        self._update_info()
        self._update_adb()

    def on_screen_minutes(self, *_):
        self.minutes_text = minutes_label(self.screen_minutes)

    # --- ekran: wygaszanie i budzenie ruchem ------------------------------------------
    def change_minutes(self, direction):
        steps = MINUTE_STEPS
        # najbliższa wartość z listy w danym kierunku (obsługuje też wpisane ręcznie)
        if direction > 0:
            new = next((m for m in steps if m > self.screen_minutes), steps[-1])
        else:
            new = next((m for m in reversed(steps) if m < self.screen_minutes), steps[0])
        self.screen_minutes = new
        self._save_screen()

    def toggle_motion(self):
        self.motion_wake = not self.motion_wake
        self._save_screen()

    # --- ogłaszanie pełnych godzin (gong i komunikat) ---------------------------------
    def toggle_chime(self):
        self.hour_chime = not self.hour_chime
        App.get_running_app().chime.enabled = self.hour_chime
        try:
            save_local(hour_chime=self.hour_chime)
        except OSError as e:
            self._show(f"Nie udało się zapisać: {e}", False)

    def test_chime(self):
        App.get_running_app().chime.play()

    def _save_screen(self):
        try:
            save_local(screen_off_minutes=int(self.screen_minutes), motion_wake=self.motion_wake)
        except OSError as e:
            self._show(f"Nie udało się zapisać: {e}", False)
            return
        App.get_running_app().apply_screen_settings()

    def on_leave(self, *_):
        self.show_token = False           # token ukryty przy następnym wejściu

    def _load(self):
        current = load_raw_settings()
        self.ids.url.text = current.get("url", "")
        self.ids.token.text = current.get("token", "")
        self.dirty = False
        self.result = ""

    def _update_info(self):
        conn = local_path()
        source = (f"zapisane w aplikacji ({conn})" if load_local().get("token")
                  else f"z pliku {settings_path()}")
        app = App.get_running_app()
        state = ("łączy się z Home Assistant" if getattr(app, "provider", None)
                 else "brak połączenia - dane przykładowe")
        self.info = f"Ustawienia połączenia: {source}.  Aplikacja {state}."

    def _values(self):
        return self.ids.url.text.strip().rstrip("/"), "".join(self.ids.token.text.split())

    def _show(self, text, ok):
        self.result, self.result_ok = text, ok

    # --- QR -----------------------------------------------------------------------
    def scan_qr(self):
        QRScannerDialog(on_result=self._on_qr).open()

    def _on_qr(self, data: dict):
        if data.get("url"):
            self.ids.url.text = data["url"]
        if data.get("token"):
            self.ids.token.text = data["token"]
        found = " i ".join(n for k, n in (("url", "adres"), ("token", "token")) if data.get(k))
        self._show(f"Odczytano z kodu QR: {found}. Sprawdź połączenie i zapisz.", True)

    # --- sprawdzanie i zapis ----------------------------------------------------
    def test_connection(self, then=None):
        url, token = self._values()
        error = validate(url, token)
        if error:
            self._show(error, False)
            return
        self.busy = True
        self._show("Łączenie…", True)

        def work():
            try:
                text, ok = f"Połączono: {check_connection(url, token)}", True
            except HAError as e:
                text, ok = f"Błąd połączenia: {e}", False
            Clock.schedule_once(lambda _dt: finish(text, ok))

        def finish(text, ok):
            self.busy = False
            self._show(text, ok)
            if then:
                then(ok)

        threading.Thread(target=work, name="ha-settings-check", daemon=True).start()

    def save(self):
        def after_check(ok):
            if ok:
                self._save()
            else:
                ConfirmDialog(
                    title="Zapisać mimo błędu połączenia?",
                    message="Nie udało się połączyć z Home Assistant tymi danymi. "
                            "Możesz je zapisać (np. serwer jest chwilowo niedostępny).",
                    confirm_text="Zapisz",
                    action=self._save).open()
        self.test_connection(then=after_check)

    def _save(self):
        url, token = self._values()
        try:
            save_connection(url, token)
        except OSError as e:
            self._show(f"Nie udało się zapisać: {e}", False)
            return
        self.dirty = False
        App.get_running_app().apply_settings()
        self._show("Zapisano - aplikacja połączyła się ponownie z Home Assistant.", True)
        self._update_info()

    # --- ADB przez sieć i zamknięcie aplikacji ---------------------------------------
    def _update_adb(self):
        self.adb_on = device.adb_network_on()
        self.adb_text = (f"ADB: włączone, port {device.ADB_PORT}" if self.adb_on
                         else "ADB przez sieć: wyłączone")

    def enable_adb(self):
        """Włącza ADB przez sieć; bez uprawnień (pm grant) otwiera Opcje programisty."""
        if device.enable_adb_network():
            self.adb_text = "włączanie ADB…"
            Clock.schedule_once(lambda _dt: self._update_adb(), 3)
        else:
            self._show("Brak uprawnień do włączenia ADB - otwieram Opcje programisty "
                       "(przełącznik „ADB przez sieć”).", False)
            device.open_developer_settings()

    def close_app(self):
        ConfirmDialog(
            title="Zamknąć aplikację?",
            message="Aplikacja zostanie zakończona. HA Kiosk jest ekranem głównym tabletu - "
                    "przycisk Home uruchomi ją ponownie.",
            confirm_text="Zamknij",
            action=device.kill_app).open()
