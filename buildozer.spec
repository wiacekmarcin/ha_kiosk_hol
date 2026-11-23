[app]
title = HA Kiosk
package.name = hakiosk
package.domain = pl.mieszkanie
version = 0.28

source.dir = .
# ogg: nagrania pełnych godzin (assets/sounds)
source.include_exts = py,png,kv,ttf,json,ogg
# settings.json (z tokenem HA) jest celowo WBUDOWANY w APK - nie udostępniaj pliku APK.
# Nowszy settings.json można wgrać bez przebudowy (ma pierwszeństwo przed wbudowanym):
#   adb push settings.json /sdcard/Android/data/pl.mieszkanie.hakiosk/files/settings.json
source.exclude_dirs = example, tools, bin, .buildozer, __pycache__, .venv, venv
source.exclude_patterns = settings.example.json, README.md, buildozer.spec

# libzbar + pyzbar: skanowanie kodu QR z tokenem (ekran Ustawienia)
requirements = python3,kivy==2.3.1,requests,urllib3,certifi,charset-normalizer,idna,openssl,libzbar,pyzbar

orientation = landscape
fullscreen = 1

# --- Android ---
# WRITE_SECURE_SETTINGS (Android i LineageOS): przycisk "Włącz ADB przez sieć" w Ustawieniach;
# nadawane raz przez ADB: pm grant pl.mieszkanie.hakiosk <uprawnienie>
android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, WAKE_LOCK, CAMERA, RECORD_AUDIO, WRITE_SECURE_SETTINGS, cyanogenmod.permission.WRITE_SECURE_SETTINGS
# Android 7.1 = API 25; minimalne API 21, docelowe 33
android.api = 33
android.minapi = 21
android.ndk_api = 21
# Galaxy Tab 3 10.1 (GT-P5210) = Intel Atom Z2560 -> x86, nie ARM
android.archs = x86
# licencja Android SDK zaakceptowana przez właściciela projektu
android.accept_sdk_license = True
# token w settings.json - bez kopii zapasowych aplikacji
android.allow_backup = False
android.wakelock = True
# aplikacja jako ekran główny (launcher): start po włączeniu tabletu i po przycisku Home
android.home_app = True
# wersja wydaniowa jako APK (domyślnie buildozer robi AAB dla Sklepu Play)
android.release_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 1
