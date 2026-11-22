"""Diagnostyka wycieku odwołań JNI (local reference table overflow, max 512).

Uruchamiana tylko, gdy istnieje plik-znacznik PROBE_FLAG (wgrywany przez adb push).
Każdą podejrzaną funkcję wywołuje wielokrotnie na głównym wątku i zapisuje postęp
do pliku PROBE_LOG (logcat gubi wpisy przy dużym ruchu). Funkcja, przy której
aplikacja padnie, zostawia odwołania; licznik wywołań pokazuje tempo wycieku.
"""
import os
import time

from kivy.clock import Clock
from kivy.logger import Logger

DIR = "/sdcard/Android/data/pl.mieszkanie.hakiosk/files/"
PROBE_FLAG = DIR + "jni_probe"
PROBE_LOG = DIR + "jni_probe.log"
REPEAT = 1500


def _log(text: str):
    Logger.info(f"JNIPROBE: {text}")
    with open(PROBE_LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {text}\n")
        f.flush()
        os.fsync(f.fileno())


def _tests(app):
    # 22.11: network, battery, volume, app_version i adb_network_on przeszły po 1500
    # wywołań; padało set_brightness (~450 wywołań) - po poprawce sprawdzane jako pierwsze
    from kiosk import device, network
    from kiosk.screensaver import set_brightness
    return [
        ("screensaver.set_brightness", lambda: set_brightness(0.6), REPEAT),
        ("chime.play", lambda: app.chime.play(12), 60),
        ("network.status", network.status, 300),
        ("device.battery", device.battery, 300),
    ]


def maybe_run(app):
    if not os.path.exists(PROBE_FLAG):
        return
    os.remove(PROBE_FLAG)
    _log("start")
    tests = _tests(app)
    state = {"i": 0}

    def step(_dt):
        if state["i"] >= len(tests):
            camera_cycles(app)
            return
        name, fn, repeat = tests[state["i"]]
        state["i"] += 1
        _log(f"test {name} x{repeat}")
        for n in range(1, repeat + 1):
            try:
                fn()
            except Exception as e:      # noqa: BLE001
                _log(f"{name} wyjątek {e}")
                break
            if n % 100 == 0:
                _log(f"{name} {n}")
        _log(f"OK {name}")
        Clock.schedule_once(step, 1)

    Clock.schedule_once(step, 3)


def camera_cycles(app, count: int = 120):
    saver = app.screensaver
    state = {"n": 0}

    def cycle(_dt):
        if state["n"] >= count:
            _log("OK kamera - koniec testów")
            saver.wake("koniec testu")
            return
        state["n"] += 1
        _log(f"kamera cykl {state['n']}")
        saver.blank()
        Clock.schedule_once(lambda _d: (saver.wake("test"), Clock.schedule_once(cycle, 0.3)), 1.2)

    _log(f"test kamera (wygaszenie i wybudzenie) x{count}")
    Clock.schedule_once(cycle, 1)
