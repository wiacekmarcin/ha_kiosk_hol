"""Tablet: bateria, jasność ekranu i głośność (Android przez pyjnius).

Jasność = jasność okna aplikacji (WindowManager.LayoutParams.screenBrightness) - działa
bez specjalnych uprawnień, bo kiosk jest zawsze na pierwszym planie. Głośność =
strumień multimediów (AudioManager.STREAM_MUSIC).

Na komputerze nie ma czego sterować: wartości są tylko zapamiętywane, żeby ekran
Ustawienia i encje w HA działały tak samo (bez efektu fizycznego), a bateria jest
niedostępna (None - ikona obok zegara jest wtedy ukryta).
"""
from kivy.logger import Logger
from kivy.utils import platform

ANDROID = platform == "android"
STREAM_MUSIC = 3                # android.media.AudioManager.STREAM_MUSIC

_brightness = None              # 0-100 ustawione w aplikacji; None = jasność systemowa
_desktop_volume = 50


def _activity():
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity").mActivity


def _clamp(value, low, high) -> int:
    return max(low, min(high, int(round(float(value)))))


# --- bateria --------------------------------------------------------------------------
def battery():
    """{"level": 0-100, "charging": bool, "temperature": °C | None} albo None."""
    if not ANDROID:
        return None
    try:
        from jnius import autoclass
        Intent = autoclass("android.content.Intent")
        IntentFilter = autoclass("android.content.IntentFilter")
        BatteryManager = autoclass("android.os.BatteryManager")
        # rozgłoszenie "sticky": registerReceiver(null, ...) zwraca ostatni stan baterii
        intent = _activity().registerReceiver(None, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
        if intent is None:
            return None
        level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, 100) or 100
        status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        temp = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, -1)
        if level < 0:
            return None
        charging = status in (BatteryManager.BATTERY_STATUS_CHARGING,
                              BatteryManager.BATTERY_STATUS_FULL)
        return {"level": round(level * 100 / scale), "charging": charging,
                "temperature": temp / 10 if temp > 0 else None}
    except Exception as e:      # noqa: BLE001
        Logger.warning(f"Tablet: nie udało się odczytać baterii: {e}")
        return None


def battery_icon(level: int) -> str:
    """Ikona MDI dla poziomu naładowania (battery-outline ... battery)."""
    if level >= 95:
        return "battery"
    if level < 5:
        return "battery-outline"
    return f"battery-{max(10, level // 10 * 10)}"


# --- jasność --------------------------------------------------------------------------
def brightness() -> int:
    """Jasność 0-100 ustawiona w aplikacji; przed pierwszym ustawieniem - systemowa."""
    if _brightness is not None:
        return _brightness
    if ANDROID:
        try:
            from jnius import autoclass
            system = autoclass("android.provider.Settings$System")
            value = system.getInt(_activity().getContentResolver(), system.SCREEN_BRIGHTNESS)
            return _clamp(value * 100 / 255, 1, 100)
        except Exception as e:  # noqa: BLE001
            Logger.warning(f"Tablet: nie udało się odczytać jasności systemowej: {e}")
    return 100


def window_brightness():
    """Jasność okna 0.01-1.0 dla ekranu wybudzonego; None = systemowa."""
    return None if _brightness is None else _brightness / 100


def set_brightness(percent):
    """Ustawia jasność ekranu (1-100). Przy wygaszonym ekranie tylko zapamiętuje -
    zostanie użyta przy wybudzeniu."""
    global _brightness
    _brightness = _clamp(percent, 1, 100)
    from kivy.app import App
    saver = getattr(App.get_running_app(), "screensaver", None)
    if saver is not None and saver.blanked:
        return
    from kiosk.screensaver import set_brightness as set_window_brightness
    set_window_brightness(window_brightness())


# --- głośność -------------------------------------------------------------------------
def _audio():
    from jnius import autoclass
    context = autoclass("android.content.Context")
    return _activity().getSystemService(context.AUDIO_SERVICE)


def volume() -> int:
    """Głośność multimediów 0-100."""
    if not ANDROID:
        return _desktop_volume
    try:
        audio = _audio()
        top = audio.getStreamMaxVolume(STREAM_MUSIC) or 1
        return _clamp(audio.getStreamVolume(STREAM_MUSIC) * 100 / top, 0, 100)
    except Exception as e:      # noqa: BLE001
        Logger.warning(f"Tablet: nie udało się odczytać głośności: {e}")
        return 0


def set_volume(percent):
    """Ustawia głośność multimediów (0-100); tablet ma kilkanaście stopni - zaokrąglenie."""
    global _desktop_volume
    percent = _clamp(percent, 0, 100)
    if not ANDROID:
        _desktop_volume = percent
        return
    try:
        audio = _audio()
        top = audio.getStreamMaxVolume(STREAM_MUSIC) or 1
        audio.setStreamVolume(STREAM_MUSIC, round(percent * top / 100), 0)
    except Exception as e:      # noqa: BLE001
        Logger.warning(f"Tablet: nie udało się zmienić głośności: {e}")


