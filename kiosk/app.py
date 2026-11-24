"""Główna klasa aplikacji."""
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.factory import Factory
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import FadeTransition, ScreenManager

from datetime import date, timedelta

from kiosk import config, device, icons, network
from kiosk.chime import HourChime
from kiosk import voice
from kiosk.widgets.voice_dialog import VoiceDialog
from kiosk.kalbi import KalbiCache
from kiosk.data import mock
from kiosk.ha.provider import HAProvider
from kiosk.ha.settings import load_local, load_settings, save_local, settings_path
from kiosk.ha.tablet import TabletSync
from kiosk.screensaver import DEFAULT_MINUTES, ScreenSaver
from kiosk.screens.battery import COLORS as BATTERY_COLORS, BatteryScreen, overall_status
from kiosk.screens.energy import EnergyScreen
from kiosk.screens.heating import HeatingScreen
from kiosk.screens.switches import SwitchesScreen
from kiosk.screens.kartka import KartkaScreen
from kiosk.screens.settings import SettingsScreen
from kiosk.screens.start import StartScreen

KV_DIR = Path(__file__).parent / "kv"


# ekran -> sekcja podświetlana w bocznym menu
SECTIONS = {"start": "home", "kartka": "home", "energy": "energy", "heating": "heating",
            "battery": "battery", "switches": "switches", "settings": "settings"}
BATTERY_CHECK_SECONDS = 600     # kolor ikony baterii w menu: sprawdzanie co 10 min
NETWORK_CHECK_SECONDS = 10      # ikona Wi-Fi obok zegara
TABLET_BATTERY_SECONDS = 60     # ikona baterii tabletu obok zegara i encja w HA
AUTO_BRIGHTNESS_SECONDS = 2     # automatyczna jasność: odczyt czujnika światła
AUTO_BRIGHTNESS_STEP = 5        # maks. zmiana jasności na krok (płynne przejście)
AUTO_BRIGHTNESS_HA_DELTA = 5    # zmiana (%), od której automatyczna jasność trafia do HA
AUTO_BRIGHTNESS_SMOOTH = 0.3     # wygładzanie odczytu światła (średnia wykładnicza, co 2 s)
AUTO_BRIGHTNESS_DEADBAND = 4    # różnica (%) od celu, poniżej której jasność się nie zmienia


