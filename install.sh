#!/usr/bin/env bash
# Instalacja ostatnio zbudowanego APK (bin/<nazwa>-<wersja>-*-release.apk) na tablecie przez
# adb w sieci - uruchamiać w WSL: ./install.sh [adres:port] [opcje]
#   bez adresu: DEFAULT_DEV poniżej; gdy pusty - port debugowania bezprzewodowego tabletu
#   MDNS_IP wyszukany przez "adb mdns services" (Android 11+, port zmienia się po restarcie)
# Po instalacji: zgoda na mikrofon, aplikacja jako ekran główny, piosenki (projekty z ekranem
# Muzyka - tylko nowe i zmienione pliki), uruchomienie.
# Opcje:
#   --reinstall  gdy na tablecie jest wersja z innym podpisem: odinstaluj i zainstaluj od nowa
#                (znikają dane aplikacji na tablecie, także wgrane pliki)
#   --no-music   bez wgrywania piosenek
#   --no-start   bez uruchamiania aplikacji
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"
ADB=${ADB:-/mnt/c/KreionAI/aae_ai_local_data/misc/android_tools/platform-tools/adb.exe}
DEFAULT_DEV=${DEFAULT_DEV:-192.168.10.252:5555}    # tablet w holu (Galaxy Tab 3, LineageOS)
MDNS_IP=${MDNS_IP:-""}
MUSIC_SRC=${MUSIC_SRC:-/mnt/c/KreionAI/aae_ai_local_data/media/audio/muzyka_dzieci}

DEV=""
REINSTALL=0
MUSIC=1
START=1
for arg in "$@"; do
  case $arg in
    --reinstall) REINSTALL=1 ;;
    --no-music) MUSIC=0 ;;
    --no-start) START=0 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    -*) echo "Nieznana opcja: $arg"; exit 2 ;;
    *) DEV=$arg ;;
  esac
done

NAME=$(sed -n 's/^package.name *= *//p' buildozer.spec)
DOMAIN=$(sed -n 's/^package.domain *= *//p' buildozer.spec)
VER=$(sed -n 's/^version *= *//p' buildozer.spec)
PKG=$DOMAIN.$NAME
APK=$(ls -t bin/$NAME-$VER-*-release.apk 2>/dev/null | head -1)
[ -n "$APK" ] || { echo "Brak bin/$NAME-$VER-*-release.apk - najpierw ./build.sh"; exit 3; }

if [ -z "$DEV" ]; then
  DEV=$DEFAULT_DEV
  if [ -z "$DEV" ] && [ -n "$MDNS_IP" ]; then
    DEV=$(timeout 15 "$ADB" mdns services 2>/dev/null | tr -d '\r' | grep _adb-tls-connect \
          | grep -oE "${MDNS_IP//./\\.}:[0-9]+" | head -1)
    [ -n "$DEV" ] || { echo "Nie znalazłem $MDNS_IP w mDNS - włącz debugowanie bezprzewodowe"\
      "albo podaj adres:port"; exit 4; }
  fi
  [ -n "$DEV" ] || { echo "Podaj adres tabletu: ./install.sh adres:port"; exit 2; }
fi
"$ADB" connect "$DEV" > /dev/null 2>&1
if ! timeout 10 "$ADB" -s "$DEV" get-state 2>/dev/null | grep -q device; then
  echo "Tablet $DEV niedostępny (włączony? debugowanie przez sieć? inny port?)"; exit 4
fi

echo "== $PKG $VER -> $DEV"
APKW=$(wslpath -w "$APK")
OUT=$(timeout 300 "$ADB" -s "$DEV" install -r "$APKW" 2>&1)
if ! echo "$OUT" | grep -q Success; then
  if echo "$OUT" | grep -q INSTALL_FAILED_UPDATE_INCOMPATIBLE; then
    if [ "$REINSTALL" = 1 ]; then
      echo "Inny podpis - odinstalowanie i instalacja od nowa"
      timeout 60 "$ADB" -s "$DEV" uninstall "$PKG"
      OUT=$(timeout 300 "$ADB" -s "$DEV" install "$APKW" 2>&1)
    else
      echo "Na tablecie jest wersja z innym podpisem. Uruchom: ./install.sh $DEV --reinstall"; exit 5
    fi
  fi
  echo "$OUT" | grep -q Success || { echo "$OUT" | tail -3; echo "INSTALACJA NIE UDAŁA SIĘ"; exit 5; }
fi
echo "INSTALL_OK"
timeout 20 "$ADB" -s "$DEV" shell pm grant "$PKG" android.permission.RECORD_AUDIO 2>/dev/null
if ! timeout 20 "$ADB" -s "$DEV" shell pm grant "$PKG" android.permission.WRITE_SECURE_SETTINGS \
  2>/dev/null; then
  echo "UWAGA: nie przyznano WRITE_SECURE_SETTINGS; Android nie zsynchronizuje czasu systemowego." >&2
fi
timeout 20 "$ADB" -s "$DEV" shell pm grant "$PKG" cyanogenmod.permission.WRITE_SECURE_SETTINGS 2>/dev/null
timeout 20 "$ADB" -s "$DEV" shell cmd package set-home-activity "$PKG/org.kivy.android.PythonActivity" \
  > /dev/null 2>&1
PUSH=../ha_kiosk_dzieci/tools/push_music.sh
if [ "$MUSIC" = 1 ] && [ -d dzieci/music ] && [ -f "$PUSH" ] && [ -d "$MUSIC_SRC" ]; then
  echo "== piosenki"
  ADB="$ADB" timeout 900 bash "$PUSH" "$DEV" "$PKG" "$MUSIC_SRC" 2>&1 | grep -E 'PUSH_OK|error|files pushed'
fi
if [ "$START" = 1 ]; then
  timeout 20 "$ADB" -s "$DEV" shell am force-stop "$PKG"
  timeout 30 "$ADB" -s "$DEV" shell am start -n "$PKG/org.kivy.android.PythonActivity" > /dev/null 2>&1
fi
echo "GOTOWE: $PKG $(timeout 20 "$ADB" -s "$DEV" shell dumpsys package "$PKG" | sed -n 's/.*versionName=//p' | head -1)"
