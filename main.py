"""Punkt wejścia aplikacji kiosku (ekran 1280x800).

Uruchomienie:
    python main.py              # okno 1280x800 (tryb deweloperski)
    python main.py --fullscreen # pełny ekran, bez kursora (tryb kiosku)
Na Androidzie (APK z buildozera) zawsze pełny ekran.
"""
import argparse
import os
import sys

# python-for-android ustawia ANDROID_ARGUMENT / ANDROID_PRIVATE
IS_ANDROID = "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ


def parse_args():
    parser = argparse.ArgumentParser(description="HA Kiosk")
    parser.add_argument("--fullscreen", action="store_true",
                        help="uruchom w trybie pełnoekranowym (kiosk)")
    # Kivy ma własny parser argumentów - przekazujemy mu tylko to, czego nie znamy.
    args, rest = parser.parse_known_args()
    sys.argv = [sys.argv[0]] + rest
    return args


def configure_kivy(fullscreen: bool):
    # Konfiguracja MUSI nastąpić przed importem czegokolwiek z kivy poza Config.
    os.environ.setdefault("KIVY_NO_ARGS", "1")
    if IS_ANDROID:
        # układ jest projektowany w pikselach dla 1280x800 - bez skalowania DPI
        # (inaczej czcionki w "sp" rosną względem stałych wysokości elementów)
        os.environ.setdefault("KIVY_METRICS_DENSITY", "1")
        os.environ.setdefault("KIVY_METRICS_FONTSCALE", "1")
        fullscreen = True
    from kivy.config import Config
    from kiosk.config import SCREEN_WIDTH, SCREEN_HEIGHT

    Config.set("graphics", "width", str(SCREEN_WIDTH))
    Config.set("graphics", "height", str(SCREEN_HEIGHT))
    Config.set("graphics", "resizable", "0")
    Config.set("graphics", "fullscreen", "auto" if fullscreen else "0")
    Config.set("graphics", "borderless", "1" if fullscreen else "0")
    Config.set("graphics", "show_cursor", "0" if fullscreen else "1")
    Config.set("kivy", "exit_on_escape", "0" if fullscreen else "1")
    Config.set("input", "mouse", "mouse,disable_multitouch")


def main():
    args = parse_args()
    configure_kivy(args.fullscreen)

    from kiosk.app import KioskApp
    KioskApp().run()


if __name__ == "__main__":
    main()