# --- czujnik światła (ROHM BH1733 w GT-P5210) -----------------------------------------
_light_listener = None          # referencja trzymana, żeby Java nie straciła słuchacza


def light_start() -> bool:
    """Włącza odczyt czujnika światła; False = brak czujnika albo komputer."""
    global _light_listener
    if not ANDROID or _light_listener is not None:
        return _light_listener is not None
    try:
        from jnius import PythonJavaClass, autoclass, java_method

        class LightListener(PythonJavaClass):
            __javainterfaces__ = ["android/hardware/SensorEventListener"]
            __javacontext__ = "app"

            def __init__(self):
                super().__init__()
                self.lux = None

            @java_method("(Landroid/hardware/SensorEvent;)V")
            def onSensorChanged(self, event):
                self.lux = float(event.values[0])

            @java_method("(Landroid/hardware/Sensor;I)V")
            def onAccuracyChanged(self, sensor, accuracy):
                pass

        context = autoclass("android.content.Context")
        sensor_cls = autoclass("android.hardware.Sensor")
        manager_cls = autoclass("android.hardware.SensorManager")
        manager = _activity().getSystemService(context.SENSOR_SERVICE)
        sensor = manager.getDefaultSensor(sensor_cls.TYPE_LIGHT)
        if sensor is None:
            Logger.info("Tablet: brak czujnika światła")
            return False
        listener = LightListener()
        manager.registerListener(listener, sensor, manager_cls.SENSOR_DELAY_NORMAL)
        _light_listener = listener
        Logger.info(f"Tablet: czujnik światła {sensor.getName()}")
        return True
    except Exception as e:      # noqa: BLE001
        Logger.warning(f"Tablet: nie udało się włączyć czujnika światła: {e}")
        return False


def light_lux():
    """Ostatni odczyt czujnika światła w luksach albo None."""
    return None if _light_listener is None else _light_listener.lux


def auto_brightness_for(lux: float) -> int:
    """Jasność 0-100 dla oświetlenia: skala logarytmiczna (oko tak odbiera światło).
    0 lx -> 10 %, 10 lx -> 40 %, 100 lx -> 70 %, od 1000 lx -> 100 %."""
    import math
    return _clamp(10 + 30 * math.log10(max(0.0, lux) + 1), 10, 100)


# --- ADB przez sieć i zamknięcie aplikacji (ekran Ustawienia) -------------------------
ADB_PORT = 5555


def adb_network_on() -> bool:
    """Czy adbd nasłuchuje na porcie sieciowym (ADB przez sieć włączone)."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.3)
    try:
        return sock.connect_ex(("127.0.0.1", ADB_PORT)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def enable_adb_network() -> bool:
    """Włącza debugowanie i ADB przez sieć (LineageOS: ustawienie adb_port w cmsettings).

    Wymaga uprawnień nadanych raz przez ADB:
      pm grant pl.mieszkanie.hakiosk android.permission.WRITE_SECURE_SETTINGS
      pm grant pl.mieszkanie.hakiosk cyanogenmod.permission.WRITE_SECURE_SETTINGS
    Bez nich zwraca False - wtedy wołający otwiera Opcje programisty."""
    if not ANDROID:
        return False
    try:
        from jnius import autoclass
        resolver = _activity().getContentResolver()
        settings_global = autoclass("android.provider.Settings$Global")
        settings_global.putInt(resolver, "adb_enabled", 1)
        uri = autoclass("android.net.Uri").parse("content://cmsettings/secure")
        values = autoclass("android.content.ContentValues")()
        values.put("name", "adb_port")
        values.put("value", str(ADB_PORT))
        resolver.insert(uri, values)
        return True
    except Exception as e:      # noqa: BLE001 - brak uprawnień / inny system
        Logger.warning(f"Tablet: nie udało się włączyć ADB przez sieć: {e}")
        return False


def open_developer_settings():
    """Otwiera Opcje programisty Androida (tam ręczny przełącznik ADB przez sieć)."""
    if not ANDROID:
        return
    try:
        from jnius import autoclass
        intent_cls = autoclass("android.content.Intent")
        settings = autoclass("android.provider.Settings")
        intent = intent_cls(settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS)
        intent.addFlags(intent_cls.FLAG_ACTIVITY_NEW_TASK)
        _activity().startActivity(intent)
    except Exception as e:      # noqa: BLE001
        Logger.warning(f"Tablet: nie udało się otworzyć Opcji programisty: {e}")


def kill_app():
    """Kończy proces aplikacji. HA Kiosk jest ekranem głównym - przycisk Home
    (albo Android sam) uruchomi go ponownie."""
    Logger.info("Kiosk: zamykanie aplikacji na żądanie")
    if ANDROID:
        try:
            from jnius import autoclass
            process = autoclass("android.os.Process")
            process.killProcess(process.myPid())
        except Exception as e:  # noqa: BLE001
            Logger.warning(f"Kiosk: nie udało się zakończyć procesu: {e}")
    from kivy.app import App
    App.get_running_app().stop()
