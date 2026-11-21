"""Dane przykładowe - struktura odpowiada temu, co później przyjdzie z Home Assistant.

weather  <- weather.* (state, attributes.temperature) + weather.get_forecasts (daily)
sensors  <- sensor.* (state, unit_of_measurement)
sun      <- sun.sun (next_rising / next_setting)
events   <- calendar.* (calendar.get_events)
"""
import math
import random
from datetime import date, datetime, time, timedelta


def get_data():
    today = date.today()
    now = datetime.now()
    hour0 = now.replace(minute=0, second=0, microsecond=0)

    def at(days, hh, mm):
        return datetime.combine(today + timedelta(days=days), time(hh, mm))

    return {
        "weather": {
            "name": "Home Pogoda",
            "condition": "rainy",
            "temperature": 9.2,
            "temperature_unit": "°C",
            "pressure": 983.9,
            "pressure_unit": "hPa",
            "humidity": 89,
            "wind_speed": 5.69,
            "wind_speed_unit": "m/s",
            "wind_bearing": 227.4,
            "precipitation_unit": "mm",
            "attribution": "Weather forecast from met.no, delivered by the "
                           "Norwegian Meteorological Institute.",
            "last_changed": now - timedelta(hours=4, minutes=10),
            "hourly": [
                {"datetime": hour0 + timedelta(hours=i),
                 "condition": "partlycloudy" if 4 <= i % 12 <= 7 else "cloudy",
                 "temperature": round(10 - i * 0.35 + (i % 24 > 18) * 2, 1),
                 "precipitation": [0, 0, 0.1, 0.4, 1.2, 0.8, 0.3, 0][i % 8] if 10 <= i < 26
                 else 0.0}
                for i in range(48)
            ],
            "forecast": [
                {"date": today + timedelta(days=i), "condition": c, "high": h, "low": l,
                 "precipitation": p}
                for i, (c, h, l, p) in enumerate([
                    ("rainy", 10, 7.3, 0.2),
                    ("cloudy", 9.1, 5.1, 1.8),
                    ("cloudy", 8.2, -0.2, 1.8),
                    ("partlycloudy", 3.4, -1.1, 0.0),
                    ("cloudy", 2.9, 1.3, 2.4),
                    ("snowy", 1.5, -2.0, 0.6),
                ])
            ],
        },
        "sensors": [
            {"entity_id": "mock.out", "name": "Na zewnątrz", "value": 9.6, "unit": "°C", "icon": "thermometer",
             "humidity": {"entity_id": "mock.out_h", "value": 81, "unit": "%"}},
            {"entity_id": "mock.hol", "name": "Hol", "value": 22.9, "unit": "°C", "icon": "home-thermometer",
             "action": "rooms", "humidity": {"entity_id": "mock.hol_h", "value": 50, "unit": "%"}},
            {"entity_id": "mock.temp", "name": "Mieszkanie", "value": 22.7, "unit": "°C",
             "icon": "home-thermometer-outline",
             "humidity": {"entity_id": "mock.hum", "value": 52.2, "unit": "%"}},
        ],
        "sun": {"rising": "07:01", "setting": "15:42"},
        "events": [
            {"start": at(2, 17, 45), "end": at(2, 18, 30), "title": "Rehabilitacja Mateusz"},
            {"start": at(4, 11, 30), "end": at(4, 12, 0), "title": "Basen"},
        ],
    }


def get_history(entity_id: str, start: datetime, end: datetime):
    """Syntetyczna historia: cykl dobowy + szum, pomiar co ~15 min."""
    if entity_id == "mock.out":
        base, amp = 7, 3
    elif entity_id.endswith("_h") or entity_id == "mock.hum":
        base, amp = (80, 8) if entity_id == "mock.out_h" else (52, 4)
    else:
        base, amp = 22.5, 0.6
    rnd = random.Random(entity_id)
    points, t = [], start
    while t <= end:
        phase = (t.hour + t.minute / 60 - 15) / 24 * 2 * math.pi   # maksimum ok. 15:00
        points.append((t, round(base + amp * math.cos(phase) + rnd.uniform(-0.2, 0.2), 1)))
        t += timedelta(minutes=rnd.randint(10, 20))
    return points


