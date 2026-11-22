# HA Kiosk - podsumowanie prac

Stan na: 22 listopada 2026, wersja aplikacji **0.22**.
Repozytorium: https://github.com/wiacekmarcin/ha_kiosk_hol

Dokument podsumowuje całą rozmowę: od pierwszego połączenia z Home Assistantem,
przez dashboard dla tabletu, po własną aplikację kiosku na Androida.

---

## 1. Punkt wyjścia

- Home Assistant pod adresem `192.168.10.250:8123`.
- Tablet Samsung Galaxy Tab 3 10.1 (GT-P5210, Intel Atom, x86) z LineageOS,
  adres `192.168.10.252`, wisi na ścianie w holu.
- Na początku tablet pokazywał dashboard HA w aplikacji Fully Kiosk Browser.

## 2. Etap 1: połączenie z HA i dashboard `samsung-kiosk` (17-18 listopada)

- Uruchomione połączenie agenta z HA przez integrację **MCP Server** (brakowała
  integracja, a w nagłówku autoryzacji słowo `Bearer`).
- Strona startowa użytkownika `samsung_kiosk` na dashboardzie `samsung-kiosk`:
  - aktualna pogoda i prognoza na 5 dni,
  - kafelek "Na zewnątrz" (dawniej "Balkon"),
  - "Mieszkanie": średnia temperatura z pomieszczeń poza holem i średnia wilgotność,
  - większa czcionka, pod zegarem data,
  - wschód i zachód słońca zamiast temperatury baterii tabletu,
  - tryb tylko do odczytu (kiosk-mode), usunięta lista zakupów,
  - kafelki klikalne: temperatura pokazuje historię, pogoda szczegóły i prognozę godzinową.

## 3. Etap 2: własna aplikacja kiosku (Python + Kivy, APK)

Fully Kiosk zastąpiła natywna aplikacja **HA Kiosk** napisana w Pythonie z biblioteką
Kivy, budowana do APK przez buildozer w środowisku FullStack WSL (Ubuntu w Windows).
Aplikacja jest ekranem głównym tabletu (launcher), więc startuje po włączeniu tabletu
i po przycisku Home.

### 3.1 Ekran startowy

| Element | Co pokazuje | Dotknięcie |
|---|---|---|
| Zegar | czas z sekundami, wersja aplikacji, bateria tabletu z procentem, błyskawica i moc ładowania (W) podczas ładowania, ikony Wi-Fi i połączenia z HA | kartka z kalendarza (kalbi.pl) |
| Pogoda | warunki (długi opis w 2 wierszach), temperatura i odczuwalna (niebieska: zimniej, czerwona: cieplej), zakres dnia, prognoza 5 dni z opadami | okno pogody na pełny ekran z prognozą godzinową i wiatrem |
| Czujniki | Na zewnątrz, Hol, Mieszkanie (temperatura i wilgotność) | historia 24 h; Hol otwiera wszystkie pomieszczenia |
| Kartka z kalendarza | dzień tygodnia, data, miesiąc; po lewej wschód i zachód słońca oraz długość dnia, po prawej faza Księżyca z jego wschodem i zachodem; niżej święta, wydarzenia z kalendarzy HA, imieniny, inne święta, przysłowia | góra: tabela miesiąca; słońce: "Słońce w roku"; Księżyc: fazy Księżyca; dół: lista wydarzeń |

### 3.2 Okna (wszystkie na cały ekran, z przyciskiem "Wstecz")

- **Pogoda** - szczegóły, prognoza godzinowa z prędkością i kierunkiem wiatru,
  wskaźnik ładowania przy otwieraniu.
- **Tabela miesiąca** - przewijanie miesięcy, święta i wydarzenia na dniach,
  dotknięcie dnia otwiera wydarzenia tego dnia.
- **Lista wydarzeń** - 30 dni z pełnym opisem, przycisk "Dodaj" i formularz nowego
  wydarzenia (usługa `calendar.create_event`).
- **Słońce w roku** - wykres wschodów i zachodów dla każdego dnia roku, zaznaczony
  dzień dzisiejszy, najdłuższy i najkrótszy dzień, podgląd dowolnego dnia pod palcem;
  opisy: długość dnia, zmiana od wczoraj, różnica do najdłuższego i najkrótszego dnia,
  liczba dni do przesilenia.
- **Księżyc** - dzisiejsza faza z oświetleniem i wiekiem, wschód i zachód, 4 najbliższe
  główne fazy, kalendarz faz na cały miesiąc z przewijaniem.
- **Historia czujnika**, **Pomieszczenia**, **Kod QR** (token HA ze skanera).

