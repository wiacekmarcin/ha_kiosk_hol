"""Minimalny klient REST API Home Assistant (https://developers.home-assistant.io/docs/api/rest)."""
from datetime import datetime
from urllib.parse import quote

import requests


class HAError(Exception):
    pass


class HAClient:
    def __init__(self, url: str, token: str, timeout: float = 10):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })

    def _request(self, method: str, path: str, **kwargs):
        try:
            resp = self.session.request(method, f"{self.url}{path}",
                                        timeout=self.timeout, **kwargs)
        except requests.RequestException as e:
            raise HAError(f"{method} {path}: {e}") from e
        if resp.status_code == 401:
            raise HAError("401 Unauthorized - sprawdź token")
        if resp.status_code in (400, 404) and "/api/calendars/" in path and not resp.text:
            raise HAError(f"{path}: encja nie istnieje (HTTP {resp.status_code})")
        if not resp.ok:
            raise HAError(f"{method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json()

    def ping(self) -> str:
        return self._request("GET", "/api/")["message"]

    def states(self) -> list:
        return self._request("GET", "/api/states")

    def state(self, entity_id: str) -> dict:
        return self._request("GET", f"/api/states/{entity_id}")

    def forecast(self, entity_id: str, kind: str = "daily") -> list:
        """kind: 'daily' | 'hourly' | 'twice_daily'"""
        data = self._request("POST", "/api/services/weather/get_forecasts?return_response",
                             json={"entity_id": entity_id, "type": kind})
        # Odpowiedź: {"changed_states": [...], "service_response": {entity_id: {"forecast": [...]}}}
        response = data.get("service_response", data)
        return response.get(entity_id, {}).get("forecast", [])

    def calendar_events(self, entity_id: str, start: datetime, end: datetime) -> list:
        return self._request("GET", f"/api/calendars/{entity_id}",
                             params={"start": start.isoformat(), "end": end.isoformat()})

    def history(self, entity_id: str, start: datetime, end: datetime) -> list:
        """Lista zmian stanu: [{"state": "9.6", "last_changed": "..."}, ...]"""
        data = self._request("GET", f"/api/history/period/{quote(start.isoformat())}",
                             params={"filter_entity_id": entity_id,
                                     "end_time": end.isoformat(),
                                     "minimal_response": "", "no_attributes": ""})
        return data[0] if data else []

    def states_batch(self, entity_ids: list) -> dict:
        """Stany i jednostki wielu encji JEDNYM zapytaniem (API szablonów HA).

        Zwraca {entity_id: (state, unit)}. Wymaga uprawnień do /api/template
        (przy 401/403 wołający przechodzi na pojedyncze zapytania).
        """
        parts = [
            f'"{eid}": [{{{{ states("{eid}") | tojson }}}}, '
            f'{{{{ state_attr("{eid}", "unit_of_measurement") | tojson }}}}]'
            for eid in entity_ids
        ]
        template = "{" + ", ".join(parts) + "}"
        try:
            resp = self.session.post(f"{self.url}/api/template", json={"template": template},
                                     timeout=self.timeout)
        except requests.RequestException as e:
            raise HAError(f"POST /api/template: {e}") from e
        if resp.status_code in (401, 403):
            raise HAError(f"/api/template niedostępne (HTTP {resp.status_code})")
        if not resp.ok:
            raise HAError(f"POST /api/template: HTTP {resp.status_code} {resp.text[:200]}")
        import json
        return {eid: tuple(v) for eid, v in json.loads(resp.text).items()}

    def render_template(self, template: str):
        """Renderuje szablon Jinja w HA i parsuje wynik jako JSON."""
        try:
            resp = self.session.post(f"{self.url}/api/template", json={"template": template},
                                     timeout=self.timeout)
        except requests.RequestException as e:
            raise HAError(f"POST /api/template: {e}") from e
        if resp.status_code in (401, 403):
            raise HAError(f"/api/template niedostępne (HTTP {resp.status_code})")
        if not resp.ok:
            raise HAError(f"POST /api/template: HTTP {resp.status_code} {resp.text[:200]}")
        import json
        return json.loads(resp.text)

    def entities_batch(self, entity_ids: list, attrs: list) -> dict:
        """Stan + wybrane atrybuty wielu encji jednym zapytaniem:
        {entity_id: {"state": str, "attributes": {nazwa: wartość}}}"""
        def one(eid):
            a = ", ".join(f'"{k}": {{{{ state_attr("{eid}", "{k}") | tojson }}}}' for k in attrs)
            return f'"{eid}": {{"state": {{{{ states("{eid}") | tojson }}}}, "attributes": {{{a}}}}}'
        return self.render_template("{" + ", ".join(one(e) for e in entity_ids) + "}")

    def batteries(self) -> list:
        """Wszystkie sensory baterii: [[entity_id, nazwa, stan, jednostka], ...] (1 zapytanie)."""
        return self.render_template(
            "{% set ns = namespace(r=[]) %}"
            "{% for s in states.sensor if s.attributes.device_class == 'battery' %}"
            "{% set ns.r = ns.r + [[s.entity_id, s.name, s.state, "
            "s.attributes.unit_of_measurement | default('')]] %}"
            "{% endfor %}{{ ns.r | tojson }}")

    def call_service(self, domain: str, service: str, data: dict):
        return self._request("POST", f"/api/services/{domain}/{service}", json=data)

    def set_state(self, entity_id: str, state, attributes: dict):
        """Tworzy / aktualizuje stan encji (np. sensor baterii tabletu); wymaga konta admina.
        HA nie zapamiętuje takiej encji po restarcie - wraca przy następnym zapisie."""
        return self._request("POST", f"/api/states/{entity_id}",
                             json={"state": str(state), "attributes": attributes})

    def switches(self) -> list:
        """Wszystkie przełączniki i światła (1 zapytanie):
        [[entity_id, nazwa, stan, [moc, jednostka] | None], ...].

        Moc = pierwszy czujnik z device_class power tego samego urządzenia w HA
        (np. gniazdko z pomiarem: switch.fridge -> sensor.fridge_power)."""
        return self.render_template(
            "{% set ns = namespace(r=[]) %}"
            "{% for s in states if s.domain in ['switch', 'light'] %}"
            "{% set p = namespace(v=none) %}{% set d = device_id(s.entity_id) %}"
            "{% if d %}{% for e in device_entities(d) if e.startswith('sensor.') "
            "and state_attr(e, 'device_class') == 'power' %}"
            "{% if p.v is none %}{% set p.v = [states(e), state_attr(e, 'unit_of_measurement')] %}"
            "{% endif %}{% endfor %}{% endif %}"
            "{% set ns.r = ns.r + [[s.entity_id, s.name, s.state, p.v]] %}"
            "{% endfor %}{{ ns.r | tojson }}")
