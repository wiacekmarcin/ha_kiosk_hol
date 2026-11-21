"""Ekran "Włączniki": wszystkie przełączniki (switch.*) i światła (light.*) z HA.

Konfiguracja (settings.json -> entities.switches, wszystko opcjonalne):
  sections         - zakładki u góry, w kolejności wyświetlania:
                       {"name": "Start", "entities": [...], "protect": [...]}  - lista encji,
                       {"name": "Inne", "rest": true, "protect": "all"}         - wszystko pozostałe,
                       {"name": "Włączone", "on": true}                          - włączone ze wszystkich;
                     "protect": "all" albo lista encji wymagających potwierdzenia (kłódka),
  exclude_patterns - wyrażenia regularne entity_id do ukrycia (domyślnie DEFAULT_EXCLUDE:
                     blokady rodzicielskie, ustawienia głowic, tabletu itp.),
  exclude          - konkretne encje do ukrycia,
  readonly         - encje tylko do podglądu (dotyk nic nie przełącza, np. pompa),
  names            - własne nazwy {entity_id: nazwa}.
Odczyt: cała lista jednym zapytaniem co REFRESH_SECONDS, tylko gdy ekran widoczny.
"""
import re
import time

from kivy.app import App
from kivy.clock import Clock
from kivy.properties import NumericProperty, StringProperty
from kivy.uix.screenmanager import Screen

from kiosk import pl
from kiosk.ui import make
from kiosk.widgets.confirm_dialog import ConfirmDialog

REFRESH_SECONDS = 5
HOLD_AFTER_TOGGLE = 4          # s - po przełączeniu nie nadpisuj stanu starym odczytem

# ustawienia techniczne urządzeń - to nie są "włączniki"
DEFAULT_EXCLUDE = [
    r"_child_lock$", r"_wstrzymaj_uczenie$", r"_zwolnienie_trv$", r"_zwolnij_urzadzenia$",
    r"samsung_galaxy_tab_3_", r"_permit_join$", r"_deco_polling$", r"usb_kontroler",
    r"_bubble_soak$", r"^switch\.0x[0-9a-f]+$",
]

# słowo w entity_id/nazwie -> ikona
ICONS = [
    ("oswietlen", "lightbulb"), ("light", "lightbulb"), ("wiatrak", "fan"), ("okap", "fan"),
    ("hood", "fan"), ("tv", "television"), ("dekoder", "television"), ("decoder", "television"),
    ("dvd", "television"), ("pralka", "washing-machine"), ("washing", "washing-machine"),
    ("fridge", "fridge"), ("lodówka", "fridge"), ("teapot", "kettle"), ("czajnik", "kettle"),
    ("microwave", "microwave"), ("computer", "desktop-classic"), ("komputer", "desktop-classic"),
    ("router", "router-wireless"), ("vectra", "router-wireless"), ("wifi", "router-wireless"),
    ("dryer", "tumble-dryer"), ("gazow", "stove"), ("zmywark", "dishwasher"),
    ("roaster", "toaster-oven"), ("piekarnik", "toaster-oven"), ("zelazko", "iron"),
    ("serwer", "server"), ("nas", "server"), ("centrala", "server"),
    ("ogrzewanie_podlogowe", "heating-coil"), ("heating", "radiator"), ("pompa", "pump"),
    ("charger", "power-plug"), ("zasila", "power-plug"), ("power", "power"),
]


def icon_for(entity_id: str, name: str) -> str:
    text = f"{entity_id} {name}".lower()
    for key, icon in ICONS:
        if key in text:
            return icon
    return "lightbulb" if entity_id.startswith("light.") else "power-socket-eu"


def clean_name(name: str) -> str:
    """'ArduinoMega Wiatrak kuchnia' -> 'Wiatrak kuchnia'; 'kuchnia_gazowa' -> 'Kuchnia gazowa'."""
    name = re.sub(r"^ArduinoMega\s+", "", name).replace("_", " ").strip()
    return name[:1].upper() + name[1:]


DEFAULT_SECTIONS = [{"name": "Wszystkie", "rest": True}, {"name": "Włączone", "on": True}]