### 3.3 Pozostałe ekrany (menu boczne)

- **Energia**, **Ogrzewanie**, **Bateria** (magazyn energii), **Włączniki** - przy
  włączonym gniazdku moc w W zamiast napisu "włączone".
- **Ustawienia** - adres i token HA, wygaszanie ekranu, budzenie ruchem (przednia
  kamera), jasność (ręczna i automatyczna z czujnika światła), głośność, przyciski
  "Włącz ADB przez sieć" i "Zamknij aplikację".

### 3.4 Zachowanie

- **Wygaszacz ekranu** po bezczynności (czarna nakładka); budzenie dotykiem albo ruchem
  przed kamerą. Dopiero wygaszenie zamyka okna, a wybudzenie pokazuje ekran startowy.
- **Automatyczna jasność** domyślnie włączona: skala logarytmiczna według czujnika
  światła (ciemno 10 %, około 17 lx 47 %, 100 lx 70 %, od 1000 lx 100 %), z wygładzaniem
  i strefą martwą 4 %. Ruszenie suwaka jasności wyłącza automat.
- **Bateria** odświeżana na zdarzeniach Androida (podłączenie i odłączenie ładowarki,
  zmiana poziomu), nie tylko co minutę.
- Obliczenia słońca (algorytm NOAA z poprawką na wysokość n.p.m., jak w HA) i Księżyca
  (Meeus) są lokalne, bez internetu. Położenie i wysokość domu aplikacja pobiera raz
  z `/api/config` HA.

## 4. Encje i automatyzacje w Home Assistant

### 4.1 Encje tabletu (zapisuje i czyta aplikacja)

| Encja | Kierunek | Opis |
|---|---|---|
| `sensor.tablet_kiosk_bateria` | tablet do HA | poziom baterii %, atrybuty: ładowanie, temperatura |
| `sensor.tablet_kiosk_oswietlenie` | tablet do HA | czujnik światła w lx |
| `input_number.tablet_kiosk_jasnosc` | w obie strony | jasność ekranu 0-100 % |
| `input_number.tablet_kiosk_glosnosc` | w obie strony | głośność 0-100 % |
| `input_boolean.tablet_kiosk_jasnosc_auto` | w obie strony | automatyczna jasność |
| `sensor.charger_2_power` | HA do tabletu | moc gniazdka "Ładowarka do telefonu 2" przy zegarze |

Identyfikatory można zmienić w `settings.json` w sekcji `entities.tablet`.

### 4.2 Automatyzacja ładowarki tabletu

`automation.tablet_kiosk_ladowarka_ladowarka_do_telefonu_2`
(id `tablet_kiosk_ladowarka`), gniazdko `switch.charger_2`:

- **wyłącza**, gdy bateria tabletu ma 100 % przez 2 minuty albo pobór gniazdka jest
  poniżej 1 W przez 5 minut,
- **włącza**, gdy bateria spadnie poniżej 30 %,
- **włącza** (zabezpieczenie), gdy tablet przez 30 minut nie zapisze stanu baterii,
- po starcie HA włącza, jeśli bateria jest poniżej 30 %.

## 5. Historia wersji

| Wersja | Data | Zmiany |
|---|---|---|
| do 0.7 | 18-20 XI | szkielet aplikacji, ekrany, release APK, aplikacja jako ekran główny, Wi-Fi i HA przy zegarze, jasność i głośność jako encje HA, czujnik światła, okno pogody, powrót na start po 3 min, wiatr w prognozie, moc przy włącznikach |
| 0.8 | 21 XI | kartka z kalendarza z tabelą miesiąca, listą i formularzem wydarzeń; okna pełnoekranowe z "Wstecz"; ADB przez sieć i zamknięcie aplikacji w Ustawieniach |
| 0.9 | 21 XI | procent baterii pod ikoną, błyskawica tylko podczas ładowania, zdarzenia zasilania Androida, numer wersji przy zegarze |
| 0.10 | 21 XI | strzałki miesiąca przesuwały o 2 (podwójne zdarzenia dotyku z dostawcy myszy Kivy) |
| 0.11-0.12 | 21 XI | pogoda: bez nazwy encji, opis w 2 wierszach, temperatura odczuwalna w kolorze |
| 0.13 | 21 XI | okno "Słońce w roku" |
| 0.14 | 21 XI | kartka bez paska u góry, automatyczna jasność domyślnie włączona i wygładzona |
| 0.15 | 21 XI | słońce i Księżyc na kartce, okno faz Księżyca, zegar bez daty, powrót na start tylko po wygaszeniu ekranu |
| 0.16 | 21 XI | poprawka awarii po wybudzeniu ekranu i w menu (przywrócona metoda `go_to`) |
| 0.17 | 21 XI | moc ładowania obok błyskawicy; automatyzacja ładowarki w HA |
| 0.18 | 21 XI | ogłaszanie pełnych godzin: gong i "Jest godzina ..." (pn-pt 7-22, sb-nd 9-22), przełącznik w Ustawieniach |
| 0.19 | 21 XI | ikona wyświetlacza w menu bocznym - natychmiastowe wygaszenie ekranu |
| 0.20-0.21 | 22 XI | wersje diagnostyczne awarii JNI (test uruchamiany plikiem-znacznikiem) |
| 0.22 | 22 XI | poprawka awarii JNI przy zmianie jasności; strażnik ponownego uruchomienia co 15 min |