ROOMS = [
    {"name": n, "temperature": f"mock.{k}_t", "humidity": f"mock.{k}_h"}
    for n, k in [("WC", "wc"), ("Hol", "hol"), ("Łazienka", "lazienka"), ("Salon 1", "salon1"),
                 ("Salon 2", "salon2"), ("Kuchnia", "kuchnia"), ("Sypialnia", "sypialnia"),
                 ("Pokój dzieci", "dzieci")]
]


ENERGY = {
    "title": "Rozdzielnia elektryczna",
    "summary": ["mock.e.p", "mock.e.kwh"],
    "phases": [{"name": f"Faza {i}", "voltage": f"mock.e.u{i}", "current": f"mock.e.i{i}",
                "power": f"mock.e.p{i}", "power_factor": f"mock.e.pf{i}"} for i in (1, 2, 3)],
    "totals": [
        {"entity_id": "mock.e.p", "name": "Moc chwilowa", "icon": "transmission-tower-export"},
        {"entity_id": "mock.e.pf", "name": "Współczynnik mocy", "icon": "angle-acute"},
        {"entity_id": "mock.e.kwh", "name": "Energia pobrana", "icon": "lightning-bolt",
         "decimals": 3},
        {"entity_id": "mock.e.q", "name": "Moc bierna", "icon": "transmission-tower"},
        {"entity_id": "mock.e.s", "name": "Moc pozorna", "icon": "transmission-tower"},
        {"entity_id": "mock.e.kvarh", "name": "Energia bierna", "icon": "lightning-bolt"},
        {"entity_id": "mock.e.hz", "name": "Częstotliwość", "icon": "sine-wave"},
        {"entity_id": "mock.e.cost", "name": "Aktualny koszt", "icon": "cash-clock"},
        {"entity_id": "mock.e.price", "name": "Cena energii", "icon": "cash", "decimals": 6},
    ],
}

_ENERGY_VALUES = {  # prefiks id -> (min, max, jednostka)
    "mock.e.u": (236, 241, "V"), "mock.e.i": (0.02, 0.7, "A"), "mock.e.pf": (0.2, 0.65, ""),
    "mock.e.p": (0, 90, "W"), "mock.e.kwh": (3124, 3125, "kWh"), "mock.e.q": (-85, -75, "W"),
    "mock.e.s": (-85, -75, "W"), "mock.e.kvarh": (52, 53, "kWh"), "mock.e.hz": (49.95, 50.05, "Hz"),
    "mock.e.cost": (0.1, 0.13, "PLN/h"), "mock.e.price": (1.297896, 1.297896, "PLN/kWh"),
}


def get_states(entity_ids):
    rnd = random.Random()
    out = {}
    for eid in entity_ids:
        if eid.startswith("mock.e."):
            key = max((k for k in _ENERGY_VALUES if eid.startswith(k)), key=len)
            lo, hi, unit = _ENERGY_VALUES[key]
            out[eid] = {"value": rnd.uniform(lo, hi), "unit": unit}
        elif eid.endswith("_t"):
            out[eid] = {"value": round(rnd.uniform(20.5, 24.5), 1), "unit": "°C"}
        else:
            out[eid] = {"value": round(rnd.uniform(45, 58)), "unit": "%"}
    return out


# --- Ogrzewanie (stan w pamięci - przełączniki działają w trybie bez HA) -------------
HEATING = {
    "title": "Ogrzewanie",
    "summary": ["mock.h.power", "mock.h.energy"],
    "thermostats": [{"entity_id": f"mock.h.t{i}", "name": n}
                    for i, n in enumerate(["Dzieci", "Sypialnia", "Pracownia", "Salon", "Jadalnia"])],
    "floor": {
        "switch": "mock.h.floor", "pump": "mock.h.pump", "pump_timer": "mock.h.timer",
        "power": "mock.h.power", "energy": "mock.h.energy",
        "zones": [{"entity_id": f"mock.h.z{i}", "name": n} for i, n in
                  enumerate(["Hol 1", "Hol 2", "Hol 3", "Kuchnia", "Łazienka", "Salon", "WC"])],
    },
}

