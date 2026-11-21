# HA Kiosk

Aplikacja Kivy na ekran dotykowy 1280x800.

## Instalacja

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Uruchomienie

```bash
python main.py              # okno 1280x800
python main.py --fullscreen # tryb kiosku: pełny ekran, bez kursora, ESC nie zamyka
```

## Połączenie z Home Assistant

1. W HA: profil użytkownika → Bezpieczeństwo → *Tokeny długoterminowe* → Utwórz token.
2. `cp settings.example.json settings.json` i wpisz `url` oraz `token`
   (`settings.json` jest w `.gitignore`; token można też podać jako zmienną `HA_TOKEN`).
3. `python3 tools/list_entities.py` wypisze encje pogody, kalendarzy, temperatury i wilgotności.
   Wpisz wybrane `entity_id` do sekcji `entities` w `settings.json`.

Bez `settings.json` aplikacja pokazuje dane przykładowe (`kiosk/data/mock.py`).
Odświeżanie: czujniki/pogoda/słońce co 30 s, prognoza i kalendarz co 5 min.

Kartka z kalendarza (dotknięcie zegara) pochodzi z kalbi.pl: każdy dzień pobierany raz
i trzymany w `~/.cache/ha_kiosk/kalbi/` (14 dni); dziś i jutro pobierane w tle.
Godziny słońca/księżyca na kartce są dla Warszawy (domyślna lokalizacja kalbi.pl).

Menu po prawej: Dom (ekran startowy) i Błyskawica (rozdzielnia elektryczna, sekcja
`entities.energy` w `settings.json`). Ekran energii i okno pomieszczeń pobierają wszystkie
wartości jednym zapytaniem (`/api/template`), odświeżanie tylko gdy są widoczne.

Ogrzewanie (ikona grzejnika, `entities.heating`): termostaty (+/- temperatury zadanej, wł./wył.)
i ogrzewanie podłogowe (główny przełącznik, pompa, strefy). Sterowanie wywołuje usługi HA:
`climate.set_temperature`, `climate.set_hvac_mode`, `switch.turn_on/turn_off`.

Baterie (ikona baterii, `entities.battery`): wszystkie sensory z `device_class: battery`.
Kolor ikony w menu: czerwony gdy któraś < 30 %, żółty gdy któraś < 60 %, inaczej zielony
(sprawdzanie co 10 min; niedostępne nie wpływają na kolor). `exclude` - lista encji do pominięcia,
`names` - własne nazwy {entity_id: nazwa}.

Włączniki (ikona przełącznika, `entities.switches`): wszystkie `switch.*` i `light.*` poza
ustawieniami technicznymi (blokady rodzicielskie, ustawienia głowic, tabletu - `exclude_patterns`).
`sections` - zakładki u góry (lista encji, `"rest": true` = pozostałe, `"on": true` = włączone);
`"protect": "all"` albo lista encji - przełączenie wymaga potwierdzenia (kłódka na kafelku),
`readonly` - tylko podgląd, `exclude` - ukryte encje, `names` - własne nazwy.

Obok zegara: ikona sieci (zielona = jest połączenie; na Androidzie siła sygnału Wi-Fi,
sprawdzanie co 10 s) i pod nią ikona Home Assistant (zielona = ostatnie pobranie danych
udane, czerwona = błąd, szara = łączenie albo dane przykładowe).

Ustawienia (trzy kropki na dole menu): adres HA i token - wpisany, wklejony albo zeskanowany
kamerą z kodu QR (sam token, sam adres, `{"url": …, "token": …}` albo `adres?token=…`).
„Sprawdź połączenie” pyta `GET /api/config`; „Zapisz i połącz” zapisuje `local.json`
w prywatnym katalogu danych aplikacji (prawa 0600; na komputerze `~/.config/kiosk/`)
i od razu łączy się ponownie. Zapisany adres/token ma pierwszeństwo przed `settings.json`
(listę encji nadal bierze z `settings.json`). Odczyt QR: `pyzbar` (w APK) albo OpenCV.

Ekran (też w Ustawieniach, zapis od razu do `local.json`): wygaszanie po bezczynności
(domyślnie 5 min, 0 = nigdy) i budzenie ruchem. Galaxy Tab 3 10.1 nie ma czujnika ruchu -
ruch wykrywa przednia kamera (porównanie klatek 320x240, działa tylko przy wygaszonym ekranie).
Wygaszenie = czarny ekran + minimalne podświetlenie (prawdziwe wyłączenie wyświetlacza
zatrzymałoby aplikację i kamerę). Ruch albo dotyk budzi ekran i pokazuje stronę startową;
dotyk budzący niczego nie klika.

## Struktura

```
main.py                 # konfiguracja okna (Config) + start aplikacji
kiosk/
  config.py             # rozdzielczość, kolory, stałe
  app.py                # KioskApp: ładowanie .kv, ScreenManager, nawigacja
  screens/              # klasy ekranów (logika)
  icons.py              # ikony MDI (font w assets/fonts)
  weather_icons.py      # kolorowe ikony pogody Meteocons (assets/weather, MIT)
  kalbi.py              # kartka z kalendarza z kalbi.pl: parser + cache (~/.cache/ha_kiosk/kalbi)
  pl.py                 # polskie daty i liczby
  data/mock.py          # dane przykładowe (gdy brak settings.json)
  ha/                   # klient REST HA + wątek pobierający dane
  kv/                   # wygląd: *.kv ładowane automatycznie, root.kv.layout = korzeń
assets/                 # ikony, czcionki, obrazy
```

Nowy ekran: dodaj klasę w `kiosk/screens/`, plik `kiosk/kv/<nazwa>.kv`
z regułą `<NazwaScreen>:` i zarejestruj go w `KioskApp.build()`.

## Licencje zasobów

- `assets/fonts/materialdesignicons-webfont.ttf` – [Material Design Icons](https://pictogrammers.com/library/mdi/) (Apache 2.0)
- `assets/weather/*.png` – [Meteocons](https://github.com/basmilius/weather-icons) Bas Milius (MIT, `assets/weather/LICENSE`),
  PNG wygenerowane ze statycznych SVG `@bybas/weather-icons@2.0.0` (`design/fill/export`)

## Android (APK)

Budowanie (buildozer, Linux):

```bash
export JAVA_HOME=$HOME/.local/jdk-17
export PATH=$JAVA_HOME/bin:$HOME/.local/bin:$HOME/.local/buildozer-venv/bin:$PATH
buildozer android debug          # wynik: bin/hakiosk-0.1-x86-debug.apk
```

Konfiguracja w `buildozer.spec`: Android 7.1+ (minapi 21), architektura `armeabi-v7a`,
poziomo, pełny ekran, ekran nie gaśnie, "Wstecz" wraca na ekran startowy.

**`settings.json` (z tokenem HA) jest wbudowany w APK - nie udostępniaj pliku APK.**
Nowszy plik można wgrać bez przebudowy (ma pierwszeństwo przed wbudowanym):

```bash
adb push settings.json /sdcard/Android/data/pl.mieszkanie.hakiosk/files/settings.json
```

Instalacja: `adb install -r bin/hakiosk-0.1-x86-debug.apk`
(albo skopiuj APK na tablet i zainstaluj, zezwalając na "nieznane źródła").
