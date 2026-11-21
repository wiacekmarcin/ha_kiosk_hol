"""Kartka z kalendarza z kalbi.pl: pobieranie, parsowanie i cache.

Strona dnia: https://www.kalbi.pl/<dzień>-<miesiąc w dopełniaczu>, np. /19-listopada
(bez roku - kalbi pokazuje bieżący rok; zgodność roku jest sprawdzana).

Cache:
  - pamięć + dysk (~/.cache/ha_kiosk/kalbi/RRRR-MM-DD.json), przetrwa restart;
  - kartka danego dnia się nie zmienia -> pobierana tylko raz;
  - pliki starsze niż PRUNE_DAYS są usuwane;
  - po błędzie sieci kolejna próba najwcześniej po RETRY_AFTER sekundach.
robots.txt kalbi.pl pozwala na pobieranie (User-agent: * Allow: /).
"""
import json
import math
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests

from kiosk import pl

BASE_URL = "https://www.kalbi.pl"
USER_AGENT = "HA-Kiosk/1.0 (kartka z kalendarza; 1 zapytanie na dzien)"
CACHE_VERSION = 1
PRUNE_DAYS = 14
RETRY_AFTER = 15 * 60
TIMEOUT = 15

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "ha_kiosk" / "kalbi"


class KalbiError(Exception):
    pass


def url_for(day: date) -> str:
    return f"{BASE_URL}/{day.day}-{pl.MONTHS_GEN[day.month - 1]}"


