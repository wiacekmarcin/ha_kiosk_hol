"""Pobiera dane z HA w tle i przekazuje je do UI w formacie jak kiosk/data/mock.py."""
import threading
import time
from datetime import date, datetime, timedelta

from kivy.clock import Clock
from kivy.logger import Logger

from kiosk.ha.client import HAClient, HAError

FAST_INTERVAL = 30       # s - stany czujników, pogoda, słońce
SLOW_INTERVAL = 300      # s - prognoza i kalendarz
CALENDAR_PAST_DAYS = 7
CALENDAR_FUTURE_DAYS = 8 * 7


def parse_dt(value: str) -> datetime:
    """ISO z HA ('...Z' / '+00:00' / sama data) -> datetime w strefie lokalnej (naive)."""
    if len(value) == 10:                                   # wydarzenie całodniowe
        return datetime.fromisoformat(value)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None                                        # unavailable / unknown


class HAProvider:
    def __init__(self, settings: dict, on_data, on_status=None):
        self.settings = settings
        self.entities = settings.get("entities", {})
        self.on_data = on_data
        self.on_status = on_status or (lambda _msg: None)
        self.client = HAClient(settings["url"], settings["token"])
        self.data = {}
        self._last_slow = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ha-provider", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def refresh_now(self):
        self._last_slow = 0.0

    # --- pętla w tle ------------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            slow = time.monotonic() - self._last_slow >= SLOW_INTERVAL
            ok = self._fetch(slow)
            if ok and slow:
                self._last_slow = time.monotonic()
            if self.data:
                data = dict(self.data)
                Clock.schedule_once(lambda _dt: self.on_data(data))
            status = "" if ok else "Brak połączenia z HA"
            Clock.schedule_once(lambda _dt: self.on_status(status))
            self._stop.wait(FAST_INTERVAL if ok else 10)

    def _fetch(self, slow: bool) -> bool:
        ok = True
        for name, func in (("sensors", self._sensors), ("weather", self._weather),
                           ("sun", self._sun)):
            ok &= self._section(name, func)
        if slow or "forecast" not in self.data.get("weather", {}):
            ok &= self._section("forecast", self._forecast)
            ok &= self._section("events", self._events)
        return ok

    def _section(self, name, func) -> bool:
        try:
            func()
            return True
        except (HAError, KeyError, ValueError) as e:
            Logger.warning(f"HA: błąd pobierania '{name}': {e}")
            return False

    # --- sekcje -----------------------------------------------------------------
    def _sensors(self):
        result = []
        for cfg in self.entities.get("sensors", []):
            st = self.client.state(cfg["entity_id"])
            attrs = st.get("attributes", {})
            result.append({
                "entity_id": cfg["entity_id"],
                "name": cfg.get("name") or attrs.get("friendly_name", cfg["entity_id"]),
                "value": to_float(st["state"]),
                "unit": attrs.get("unit_of_measurement", ""),
                "icon": cfg.get("icon") or (attrs.get("icon") or "").replace("mdi:", ""),
                "action": cfg.get("action", "history"),
                "humidity": self._humidity(cfg.get("humidity")),
            })
        self.data["sensors"] = result

    def _humidity(self, entity_id):
        """Opcjonalna wilgotność do kafelka: {"entity_id", "value", "unit"} albo None."""
        if not entity_id:
            return None
        st = self.client.state(entity_id)
        return {"entity_id": entity_id, "value": to_float(st["state"]),
                "unit": st.get("attributes", {}).get("unit_of_measurement", "%")}

    def _weather(self):
        eid = self.entities.get("weather")
        if not eid:                               # brak w ustawieniach (np. sam adres i token)
            return
        st = self.client.state(eid)
        attrs = st.get("attributes", {})
        weather = dict(self.data.get("weather", {}))
        weather.update({
            "name": attrs.get("friendly_name", eid),
            "condition": st["state"],
            "temperature": to_float(attrs.get("temperature")),
            "temperature_unit": attrs.get("temperature_unit", "°C"),
            "pressure": to_float(attrs.get("pressure")),
            "pressure_unit": attrs.get("pressure_unit", "hPa"),
            "humidity": to_float(attrs.get("humidity")),
            "wind_speed": to_float(attrs.get("wind_speed")),
            "wind_speed_unit": attrs.get("wind_speed_unit", "m/s"),
            "wind_bearing": to_float(attrs.get("wind_bearing")),
            # tylko niektóre integracje (np. OpenWeatherMap) ją podają; met.no nie
            "apparent_temperature": to_float(attrs.get("apparent_temperature")),
            "precipitation_unit": attrs.get("precipitation_unit", "mm"),
            "attribution": attrs.get("attribution", ""),
            "last_changed": parse_dt(st["last_changed"]) if st.get("last_changed") else None,
        })
        self.data["weather"] = weather

    def _forecast(self):
        eid = self.entities.get("weather")
        if not eid:
            return
        forecast = []
        for item in self.client.forecast(eid, "daily"):
            forecast.append({
                "date": parse_dt(item["datetime"]).date(),
                "condition": item.get("condition", ""),
                "high": to_float(item.get("temperature")),
                "low": to_float(item.get("templow")),
                "precipitation": to_float(item.get("precipitation")),
            })
        hourly = []
        try:
            for item in self.client.forecast(eid, "hourly")[:48]:
                hourly.append({
                    "datetime": parse_dt(item["datetime"]),
                    "condition": item.get("condition", ""),
                    "temperature": to_float(item.get("temperature")),
                    "precipitation": to_float(item.get("precipitation")),
                    "wind_speed": to_float(item.get("wind_speed")),
                    "wind_bearing": to_float(item.get("wind_bearing")),
                })
        except HAError as e:                      # nie każda integracja ma godzinową
            Logger.info(f"HA: brak prognozy godzinowej: {e}")
        weather = dict(self.data.get("weather", {}))
        weather["forecast"] = forecast
        weather["hourly"] = hourly
        self.data["weather"] = weather

    def _sun(self):
        attrs = self.client.state(self.entities.get("sun", "sun.sun"))["attributes"]
        # next_rising/next_setting to następne zdarzenie - po zachodzie pokaże jutrzejszy wschód
        self.data["sun"] = {
            "rising": parse_dt(attrs["next_rising"]).strftime("%H:%M"),
            "setting": parse_dt(attrs["next_setting"]).strftime("%H:%M"),
        }
        if "location" not in self.data:
            # położenie domu z konfiguracji HA - do wykresu wschodów i zachodów w roku
            cfg = self.client._request("GET", "/api/config")
            if cfg.get("latitude") is not None and cfg.get("longitude") is not None:
                self.data["location"] = {"latitude": float(cfg["latitude"]),
                                         "longitude": float(cfg["longitude"]),
                                         "elevation": float(cfg.get("elevation") or 0)}

    def _events(self):
        today = datetime.combine(date.today(), datetime.min.time()).astimezone()
        start = today - timedelta(days=CALENDAR_PAST_DAYS)
        end = today + timedelta(days=CALENDAR_FUTURE_DAYS)
        self.data["events"] = self.load_events(self.client, self.entities.get("calendars", []),
                                               start, end)

    @staticmethod
    def load_events(client, calendars, start, end) -> list:
        """Wydarzenia ze wszystkich kalendarzy w zakresie [start, end):
        {start, end, all_day, title, description, location, calendar}."""
        events, failed = [], []
        for eid in calendars:
            try:
                items = client.calendar_events(eid, start, end)
            except HAError as e:
                # błąd jednego kalendarza (np. literówka w entity_id) nie ukrywa pozostałych
                Logger.warning(f"HA: kalendarz {eid}: {e}")
                failed.append(eid)
                continue
            for ev in items:
                s, e = ev["start"], ev["end"]
                all_day = "date" in s and "dateTime" not in s
                events.append({
                    "start": parse_dt(s.get("dateTime") or s["date"]),
                    "end": parse_dt(e.get("dateTime") or e["date"]),
                    "all_day": all_day,
                    "title": ev.get("summary", ""),
                    "description": ev.get("description") or "",
                    "location": ev.get("location") or "",
                    "calendar": eid,
                })
        if calendars and len(failed) == len(calendars):
            raise HAError("żaden kalendarz nie odpowiedział")
        return events

    def fetch_events(self, start: datetime, end: datetime, callback):
        """Wydarzenia z dowolnego zakresu (tabela miesiąca, lista); callback(events, error)."""
        calendars = self.entities.get("calendars", [])
        self._in_thread("wydarzenia", lambda client: self.load_events(
            client, calendars, start.astimezone(), end.astimezone()), callback)

    def fetch_calendars(self, callback):
        """Kalendarze z settings.json: callback([(entity_id, nazwa, zapis_możliwy)], error).
        supported_features & 1 = CREATE_EVENT."""
        calendars = self.entities.get("calendars", [])

        def func(client):
            out = []
            for eid in calendars:
                try:
                    attrs = client.state(eid).get("attributes", {})
                except HAError:
                    continue
                out.append((eid, attrs.get("friendly_name", eid),
                            bool(int(attrs.get("supported_features") or 0) & 1)))
            return out
        self._in_thread("kalendarze", func, callback)

    # --- historia na żądanie (okno wykresu) ----------------------------------------
    def fetch_history(self, entity_id: str, start: datetime, end: datetime, callback):
        """Pobiera historię w osobnym wątku; callback(points, error) w wątku UI."""
        def work():
            # osobny klient - requests.Session nie powinien być dzielony między wątki
            client = HAClient(self.settings["url"], self.settings["token"])
            try:
                raw = client.history(entity_id, start.astimezone(), end.astimezone())
                points = [(parse_dt(p["last_changed"]), to_float(p["state"])) for p in raw]
                result = (points, None)
            except (HAError, KeyError, ValueError) as e:
                Logger.warning(f"HA: historia {entity_id}: {e}")
                result = (None, str(e))
            Clock.schedule_once(lambda _dt: callback(*result))

        threading.Thread(target=work, name="ha-history", daemon=True).start()

    _template_ok = True       # czy /api/template działa (jedno zapytanie zamiast N)

    def fetch_states(self, entity_ids: list, callback):
        """Stany wielu encji w osobnym wątku; callback({eid: {"value", "unit"}}, error).

        Najpierw jedno zbiorcze zapytanie przez API szablonów; gdy niedostępne -
        pojedyncze zapytania o każdą encję.
        """
        def work():
            client = HAClient(self.settings["url"], self.settings["token"])
            if HAProvider._template_ok:
                try:
                    raw = client.states_batch(entity_ids)
                    values = {eid: {"value": to_float(state), "unit": unit or ""}
                              for eid, (state, unit) in raw.items()}
                    Clock.schedule_once(lambda _dt: callback(values, None))
                    return
                except HAError as e:
                    if "niedostępne" in str(e):
                        HAProvider._template_ok = False
                    Logger.warning(f"HA: zapytanie zbiorcze: {e} - pojedyncze zapytania")
            values, errors = {}, []
            for eid in entity_ids:
                try:
                    st = client.state(eid)
                    values[eid] = {"value": to_float(st["state"]),
                                   "unit": st.get("attributes", {}).get("unit_of_measurement", "")}
                except (HAError, KeyError) as e:
                    Logger.warning(f"HA: stan {eid}: {e}")
                    errors.append(eid)
            error = "brak odpowiedzi HA" if errors and not values else None
            Clock.schedule_once(lambda _dt: callback(values, error))

        threading.Thread(target=work, name="ha-states", daemon=True).start()

    # --- encje z atrybutami, baterie, usługi (ekrany Ogrzewanie / Baterie) -----------
    def _in_thread(self, name, func, callback):
        def work():
            client = HAClient(self.settings["url"], self.settings["token"])
            try:
                result, error = func(client), None
            except (HAError, KeyError, ValueError, TypeError) as e:
                Logger.warning(f"HA: {name}: {e}")
                result, error = None, str(e)
            if callback:
                Clock.schedule_once(lambda _dt: callback(result, error))
        threading.Thread(target=work, name=f"ha-{name}", daemon=True).start()

    def fetch_entities(self, entity_ids: list, attrs: list, callback):
        """callback({eid: {"state", "attributes"}}, error) - jedno zapytanie (z fallbackiem)."""
        def func(client):
            if HAProvider._template_ok:
                try:
                    return client.entities_batch(entity_ids, attrs)
                except HAError as e:
                    if "niedostępne" not in str(e):
                        raise
                    HAProvider._template_ok = False
            out = {}
            for eid in entity_ids:
                st = client.state(eid)
                out[eid] = {"state": st["state"],
                            "attributes": {k: st.get("attributes", {}).get(k) for k in attrs}}
            return out
        self._in_thread("encje", func, callback)

    def fetch_batteries(self, callback):
        """callback([{"entity_id", "name", "value", "unit"}], error)"""
        def func(client):
            return [{"entity_id": eid, "name": name, "value": to_float(state), "unit": unit}
                    for eid, name, state, unit in client.batteries()]
        self._in_thread("baterie", func, callback)

    def call_service(self, domain: str, service: str, data: dict, callback=None):
        self._in_thread(f"{domain}.{service}",
                        lambda client: client.call_service(domain, service, data), callback)

    def fetch_switches(self, callback):
        """callback([{"entity_id", "name", "state", "power", "power_unit"}], error);
        power = moc z czujnika tego samego urządzenia albo None."""
        def func(client):
            out = []
            for e, n, s, p in client.switches():
                power, unit = (to_float(p[0]), p[1] or "W") if p else (None, "")
                out.append({"entity_id": e, "name": n, "state": s,
                            "power": power, "power_unit": unit})
            return out
        self._in_thread("przełączniki", func, callback)