_heating_state = {
    **{f"mock.h.t{i}": {"state": m, "attributes": {
        "current_temperature": c, "temperature": t, "hvac_action": a, "preset_mode": p,
        "min_temp": 5, "max_temp": 30, "target_temp_step": 0.5}}
       for i, (m, c, t, a, p) in enumerate([
           ("heat", 22.2, 16.0, "idle", "away"), ("heat", 20.1, 21.0, "heating", "sleep"),
           ("heat", 22.1, 16.0, "idle", "eco"), ("off", None, 21.0, None, None),
           ("off", None, 16.0, None, None)])},
    "mock.h.floor": {"state": "on", "attributes": {}},
    "mock.h.pump": {"state": "on", "attributes": {}},
    "mock.h.timer": {"state": "idle", "attributes": {}},
    "mock.h.power": {"state": "1250", "attributes": {"unit_of_measurement": "W"}},
    "mock.h.energy": {"state": "77.76", "attributes": {"unit_of_measurement": "kWh"}},
    **{f"mock.h.z{i}": {"state": "on" if i in (0, 3, 4) else "off", "attributes": {}}
       for i in range(7)},
}


def get_entities(entity_ids, attrs):
    return {eid: {"state": _heating_state.get(eid, {}).get("state", "unknown"),
                  "attributes": {k: _heating_state.get(eid, {}).get("attributes", {}).get(k)
                                 for k in attrs}}
            for eid in entity_ids}


def call_service(domain, service, data):
    eid = data.get("entity_id")
    st = _heating_state.setdefault(eid, {"state": "off", "attributes": {}})
    if service in ("turn_on", "turn_off"):
        st["state"] = "on" if service == "turn_on" else "off"
    elif service == "set_temperature":
        st["attributes"]["temperature"] = data["temperature"]
    elif service == "set_hvac_mode":
        st["state"] = data["hvac_mode"]
        st["attributes"]["hvac_action"] = "idle" if data["hvac_mode"] == "heat" else None
    return []


# --- Baterie ---------------------------------------------------------------------
BATTERIES = [
    ("mock.b.phone", "SM-A325F Battery level", 6), ("mock.b.sw", "Włącznik 4x salon Bateria", 22),
    ("mock.b.trv1", "Jadalnia-grzejnik Jadalnia-Grzejnik_battery_level", 48),
    ("mock.b.out", "outside_temperature Bateria", 55), ("mock.b.trv2", "Salon-grzejnik_battery_level", 80),
    ("mock.b.tih1", "Termohigrometr salon Bateria", 100), ("mock.b.tih2", "Termohigrometr kuchnia Bateria", 100),
    ("mock.b.tab", "Samsung Galaxy Tab 3 Bateria", None),
]


def get_batteries():
    return [{"entity_id": e, "name": n, "value": v, "unit": "%"} for e, n, v in BATTERIES]


# --- Włączniki ---------------------------------------------------------------------
SWITCHES = [
    ("switch.main_power_switch", "Wyłącznik główny", "on"), ("switch.centrala_ha", "Centrala HA", "on"),
    ("switch.fridge", "Lodówka", "on"), ("switch.fridge_child_lock", "Lodówka Child lock", "off"),
    ("switch.teapot_electric", "Czajnik", "off"), ("switch.tv_samsung", "Samsung TV", "off"),
    ("switch.arduinomega_wiatrak_kuchnia", "ArduinoMega Wiatrak kuchnia", "on"),
    ("light.arduinomega_oswietlenie_pod_wanna_2", "ArduinoMega Oświetlenie pod wanną", "off"),
    ("switch.washing_machine", "Pralka", "off"), ("switch.zelazko", "Żelazko", "unavailable"),
    ("switch.kuchnia_gazowa", "kuchnia_gazowa", "off"), ("switch.computer", "Komputer", "on"),
]


def get_switches():
    for eid, _n, st in SWITCHES:
        _heating_state.setdefault(eid, {"state": st, "attributes": {}})
    return [{"entity_id": e, "name": n, "state": _heating_state[e]["state"]} for e, n, _s in SWITCHES]


SWITCH_CONFIG = {"sections": [
    {"name": "Start", "protect": ["switch.main_power_switch"],
     "entities": ["switch.main_power_switch", "switch.tv_samsung", "switch.washing_machine",
                  "switch.arduinomega_wiatrak_kuchnia"]},
    {"name": "Włączone", "on": True},
    {"name": "Rozdzielnia", "protect": "all", "entities": ["switch.fridge"]},
    {"name": "Centrala HA", "protect": "all", "entities": ["switch.centrala_ha", "switch.computer"]},
    {"name": "Inne", "rest": True, "protect": "all"},
]}