# --------------------------------------------------------------------------------------
# Minimalne drzewo HTML na bazie html.parser (bez zewnętrznych zależności)
# --------------------------------------------------------------------------------------
VOID = {"br", "img", "input", "meta", "link", "hr", "source", "wbr", "area", "col"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.children, self.parent = tag, dict(attrs or {}), [], parent

    @property
    def classes(self):
        return self.attrs.get("class", "").split()

    def find_all(self, cls=None, tag=None):
        out = []
        for ch in self.children:
            if isinstance(ch, Node):
                if (cls is None or cls in ch.classes) and (tag is None or ch.tag == tag):
                    out.append(ch)
                out.extend(ch.find_all(cls, tag))
        return out

    def find(self, cls=None, tag=None):
        found = self.find_all(cls, tag)
        return found[0] if found else None

    def text(self, br="\n"):
        parts = []
        for ch in self.children:
            if isinstance(ch, str):
                parts.append(ch)
            elif ch.tag == "br":
                parts.append(br)
            elif ch.tag not in ("script", "style", "h3"):
                parts.append(ch.text(br))
        return "".join(parts)


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:      # domknij niedomknięte
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


# --------------------------------------------------------------------------------------
# Parsowanie kartki
# --------------------------------------------------------------------------------------
def parse(html: str, day: date) -> dict:
    builder = _TreeBuilder()
    builder.feed(html)
    card = builder.root.find("calCard-container")
    if card is None:
        raise KalbiError("nie znaleziono kartki na stronie (zmienił się układ strony?)")

    def txt(cls, node=card):
        n = node.find(cls)
        return clean(n.text(" ")) if n else ""

    year = txt("calCard-year")
    day_num = txt("calCard-day")
    if year != str(day.year) or day_num != str(day.day):
        raise KalbiError(f"kalbi zwróciło kartkę {day_num}.{year} zamiast {day:%d.%Y}")

    data = {
        "date": day.isoformat(),
        "weekday": txt("calCard-day-week"),
        "month": txt("calCard-month"),
        "day_of_year": txt("calCard-dayyear"),
        "week": txt("calCard-week"),
    }

    # imieniny: nazwy przed "oraz" to główne, reszta pozostałe
    main, other, target = [], [], None
    nd = card.find("calCard-name-day")
    if nd:
        target = main
        for ch in nd.children:
            if isinstance(ch, Node) and ch.tag == "span" and "oraz" in ch.text():
                target = other
            elif isinstance(ch, Node) and ch.tag == "a":
                target.append(clean(ch.text()))
    data["namedays_main"], data["namedays_other"] = main, other

    ent = card.find("calCard-ententa")
    data["holidays"] = [clean(a.text()) for a in ent.find_all(tag="a")] if ent else []

    prov = card.find("calCard_proverb")
    data["proverbs"] = [clean(li.text()) for li in prov.find_all(tag="li")] if prov else []

    # Słońce: "Świt: 06:23", "Wsch. Sł.: 07:01", ...
    sun = {}
    hours = card.find("calCard-astro-sun-hours")
    if hours:
        for line in hours.text("\n").split("\n"):
            line = clean(line)
            m = re.match(r"(.+?):\s*(.+)$", line)
            if m:
                key = m.group(1)
                if key.startswith("Świt"):
                    sun["dawn"] = m.group(2)
                elif key.startswith("Wsch"):
                    sun["rise"] = m.group(2)
                elif key.startswith("Górowanie"):
                    sun["noon"] = m.group(2)
                elif key.startswith("Zach"):
                    sun["set"] = m.group(2)
                elif key.startswith("Zmierzch"):
                    sun["dusk"] = m.group(2)
                elif key.startswith("Długość"):
                    sun["length"] = m.group(2)
    zod = card.find("calCard-astro-sun-zodiac")
    if zod:
        span = zod.find(tag="span")
        title = span.attrs.get("title", "") if span else ""
        sun["sign"] = title.split(":", 1)[-1].strip()
    data["sun"] = sun

    moon = {"lines": [], "sign": ""}
    mz = card.find("calCard-astro-moon-zodiac")
    if mz:
        moon["lines"] = [clean(d.text()) for d in mz.find_all(tag="div") if clean(d.text())]
    label = card.find("calCard-moon-sign-label")
    if label:
        moon["sign"] = clean(label.text())
    data["moon"] = moon

    quote = card.find("calCard-quotes")
    if quote:
        content = quote.find("calCard_proverb-content")
        q = content.find(tag="i") if content else None
        q_text = clean(q.text()) if q else ""
        full = clean(content.text(" ")) if content else ""
        author = clean(full[len(q_text):]) if q_text and full.startswith(q_text) else ""
        data["quote"] = {"text": q_text.rstrip(" -–"), "author": author}
    else:
        data["quote"] = {"text": "", "author": ""}

    lit = card.find("calCard-liturgia")
    if lit:
        rank = txt("calCard-liturgia-ranga", lit)
        body = clean(lit.text(" "))
        data["church"] = {"text": clean(body.replace(rank, "")) if rank else body, "rank": rank}
    else:
        data["church"] = {"text": "", "rank": ""}

    data["location"] = txt("calCard-location-label").replace("Lokalizacja:", "").strip()
    return data


# --------------------------------------------------------------------------------------
# Dane liczone lokalnie (bez sieci)
# --------------------------------------------------------------------------------------
SYNODIC_MONTH = 29.530588853
KNOWN_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
MOON_PHASES = [  # (nazwa, ikona MDI)
    ("nów", "moon-new"),
    ("przybywający sierp", "moon-waxing-crescent"),
    ("pierwsza kwadra", "moon-first-quarter"),
    ("przybywający garb", "moon-waxing-gibbous"),
    ("pełnia", "moon-full"),
    ("ubywający garb", "moon-waning-gibbous"),
    ("ostatnia kwadra", "moon-last-quarter"),
    ("ubywający sierp", "moon-waning-crescent"),
]


def moon_phase(day: date) -> dict:
    """Faza Księżyca w południe danego dnia (przybliżenie, dokładność ~kilka godzin)."""
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
    age = ((noon - KNOWN_NEW_MOON).total_seconds() / 86400) % SYNODIC_MONTH
    frac = age / SYNODIC_MONTH
    name, icon = MOON_PHASES[int(frac * 8 + 0.5) % 8]
    illumination = (1 - math.cos(2 * math.pi * frac)) / 2
    return {"name": name, "icon": icon, "illumination": round(illumination * 100),
            "age": round(age, 1)}


def local_info(day: date) -> dict:
    """Pola kartki, które da się policzyć bez kalbi.pl."""
    return {
        "date": day.isoformat(),
        "weekday": pl.DAYS[day.weekday()].capitalize(),
        "month": pl.MONTHS_NOM[day.month - 1],
        "day_of_year": f"{day.timetuple().tm_yday} dzień roku",
        "week": f"{day.isocalendar()[1]} tydzień roku",
    }


# --------------------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------------------
class KalbiCache:
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.dir = Path(cache_dir)
        self._mem = {}
        self._lock = threading.Lock()
        self._inflight = set()
        self._failed_at = {}

    def _path(self, day: date) -> Path:
        return self.dir / f"{day.isoformat()}.json"

    def cached(self, day: date):
        """Kartka z pamięci lub dysku, bez sieci; None gdy brak."""
        key = day.isoformat()
        with self._lock:
            if key in self._mem:
                return self._mem[key]
        try:
            with open(self._path(day), encoding="utf-8") as f:
                stored = json.load(f)
            if stored.get("v") != CACHE_VERSION:
                return None
            with self._lock:
                self._mem[key] = stored
            return stored
        except (OSError, ValueError):
            return None

    def fetch(self, day: date) -> dict:
        """Pobiera kartkę z kalbi.pl (blokujące) i zapisuje w cache."""
        try:
            resp = requests.get(url_for(day), timeout=TIMEOUT,
                                headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
        except requests.RequestException as e:
            raise KalbiError(f"kalbi.pl: {e}") from e
        resp.encoding = "utf-8"
        stored = {"v": CACHE_VERSION, "fetched_at": datetime.now().isoformat(timespec="seconds"),
                  "url": url_for(day), "data": parse(resp.text, day)}
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path(day).with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(stored, f, ensure_ascii=False, indent=1)
        tmp.replace(self._path(day))
        with self._lock:
            self._mem[day.isoformat()] = stored
        return stored

    def get_async(self, day: date, callback=None, force=False):
        """Kartka z cache albo pobranie w wątku. callback(stored | None, error | None)
        wołany z wątku roboczego (UI powinno przełączyć się przez Clock)."""
        stored = self.cached(day)
        if stored:
            if callback:
                callback(stored, None)
            return
        key = day.isoformat()
        failed = self._failed_at.get(key)
        if not force and failed and time.monotonic() - failed < RETRY_AFTER:
            if callback:
                callback(None, "brak połączenia z kalbi.pl (kolejna próba za kilka minut)")
            return
        with self._lock:
            if key in self._inflight:         # już pobierane - nie dubluj zapytań
                return
            self._inflight.add(key)

        def work():
            try:
                stored, error = self.fetch(day), None
                self._failed_at.pop(key, None)
            except (KalbiError, OSError) as e:
                stored, error = None, str(e)
                self._failed_at[key] = time.monotonic()
            finally:
                with self._lock:
                    self._inflight.discard(key)
            if callback:
                callback(stored, error)

        threading.Thread(target=work, name=f"kalbi-{key}", daemon=True).start()

    def prefetch(self, days):
        for d in days:
            self.get_async(d)

    def prune(self, keep_days: int = PRUNE_DAYS):
        limit = date.today() - timedelta(days=keep_days)
        for f in self.dir.glob("*.json"):
            try:
                if date.fromisoformat(f.stem) < limit:
                    f.unlink()
            except (ValueError, OSError):
                pass
