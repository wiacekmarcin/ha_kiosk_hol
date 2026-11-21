"""Wypisuje encje z HA przydatne dla kiosku (pogoda, kalendarze, temperatura, wilgotność).

Użycie (z katalogu ha_kiosk):
    python3 tools/list_entities.py
Wymaga settings.json z url i tokenem (sekcja entities może być jeszcze przykładowa).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kiosk.ha.client import HAClient, HAError  # noqa: E402
from kiosk.ha.settings import SETTINGS_PATH, load_settings  # noqa: E402


def main():
    settings = load_settings()
    if not settings:
        sys.exit(f"Brak url/tokenu w {SETTINGS_PATH} (skopiuj settings.example.json)")
    client = HAClient(settings["url"], settings["token"])
    try:
        print("HA:", client.ping())
        states = client.states()
    except HAError as e:
        sys.exit(f"Błąd: {e}")

    groups = {"Pogoda": [], "Kalendarze": [], "Temperatura": [], "Wilgotność": []}
    for st in states:
        eid, attrs = st["entity_id"], st.get("attributes", {})
        dc = attrs.get("device_class")
        line = (f"  {eid:55} {st['state']:>12} {attrs.get('unit_of_measurement', ''):4}"
                f"  {attrs.get('friendly_name', '')}")
        if eid.startswith("weather."):
            groups["Pogoda"].append(line)
        elif eid.startswith("calendar."):
            groups["Kalendarze"].append(line)
        elif eid.startswith("sensor.") and dc == "temperature":
            groups["Temperatura"].append(line)
        elif eid.startswith("sensor.") and dc == "humidity":
            groups["Wilgotność"].append(line)

    for title, lines in groups.items():
        print(f"\n{title}:")
        print("\n".join(sorted(lines)) or "  (brak)")


if __name__ == "__main__":
    main()
