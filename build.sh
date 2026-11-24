#!/usr/bin/env bash
# Budowanie APK (release, podpisany kluczem kiosków) - uruchamiać w WSL z katalogu projektu
# albo skądkolwiek: ./build.sh
#   1. przygotowanie: sync_kiosk.sh (wspólny kod z ha_kiosk i settings.json), jeśli jest
#   2. test dymny w wirtualnym ekranie (tools/smoke_test.py), jeśli jest
#   3. buildozer android release -> bin/<nazwa>-<wersja>-<arch>-release.apk
# Opcje: --no-test (bez testu dymnego), --clean (buildozer android clean przed budową).
# Wymaga: venv ../kioskha/.venv (buildozer), klucz ~/.android/hakiosk-release.keystore
# i hasło w ~/.android/hakiosk-release.haslo, xvfb-run do testu.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
TABLET_NAME=${TABLET_NAME:-""}         # nazwa tabletu dla sync_kiosk.sh (pusta - domyślna)
VENV=${VENV:-../kioskha/.venv}
KEYSTORE=${KEYSTORE:-$HOME/.android/hakiosk-release.keystore}
PASSFILE=${PASSFILE:-$HOME/.android/hakiosk-release.haslo}

TEST=1
CLEAN=0
for arg in "$@"; do
  case $arg in
    --no-test) TEST=0 ;;
    --clean) CLEAN=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Nieznana opcja: $arg (--no-test, --clean)"; exit 2 ;;
  esac
done

NAME=$(sed -n 's/^package.name *= *//p' buildozer.spec)
VER=$(sed -n 's/^version *= *//p' buildozer.spec)
[ -x "$VENV/bin/buildozer" ] || { echo "Brak buildozera w $VENV"; exit 3; }
[ -f "$KEYSTORE" ] && [ -f "$PASSFILE" ] || { echo "Brak klucza $KEYSTORE albo hasła $PASSFILE"; exit 3; }
export PATH="$VENV/bin:$PATH"
export P4A_RELEASE_KEYSTORE="$KEYSTORE"
export P4A_RELEASE_KEYSTORE_PASSWD="$(cat "$PASSFILE")"
export P4A_RELEASE_KEYALIAS=hakiosk
export P4A_RELEASE_KEYALIAS_PASSWD="$P4A_RELEASE_KEYSTORE_PASSWD"

echo "== $NAME $VER: przygotowanie"
if [ -x sync_kiosk.sh ]; then
  ./sync_kiosk.sh "$TABLET_NAME"
fi
python3 -m py_compile main.py

if [ "$TEST" = 1 ] && [ -f tools/smoke_test.py ]; then
  echo "== test dymny"
  if ! timeout 400 xvfb-run -a -s "-screen 0 1280x800x24" "$VENV/bin/python" tools/smoke_test.py \
      > /tmp/${NAME}_smoke.log 2>&1 || ! grep -q SMOKE_OK /tmp/${NAME}_smoke.log; then
    grep -A25 SMOKE_FAIL /tmp/${NAME}_smoke.log || tail -30 /tmp/${NAME}_smoke.log
    echo "TEST DYMNY NIE PRZESZEDŁ - APK nie zbudowany"; exit 4
  fi
  echo "SMOKE_OK"
fi

[ "$CLEAN" = 1 ] && buildozer android clean
echo "== buildozer android release"
T0=$(date +%s)
LOG=/tmp/${NAME}_release.log
buildozer android release > "$LOG" 2>&1 || true
APK=$(ls -t bin/$NAME-$VER-*-release.apk 2>/dev/null | head -1 || true)
if [ -z "$APK" ] || [ "$(stat -c %Y "$APK")" -lt "$T0" ]; then
  sed 's/\x1b\[[0-9;]*[A-Za-z]//g' "$LOG" | grep -vE 'DEBUG|^\s*$' | tail -n 25
  echo "BUDOWA NIE UDAŁA SIĘ (pełny log: $LOG)"; exit 5
fi
echo "APK_OK $APK ($(( $(date +%s) - T0 )) s) - instalacja: ./install.sh"
