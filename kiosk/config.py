"""Stałe konfiguracyjne aplikacji."""
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 800

APP_TITLE = "HA Kiosk"

# Ciemny motyw (odwrócone kolory dashboardu HA "samsung-kiosk/start"), RGBA 0..1
COLOR_BG = (0.067, 0.071, 0.086, 1)        # #111216
COLOR_CARD = (0.122, 0.129, 0.153, 1)      # #1f2127
COLOR_DIVIDER = (0.22, 0.23, 0.27, 1)
COLOR_TEXT = (0.92, 0.93, 0.95, 1)
COLOR_TEXT_DIM = (0.58, 0.61, 0.66, 1)
COLOR_ACCENT = (0.012, 0.663, 0.957, 1)    # #03a9f4 - primary HA
COLOR_ACCENT_SOFT = (0.04, 0.25, 0.36, 1)  # tło niezaznaczonych przełączników
COLOR_ICON = (0.80, 0.82, 0.86, 1)
COLOR_RAIN = (0.30, 0.70, 0.98, 1)
COLOR_SUN_ICON = (0.98, 0.76, 0.25, 1)
COLOR_HEAT = (1.0, 0.58, 0.20, 1)          # grzanie / włączona strefa
COLOR_HEAT_SOFT = (0.32, 0.20, 0.10, 1)
COLOR_EVENT = (0.96, 0.71, 0.18, 1)
COLOR_OK = (0.30, 0.80, 0.40, 1)           # połączono (Wi-Fi, HA)
COLOR_ERROR = (0.96, 0.33, 0.30, 1)        # brak połączenia

CARD_RADIUS = 12