class SwitchesScreen(Screen):
    tab = NumericProperty(0)                # indeks aktywnej sekcji
    status = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._cfg = {}
        self._exclude_re = [re.compile(p) for p in DEFAULT_EXCLUDE]
        self._items = []
        self._tiles = {}
        self._hold = {}                     # entity_id -> (stan, do kiedy)
        self._event = None
        self._busy = False

    def configure(self, cfg: dict):
        self._cfg = cfg or {}
        self._exclude_re = [re.compile(p)
                            for p in self._cfg.get("exclude_patterns", DEFAULT_EXCLUDE)]
        self._sections = self._cfg.get("sections") or DEFAULT_SECTIONS
        # encja -> indeks sekcji, do której należy (pierwsza, która ją wymienia)
        self._home = {}
        for i, sec in enumerate(self._sections):
            for eid in sec.get("entities", []):
                self._home.setdefault(eid, i)
        self._rest = next((i for i, s in enumerate(self._sections) if s.get("rest")), None)
        tabs = self.ids.tabs
        tabs.clear_widgets()
        self._chips = []
        for i, sec in enumerate(self._sections):
            chip = make("FilterChip", text=sec["name"], selected=(i == self.tab))
            chip.bind(on_release=lambda _c, idx=i: setattr(self, "tab", idx))
            tabs.add_widget(chip)
            self._chips.append(chip)

    def _section_of(self, eid):
        return self._home.get(eid, self._rest)

    def _is_protected(self, eid) -> bool:
        idx = self._section_of(eid)
        if idx is None:
            return False
        protect = self._sections[idx].get("protect", [])
        return protect == "all" or eid in protect

    # --- odświeżanie ----------------------------------------------------------------
    def on_enter(self, *_):
        self.refresh()
        self._event = Clock.schedule_interval(lambda _dt: self.refresh(), REFRESH_SECONDS)

    def on_leave(self, *_):
        if self._event:
            self._event.cancel()
            self._event = None

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        App.get_running_app().fetch_switches(self._on_data)

    def _visible(self, item) -> bool:
        eid = item["entity_id"]
        if eid in self._cfg.get("exclude", []):
            return False
        return not any(r.search(eid) for r in self._exclude_re)

    def _on_data(self, items, error):
        self._busy = False
        if error and items is None:
            self.status = f"Brak danych z HA: {error}"
            return
        self.status = ""
        now = time.monotonic()
        names = self._cfg.get("names", {})
        result = []
        for it in items:
            if not self._visible(it):
                continue
            if self._section_of(it["entity_id"]) is None:
                continue                    # nie należy do żadnej sekcji i brak sekcji "rest"
            held = self._hold.get(it["entity_id"])
            state = held[0] if held and held[1] > now else it["state"]
            result.append({**it, "state": state,
                           "label": names.get(it["entity_id"]) or clean_name(it["name"])})
        result.sort(key=lambda x: pl.sort_key(x["label"]))      # alfabetycznie (polski alfabet)
        self._items = result
        for i, (sec, chip) in enumerate(zip(self._sections, self._chips)):
            chip.text = f"{sec['name']} ({len(self._in_section(i))})"
        self._render()

    def _in_section(self, idx):
        sec = self._sections[idx]
        if sec.get("on"):
            return [x for x in self._items if x["state"] == "on"]
        return [x for x in self._items if self._section_of(x["entity_id"]) == idx]

    def on_tab(self, *_):
        for i, chip in enumerate(self._chips):
            chip.selected = (i == self.tab)
        self._render()

    def _render(self):
        grid = self.ids.grid
        shown = self._in_section(self.tab) if self._sections else []
        if [t.entity_id for t in grid.children[::-1]] != [x["entity_id"] for x in shown]:
            grid.clear_widgets()
            self._tiles = {}
            readonly = set(self._cfg.get("readonly", []))
            for x in shown:
                tile = make("DeviceTile", entity_id=x["entity_id"], name=x["label"],
                            icon=icon_for(x["entity_id"], x["name"]),
                            protected=self._is_protected(x["entity_id"]),
                            readonly=x["entity_id"] in readonly)
                tile.bind(on_release=lambda t: self.on_tile(t))
                grid.add_widget(tile)
                self._tiles[x["entity_id"]] = tile
        for x in shown:
            tile = self._tiles[x["entity_id"]]
            tile.state_text = x["state"]
            # moc z gniazdka z pomiarem (czujnik tego samego urządzenia w HA)
            power = x.get("power")
            tile.power_text = (f"{pl.num(power, 0)} {x.get('power_unit') or 'W'}"
                               if power is not None else "")

    # --- przełączanie ---------------------------------------------------------------
    def on_tile(self, tile):
        if tile.readonly or tile.state_text not in ("on", "off"):
            return                                       # tylko podgląd / niedostępny
        turn_on = tile.state_text == "off"
        if tile.protected:
            ConfirmDialog(
                title=f"{'Włączyć' if turn_on else 'Wyłączyć'} „{tile.name}”?",
                message="Ten włącznik jest chroniony - przełączenie wymaga potwierdzenia "
                        "(settings.json → switches.sections → protect).",
                confirm_text="Włącz" if turn_on else "Wyłącz",
                action=lambda: self._toggle(tile, turn_on)).open()
        else:
            self._toggle(tile, turn_on)

    def _toggle(self, tile, turn_on):
        new_state = "on" if turn_on else "off"
        tile.state_text = new_state                       # od razu na ekranie
        self._hold[tile.entity_id] = (new_state, time.monotonic() + HOLD_AFTER_TOGGLE)
        domain = tile.entity_id.split(".", 1)[0]

        def done(_result, error):
            if error:
                self.status = f"Nie udało się przełączyć „{tile.name}”: {error}"
                self._hold.pop(tile.entity_id, None)
            Clock.schedule_once(lambda _dt: self.refresh(), 1.5)

        App.get_running_app().call_service(domain, "turn_on" if turn_on else "turn_off",
                                           {"entity_id": tile.entity_id}, done)