class KioskApp(App):
    title = config.APP_TITLE
    section = StringProperty("home")
    battery_status = StringProperty("unknown")          # ok / warn / low / unknown
    battery_color = ListProperty(list(BATTERY_COLORS["unknown"]))
    # ikony obok zegara: sieć (Wi-Fi) i połączenie z Home Assistant
    wifi_icon = StringProperty("wifi")
    wifi_ok = BooleanProperty(False)
    ha_state = StringProperty("connecting")             # ok / error / connecting / mock
    # bateria tabletu (ikona po lewej stronie zegara; pusty tekst = brak baterii, ikona ukryta)
    tablet_battery_icon = StringProperty("battery-unknown")
    tablet_battery_text = StringProperty("")
    tablet_battery_color = ListProperty(list(config.COLOR_TEXT_DIM))
    tablet_charging = BooleanProperty(False)            # tablet podłączony do ładowania
    tablet_charge_power = StringProperty("")             # moc gniazdka ładowarki, np. "7 W"
    voice_last = StringProperty("")                      # ostatnia odebrana wiadomość głosowa
    app_version = StringProperty("")                    # versionName z APK (nad baterią)
    _last_battery = None                                # ostatni stan baterii wysłany do HA
    # jasność i głośność tabletu 0-100 (ekran Ustawienia, encje input_number w HA)
    tablet_brightness = NumericProperty(100)
    tablet_volume = NumericProperty(50)
    # automatyczna jasność według czujnika światła (input_boolean w HA) i odczyt w luksach
    tablet_auto_brightness = BooleanProperty(False)
    tablet_lux_text = StringProperty("")

    def build(self):
        Window.clearcolor = config.COLOR_BG
        icons.register_font()

        # widgets.kv najpierw - definiuje klasy używane przez pozostałe pliki
        kv_files = sorted(KV_DIR.glob("*.kv"), key=lambda p: p.name != "widgets.kv")
        for kv_file in kv_files:
            Builder.load_file(str(kv_file))

        self.start_screen = StartScreen(name="start")
        sm = ScreenManager(transition=FadeTransition(duration=0.15))
        sm.add_widget(self.start_screen)
        sm.add_widget(SettingsScreen(name="settings"))
        self.kartka_screen = KartkaScreen(name="kartka")
        sm.add_widget(self.kartka_screen)
        self.energy_screen = EnergyScreen(name="energy")
        sm.add_widget(self.energy_screen)
        self.heating_screen = HeatingScreen(name="heating")
        sm.add_widget(self.heating_screen)
        self.battery_screen = BatteryScreen(name="battery")
        sm.add_widget(self.battery_screen)
        self.switches_screen = SwitchesScreen(name="switches")
        sm.add_widget(self.switches_screen)
        self.sm = sm

        # ekrany po lewej, boczne menu z ikonami po prawej
        root = BoxLayout()
        root.add_widget(sm)
        root.add_widget(Factory.NavRail())
        return root

    def on_start(self):
        # kartka z kalendarza: dziś i jutro pobierane w tle (raz na dzień, cache na dysku)
        # na Androidzie ~/.cache nie istnieje - cache w katalogu danych aplikacji
        self.kalbi = KalbiCache(Path(self.user_data_dir) / "kalbi") if self.is_android \
            else KalbiCache()
        if self.is_android:
            self._android_setup()
        self.kalbi.prune()
        Clock.schedule_once(lambda _dt: self.prefetch_kartka(), 10)
        Clock.schedule_interval(lambda _dt: self.prefetch_kartka(), 3600)

        # wygaszanie ekranu po bezczynności, budzenie dotykiem / ruchem (przednia kamera);
        # dopiero wygaszenie zamyka okna, a wybudzenie pokazuje ekran startowy
        self.screensaver = ScreenSaver(on_wake=lambda: self.go_to("start"))
        # wspólna kolejka komunikatów (wiadomości głosowe, ogłoszenia godzin) - po kolei,
        # bez przerywania; rejestrator wiadomości (połączenie z HA w apply_settings)
        self.voice = None
        self.voice_recorder = voice.Recorder()
        self.voice_player = voice.Player()
        # pełne godziny: gong i "Jest godzina ..." (pn-pt 7-22, sb-nd 9-22), także przy
        # wygaszonym ekranie; przełącznik w Ustawieniach
        self.chime = HourChime(self.voice_player, bool(load_local().get("hour_chime", True)))
        self.apply_screen_settings()

        self.check_network()
        Clock.schedule_interval(lambda _dt: self.check_network(), NETWORK_CHECK_SECONDS)

        # jasność i głośność zapisane w aplikacji (local.json); bez zapisu - wartości tabletu
        local = load_local()
        self.set_tablet("brightness", local.get("brightness", device.brightness()), sync=False)
        self.set_tablet("volume", local.get("volume", device.volume()), sync=False)
        self.tablet_sync = None
        self._auto_sent = None
        if device.light_start():
            # domyślnie włączona; wyłączenie (przycisk w Ustawieniach, ruch suwakiem
            # albo pomocnik w HA) zapisuje się w local.json
            self.tablet_auto_brightness = bool(local.get("auto_brightness", True))
            Clock.schedule_interval(lambda _dt: self._auto_brightness_tick(),
                                    AUTO_BRIGHTNESS_SECONDS)
        self.check_tablet_battery()
        # zdarzenia zasilania (ładowarka podłączona / odłączona, zmiana poziomu baterii):
        # ikona przy zegarze i encja w HA od razu, bez czekania na sprawdzenie co minutę
        self._battery_trigger = Clock.create_trigger(lambda _dt: self.check_tablet_battery(), 0.3)
        device.watch_power(self._battery_trigger)
        self.app_version = device.app_version()
        # strażnik systemowy: po awarii aplikacja wraca sama najpóźniej po 15 minutach
        device.start_watchdog()
        # diagnostyka wycieku JNI - tylko gdy na tablecie jest plik-znacznik (adb push)
        from kiosk import jni_probe
        Clock.schedule_once(lambda _dt: jni_probe.maybe_run(self), 20)
        Clock.schedule_interval(lambda _dt: self.check_tablet_battery(), TABLET_BATTERY_SECONDS)

        self.provider = None
        self.settings = None
        self.apply_settings()
        Clock.schedule_interval(lambda _dt: self.check_batteries(), BATTERY_CHECK_SECONDS)

    def screen_settings(self) -> dict:
        local = load_local()
        return {"screen_off_minutes": int(local.get("screen_off_minutes", DEFAULT_MINUTES)),
                "motion_wake": bool(local.get("motion_wake", True))}

    def apply_screen_settings(self):
        cfg = self.screen_settings()
        self.screensaver.configure(cfg["screen_off_minutes"], cfg["motion_wake"])

    def apply_settings(self):
        """(Ponowne) wczytanie ustawień i połączenie z HA - przy starcie i po zapisie
        na ekranie Ustawienia."""
        if self.provider:
            self.provider.stop()
            self.provider = None
        if self.tablet_sync:
            self.tablet_sync.stop()
            self.tablet_sync = None
        if self.voice:
            self.voice.stop()
            self.voice = None
        self.settings = settings = load_settings()
        ents = settings.get("entities", {}) if settings else {}
        self.energy_screen.build(ents.get("energy", {}) if settings else mock.ENERGY)
        self.heating_screen.build(ents.get("heating", {}) if settings else mock.HEATING)
        self.switches_screen.configure(ents.get("switches", {}) if settings
                                       else mock.SWITCH_CONFIG)
        Clock.schedule_once(lambda _dt: self.check_batteries(), 5)
        if settings is None:
            Logger.warning(f"HA: brak konfiguracji ({settings_path()}) - dane przykładowe")
            self.start_screen.status_text = ""
            self.ha_state = "mock"
            Clock.schedule_once(lambda _dt: self.start_screen.set_data(mock.get_data()))
            return
        Logger.info(f"HA: łączenie z {settings['url']}")
        self.ha_state = "connecting"
        provider = HAProvider(settings, self.start_screen.set_data,
                              # status zatrzymanego (starego) połączenia jest ignorowany
                              lambda error: self._on_status(error, provider))
        self.provider = provider
        provider.start()
        # nazwy kalendarzy i możliwość zapisu (lista wydarzeń, formularz)
        provider.fetch_calendars(self._on_calendars)
        # encje tabletu w HA: bateria (sensor), jasność i głośność (input_number)
        self.tablet_sync = TabletSync(settings, self._on_tablet_remote)
        self.tablet_sync.set_battery(device.battery())
        self.tablet_sync.start(int(self.tablet_brightness), int(self.tablet_volume),
                               self.tablet_auto_brightness)
        # wiadomości głosowe: nazwa tabletu z settings.json (tablet_name), domyślnie "Hol"
        self.voice = voice.VoiceLink(settings, settings.get("tablet_name", "Hol"),
                                     voice.cache_dir(), self._on_voice_message)
        self.voice.start()

    @property
    def rooms(self):
        """Lista pomieszczeń z settings.json (entities.rooms) albo przykładowa."""
        if self.settings:
            return self.settings.get("entities", {}).get("rooms", [])
        return mock.ROOMS

    def fetch_states(self, entity_ids, callback):
        """callback({entity_id: {"value", "unit"}}, error)"""
        if self.provider:
            self.provider.fetch_states(entity_ids, callback)
        else:
            values = mock.get_states(entity_ids)
            Clock.schedule_once(lambda _dt: callback(values, None), 0.3)

    def fetch_entities(self, entity_ids, attrs, callback):
        """callback({entity_id: {"state", "attributes"}}, error)"""
        if self.provider:
            self.provider.fetch_entities(entity_ids, attrs, callback)
        else:
            data = mock.get_entities(entity_ids, attrs)
            Clock.schedule_once(lambda _dt: callback(data, None), 0.2)

    # --- kalendarze (kartka, tabela miesiąca, lista wydarzeń, formularz) -------------
    calendar_info = {}              # entity_id -> (nazwa, zapis możliwy)

    def _on_calendars(self, items, error):
        if items:
            self.calendar_info = {eid: (name, writable) for eid, name, writable in items}

    def calendar_name(self, entity_id: str) -> str:
        return self.calendar_info.get(entity_id, ("", False))[0]

    def fetch_events(self, start, end, callback):
        """Wydarzenia z zakresu [start, end) ze wszystkich kalendarzy; callback(events, error)."""
        if self.provider:
            self.provider.fetch_events(start, end, callback)
        else:
            events = [e for e in mock.get_data()["events"] if start <= e["start"] < end]
            Clock.schedule_once(lambda _dt: callback(events, None), 0.2)

    def fetch_writable_calendars(self, callback):
        """Kalendarze z zapisem: callback([(entity_id, nazwa)], error)."""
        def done(items, error):
            if items:
                self._on_calendars(items, None)
            callback([(eid, name) for eid, name, writable in (items or []) if writable], error)
        if self.provider:
            self.provider.fetch_calendars(done)
        else:
            Clock.schedule_once(lambda _dt: done([("calendar.mock", "Przykładowy", True)],
                                                 None), 0.2)

    def refresh_events(self):
        """Po dodaniu wydarzenia: kartka i lista na ekranie startowym od razu z HA."""
        if self.provider:
            self.provider.refresh_now()

    def call_service(self, domain, service, data, callback=None):
        """Wywołanie usługi HA (np. switch.turn_on); callback(result, error)."""
        Logger.info(f"HA: usługa {domain}.{service} {data}")
        if self.provider:
            self.provider.call_service(domain, service, data, callback)
        else:
            result = mock.call_service(domain, service, data)
            if callback:
                Clock.schedule_once(lambda _dt: callback(result, None), 0.2)

    def fetch_switches(self, callback):
        """callback([{"entity_id", "name", "state"}], error)"""
        if self.provider:
            self.provider.fetch_switches(callback)
        else:
            data = mock.get_switches()
            Clock.schedule_once(lambda _dt: callback(data, None), 0.2)

    def check_batteries(self):
        """Lista baterii (1 zapytanie) -> ekran Baterie i kolor ikony w menu."""
        def done(batteries, error):
            if error and batteries is None:
                self.battery_screen.status = f"Brak danych z HA: {error}"
                return
            cfg = (self.settings or {}).get("entities", {}).get("battery", {})
            excluded = set(cfg.get("exclude", []))
            self.battery_screen.names = cfg.get("names", {})
            batteries = [b for b in batteries if b["entity_id"] not in excluded]
            self.battery_screen.status = ""
            self.battery_screen.batteries = batteries
            self.battery_status = overall_status(batteries)
            self.battery_color = list(BATTERY_COLORS[self.battery_status])
        if self.provider:
            self.provider.fetch_batteries(done)
        else:
            Clock.schedule_once(lambda _dt: done(mock.get_batteries(), None), 0.2)

    def fetch_history(self, entity_id, start, end, callback):
        """callback(points, error) - points: [(datetime, float | None)]"""
        if self.provider:
            self.provider.fetch_history(entity_id, start, end, callback)
        else:
            points = mock.get_history(entity_id, start, end)
            Clock.schedule_once(lambda _dt: callback(points, None), 0.3)

    def _on_status(self, error: str, provider=None):
        if provider is not None and provider is not self.provider:
            return
        self.start_screen.status_text = error
        self.ha_state = "error" if error else "ok"

    # --- tablet: bateria, jasność, głośność ----------------------------------------------
    def check_tablet_battery(self):
        info = device.battery()
        if info is None:
            self.tablet_battery_text = ""
            self.tablet_charging = False
        else:
            level = info["level"]
            self.tablet_battery_icon = device.battery_icon(level)
            self.tablet_battery_text = f"{level}%"
            self.tablet_charging = bool(info["charging"])     # błyskawica obok ikony
            self.tablet_battery_color = list(config.COLOR_ERROR if level < 20 else
                                             config.COLOR_HEAT if level < 40 else config.COLOR_OK)
        # do HA od razu tylko zmiana (BATTERY_CHANGED przychodzi często);
        # wątek synchronizacji i tak zapisuje stan baterii co 30 s
        if self.tablet_sync and info != self._last_battery:
            self.tablet_sync.set_battery(info)
        self._last_battery = info

    def set_tablet(self, kind: str, value, sync: bool = True, auto: bool = False):
        """Jasność / głośność tabletu (0-100): ustawia urządzenie, zapisuje w local.json
        i (sync=True) ustawia pomocnika w HA. Ręczna zmiana jasności (suwak, HA)
        wyłącza automatyczną jasność; auto=True = zmiana z czujnika światła."""
        value = int(round(float(value)))
        prop = "tablet_brightness" if kind == "brightness" else "tablet_volume"
        changed = int(getattr(self, prop)) != value
        setattr(self, prop, value)          # najpierw właściwość - suwak nie wywoła pętli
        if kind == "brightness":
            device.set_brightness(value)
        else:
            device.set_volume(value)
        if not changed:
            return
        if kind == "brightness" and not auto and self.tablet_auto_brightness:
            self.set_auto_brightness(False)
        try:
            save_local(**{kind: value})
        except OSError as e:
            Logger.warning(f"Tablet: nie udało się zapisać {kind}: {e}")
        if sync and getattr(self, "tablet_sync", None):
            self.tablet_sync.push(kind, value)

    def _on_tablet_remote(self, kind: str, value):
        """Pomocnik zmieniony w HA (dashboard, automatyzacja) -> tablet."""
        if kind == "charger_power":         # odczyt co cykl - bez logowania
            self.tablet_charge_power = (f"{round(value)} W" if value is not None and value >= 0.5
                                        else "")
            return
        Logger.info(f"HA: tablet {kind} = {value}")
        if kind == "auto_brightness":
            self.set_auto_brightness(value, sync=False)
        else:
            self.set_tablet(kind, value, sync=False)

    def set_auto_brightness(self, enabled: bool, sync: bool = True):
        """Włącza / wyłącza automatyczną jasność (zapis w local.json, pomocnik w HA)."""
        enabled = bool(enabled)
        if enabled == self.tablet_auto_brightness:
            return
        self.tablet_auto_brightness = enabled
        self._auto_sent = None
        try:
            save_local(auto_brightness=enabled)
        except OSError as e:
            Logger.warning(f"Tablet: nie udało się zapisać automatycznej jasności: {e}")
        if sync and getattr(self, "tablet_sync", None):
            self.tablet_sync.push("auto_brightness", enabled)
        if enabled:
            self._auto_brightness_tick()

    def _auto_brightness_tick(self):
        """Odczyt czujnika światła: encja w HA i (gdy włączona) automatyczna jasność."""
        lux = device.light_lux()
        if lux is None:
            return
        self.tablet_lux_text = f"{round(lux)} lx"
        if getattr(self, "tablet_sync", None):
            self.tablet_sync.set_light(lux)
        if not self.tablet_auto_brightness:
            return
        # wygładzanie: cień ręki czy przejście obok tabletu nie migocze jasnością
        avg = getattr(self, "_lux_avg", None)
        self._lux_avg = lux if avg is None else avg + (lux - avg) * AUTO_BRIGHTNESS_SMOOTH
        current = int(self.tablet_brightness)
        target = device.auto_brightness_for(self._lux_avg)
        # strefa martwa: drobne wahania czujnika nie ruszają jasności; zmiana, która się
        # zaczęła, dochodzi płynnie do celu
        if abs(target - current) >= AUTO_BRIGHTNESS_DEADBAND:
            self._auto_moving = True
        if getattr(self, "_auto_moving", False):
            step = max(-AUTO_BRIGHTNESS_STEP, min(AUTO_BRIGHTNESS_STEP, target - current))
            if step:
                self.set_tablet("brightness", current + step, sync=False, auto=True)
            else:
                self._auto_moving = False
        value = int(self.tablet_brightness)
        if self.tablet_sync and (self._auto_sent is None
                                 or abs(value - self._auto_sent) >= AUTO_BRIGHTNESS_HA_DELTA
                                 or (value == target and value != self._auto_sent)):
            self._auto_sent = value
            self.tablet_sync.push("brightness", value)

    def check_network(self):
        st = network.status()
        self.wifi_ok = st["connected"]
        self.wifi_icon = network.icon_for(st)

    def on_stop(self):
        if self.provider:
            self.provider.stop()
        if getattr(self, "tablet_sync", None):
            self.tablet_sync.stop()

    def prefetch_kartka(self):
        """Bez zapytań, gdy kartki są już w cache."""
        today = date.today()
        self.kalbi.prefetch([today, today + timedelta(days=1)])

    def open_kartka(self):
        self.kartka_screen.show(date.today())
        self.go_to("kartka")

    @property
    def is_android(self) -> bool:
        from kivy.utils import platform
        return platform == "android"

    def _android_setup(self):
        """Kiosk na tablecie: ekran nie gaśnie, przyciski tabletu działają systemowo tylko
        na ekranie startowym (_on_key)."""
        Window.bind(on_keyboard=self._on_key)
        Window.softinput_mode = "below_target"   # klawiatura nie zasłania pola tekstowego
        try:
            from android.runnable import run_on_ui_thread  # noqa: dostępne tylko w APK
            from jnius import autoclass

            @run_on_ui_thread
            def keep_screen_on():
                activity = autoclass("org.kivy.android.PythonActivity").mActivity
                flags = autoclass("android.view.WindowManager$LayoutParams")
                activity.getWindow().addFlags(flags.FLAG_KEEP_SCREEN_ON)
            keep_screen_on()
        except Exception as e:      # noqa: BLE001
            Logger.warning(f"Android: nie udało się wyłączyć wygaszania ekranu: {e}")

    # przyciski tabletu: 27 - Wstecz (Esc na PC), 319 i 1073741942 - Menu (Kivy / SDL)
    HARDWARE_KEYS = {27, 319, 1073741942}

    def _on_key(self, _window, key, *_args):
        """Przyciski tabletu (Wstecz, Menu) działają systemowo tylko na ekranie startowym
        bez otwartych okien; na pozostałych ekranach i w oknach nic nie robią - do cofania
        są przyciski na ekranie (Wstecz u góry, menu po prawej)."""
        if key not in self.HARDWARE_KEYS:
            return False
        from kivy.factory import Factory
        dialog_open = any(isinstance(w, Factory.ModalView) for w in Window.children)
        return dialog_open or self.sm.current != "start"

    def nav(self, target: str):
        """Boczne menu: ekran albo akcja (screen_off - wygaszenie, voice - wiadomość głosowa)."""
        if target == "screen_off":
            self.screensaver.blank()
        elif target == "voice":
            VoiceDialog().open()
        elif target:
            self.go_to(target)

    # --- wiadomości głosowe między tabletami (przez HA) ----------------------------
    def _on_voice_message(self, info, path):
        """Nowa wiadomość od innego tabletu: zapowiedź (gong + głos) i nagranie."""
        dur = info.get("duration")
        self.voice_last = (f"od: {info.get('from', '?')}, {info.get('time', '')}"
                           + (f", {dur:.0f} s" if isinstance(dur, (int, float)) else ""))
        self.voice_player.play([voice.INTRO, path])

    def go_to(self, screen_name: str):
        self.sm.current = screen_name
        self.section = SECTIONS.get(screen_name, screen_name)