## 6. Budowanie i instalacja

- Projekt: `~/Projekty/workspace1/ha_kiosk` w FullStack WSL; środowisko buildozera:
  `~/Projekty/workspace1/kioskha/.venv`.
- Wersja wydaniowa podpisana kluczem `~/.android/hakiosk-release.keystore`
  (hasło w `~/.android/hakiosk-release.haslo`, zmienne `P4A_RELEASE_*`).
- Numer wersji: pole `version` w `buildozer.spec` (widoczny przy zegarze).
- Instalacja przez ADB po sieci: `adb connect 192.168.10.252:5555`,
  `adb install -r hakiosk-<wersja>-x86-release.apk`.
- **Po każdej instalacji** trzeba ponownie ustawić aplikację jako ekran główny:
  `cmd package set-home-activity pl.mieszkanie.hakiosk/org.kivy.android.PythonActivity`.
- Uprawnienia nadane raz przez ADB: `WRITE_SECURE_SETTINGS` i
  `cyanogenmod.permission.WRITE_SECURE_SETTINGS` (przycisk "Włącz ADB przez sieć").
- `settings.json` (z tokenem HA) jest wbudowany w APK i nie trafia do repozytorium.

## 7. Napotkane problemy i rozwiązania

| Problem | Rozwiązanie |
|---|---|
| MCP HA zwracał 404 | dodana integracja MCP Server, poprawiony nagłówek `Bearer` |
| buildozer: błąd venv z `--user` | venv z `--system-site-packages`; dla libzbar pakiety gettext i autopoint |
| inny podpis APK przy aktualizacji | jednorazowa deinstalacja z kopią `local.json` |
| ukryty przycisk w oknie pogody przechwytywał dotyk | rozmiar (0, 0), gdy nie trwa ładowanie |
| awaria listy wydarzeń (`color` None) | zabezpieczenie koloru karty wydarzenia |
| Android przywraca stary launcher po instalacji | `set-home-activity` po każdej instalacji |
| ADB przez sieć wyłącza się po restarcie tabletu albo jest "offline" | przycisk w Ustawieniach, ponowna autoryzacja klucza na tablecie |
| adres Nabu Casa: błędy SSL przy kalendarzach | adres HA w sieci lokalnej |
| miesiąc przeskakiwał o 2 | wyłączony dostawca myszy Kivy na Androidzie i debounce strzałek |
| awaria po wybudzeniu ekranu (0.15) | przywrócona metoda `go_to` usunięta przy zmianie powrotu na start |
| awaria po kilkunastu godzinach: "JNI local reference table overflow (max=512)" (22 XI) | test na tablecie (`kiosk/jni_probe.py`) wskazał zmianę jasności okna: `run_on_ui_thread` tworzył przy każdym wywołaniu nowy obiekt Javy; teraz jeden stały `Runnable` (1500 zmian bez błędu) |
| awaria czyści ustawienie ekranu głównego, kiosk nie wraca sam | strażnik: alarm systemowy co 15 min uruchamia aktywność kiosku |
| VS Code staje w trakcie budowania | wykluczenie `.buildozer` (~75 tys. plików) ze śledzenia w `KreionWSL.code-workspace` |
| AAPT2 "Daemon startup failed" po restarcie WSL | zatrzymanie starego procesu Gradle (`pkill -f GradleDaemon`) i ponowne budowanie |

## 8. Do sprawdzenia i otwarte punkty

- Wybudzenie ekranu ruchem po wygaszeniu w wersji 0.16 i nowszych - sprawdzone na
  komputerze, na tablecie warto obserwować.
- Pierwsze zadziałanie automatyzacji ładowarki (wyłączenie przy 100 %).
- Na tablecie nie widać przerywanych linii miesięcy na wykresie "Słońce w roku"
  (można zamienić na ciągłe, przygaszone).
- Krzywa automatycznej jasności do ewentualnej korekty po kilku wieczorach.
