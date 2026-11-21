"""Wschody i zachody słońca na każdy dzień roku - obliczenia astronomiczne (NOAA).

Bez internetu i bez bibliotek, zgodnie z HA (biblioteka astral) co do kilkunastu sekund.
Czas lokalny bierzemy ze strefy systemu (Android/Linux), więc zmiana czasu
letni/zimowy jest widoczna na wykresie jako skok o godzinę.
"""
import math
from datetime import date, datetime, timedelta, timezone

DEFAULT_LOCATION = {"latitude": 52.23, "longitude": 21.01, "elevation": 0}   # gdy brak HA
ZENITH = 90.833        # środek tarczy słońca 50' pod horyzontem (refrakcja + promień tarczy)
EARTH_RADIUS = 6356900  # m - jak w astral (HA)


def _zenith(elevation: float) -> float:
    """Z wysokości n.p.m. widać dalej za horyzont: wschód wcześniej, zachód później."""
    if not elevation or elevation <= 0:
        return ZENITH
    return ZENITH + math.degrees(math.acos(EARTH_RADIUS / (EARTH_RADIUS + elevation)))


def _solar(jd: float):
    """(równanie czasu w minutach, deklinacja w radianach) w chwili jd (dzień juliański).

    Algorytm z kalkulatora NOAA (Meeus).
    """
    t = (jd - 2451545.0) / 36525.0
    l0 = math.radians((280.46646 + t * (36000.76983 + t * 0.0003032)) % 360)
    m = math.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    c = (math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * m) * (0.019993 - 0.000101 * t) + math.sin(3 * m) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * t)
    lam = math.radians(math.degrees(l0) + c - 0.00569 - 0.00478 * math.sin(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = math.radians(eps0 + 0.00256 * math.cos(omega))
    decl = math.asin(math.sin(eps) * math.sin(lam))
    y = math.tan(eps / 2) ** 2
    eqtime = 4 * math.degrees(y * math.sin(2 * l0) - 2 * e * math.sin(m)
                              + 4 * e * y * math.sin(m) * math.cos(2 * l0)
                              - 0.5 * y * y * math.sin(4 * l0) - 1.25 * e * e * math.sin(2 * m))
    return eqtime, decl


def _jd(day: date, utc_minutes: float) -> float:
    return day.toordinal() + 1721424.5 + utc_minutes / 1440


def _local(day: date, utc_minutes: float) -> datetime:
    """Minuty od północy UTC danego dnia -> czas lokalny (naive) wg strefy systemu."""
    utc = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(minutes=utc_minutes)
    return utc.astimezone().replace(tzinfo=None)


def _event(day: date, lat: float, longitude: float, zenith: float, sign: int, guess: float):
    """(minuty UTC wschodu (sign -1) albo zachodu (+1) lub None, cos kąta godzinnego).
    Dwie iteracje: pozycję słońca liczymy na chwilę samego zdarzenia."""
    minutes, cos_ha = guess, 0.0
    for _ in range(2):
        eqtime, decl = _solar(_jd(day, minutes))
        cos_ha = (math.cos(math.radians(zenith)) / (math.cos(lat) * math.cos(decl))
                  - math.tan(lat) * math.tan(decl))
        if abs(cos_ha) >= 1:
            return None, cos_ha
        ha = math.degrees(math.acos(cos_ha))
        minutes = 720 - 4 * (longitude - sign * ha) - eqtime
    return minutes, cos_ha


def sun_day(day: date, latitude: float, longitude: float, elevation: float = 0) -> dict:
    """{"date", "rise", "set", "noon" (datetime lokalne albo None), "length" (minuty)}.

    Dzień polarny: length 1440 i rise/set None; noc polarna: length 0.
    """
    lat = math.radians(latitude)
    zenith = _zenith(elevation)
    eqtime, _decl = _solar(_jd(day, 720 - 4 * longitude))
    noon = 720 - 4 * longitude - eqtime
    rise, cos_ha = _event(day, lat, longitude, zenith, -1, noon - 360)
    sset, _ = _event(day, lat, longitude, zenith, +1, noon + 360)
    if rise is None or sset is None:
        length = 1440.0 if cos_ha <= -1 else 0.0
        return {"date": day, "rise": None, "set": None, "noon": _local(day, noon), "length": length}
    return {"date": day, "rise": _local(day, rise), "set": _local(day, sset),
            "noon": _local(day, noon), "length": sset - rise}


def sun_year(year: int, latitude: float, longitude: float, elevation: float = 0) -> list:
    """Lista sun_day dla każdego dnia roku."""
    day = date(year, 1, 1)
    result = []
    while day.year == year:
        result.append(sun_day(day, latitude, longitude, elevation))
        day += timedelta(days=1)
    return result


def minutes_of_day(dt: datetime) -> float:
    return dt.hour * 60 + dt.minute + dt.second / 60


def duration(minutes: float, seconds: bool = False) -> str:
    """512.4 -> '8 h 32 min';  seconds=True: 2.68 -> '2 min 41 s'."""
    total = round(abs(minutes) * 60) if seconds else round(abs(minutes)) * 60
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    parts = []
    if h:
        parts.append(f"{h} h")
    if m or (not h and not (seconds and s)):
        parts.append(f"{m} min")
    if seconds and s and not h:
        parts.append(f"{s} s")
    return " ".join(parts)


def summary(today: date, latitude: float, longitude: float, elevation: float = 0) -> dict:
    """Dane do okna: rok, dziś, wczoraj, najdłuższy i najkrótszy dzień, najbliższe przesilenie."""
    year = sun_year(today.year, latitude, longitude, elevation)
    now = year[today.timetuple().tm_yday - 1]
    yesterday = sun_day(today - timedelta(days=1), latitude, longitude, elevation)
    longest = max(year, key=lambda d: d["length"])
    shortest = min(year, key=lambda d: d["length"])
    # najbliższe przesilenie (po grudniowym - czerwcowe w przyszłym roku)
    solstices = [longest["date"], shortest["date"]]
    if today > max(solstices):
        nxt = sun_year(today.year + 1, latitude, longitude, elevation)
        solstices.append(max(nxt, key=lambda d: d["length"])["date"])
    upcoming = min(d for d in solstices if d >= today)
    return {"year": year, "today": now, "yesterday": yesterday,
            "longest": longest, "shortest": shortest, "next_solstice": upcoming}
