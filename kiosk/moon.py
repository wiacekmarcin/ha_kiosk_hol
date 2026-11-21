"""Księżyc: faza, oświetlenie, wschód i zachód, daty głównych faz - obliczenia lokalne.

Pozycja Księżyca wg Meeusa (rozdz. 47, najważniejsze wyrazy szeregu): dokładność
około 0,1-0,3 stopnia, czyli 1-2 minut dla wschodu/zachodu i kilkunastu minut dla
chwili faz. Bez internetu i bez bibliotek.
"""
import math
from datetime import date, datetime, timedelta, timezone

SYNODIC_MONTH = 29.530588853
H0 = 0.125              # wysokość środka tarczy przy wschodzie: paralaksa - refrakcja - promień

# (D, M, M', F, współczynnik w 1e-6 stopnia) - długość ekliptyczna
_LON = [
    (0, 0, 1, 0, 6288774), (2, 0, -1, 0, 1274027), (2, 0, 0, 0, 658314),
    (0, 0, 2, 0, 213618), (0, 1, 0, 0, -185116), (0, 0, 0, 2, -114332),
    (2, 0, -2, 0, 58793), (2, -1, -1, 0, 57066), (2, 0, 1, 0, 53322),
    (2, -1, 0, 0, 45758), (0, 1, -1, 0, -40923), (1, 0, 0, 0, -34720),
    (0, 1, 1, 0, -30383), (2, 0, 0, -2, 15327), (0, 0, 1, 2, -12528),
    (0, 0, 1, -2, 10980), (4, 0, -1, 0, 10675), (0, 0, 3, 0, 10034),
    (4, 0, -2, 0, 8548), (2, 1, -1, 0, -7888), (2, 1, 0, 0, -6766),
    (1, 0, -1, 0, -5163), (1, 1, 0, 0, 4987), (2, -1, 1, 0, 4036), (2, 0, 2, 0, 3994),
]
# szerokość ekliptyczna
_LAT = [
    (0, 0, 0, 1, 5128122), (0, 0, 1, 1, 280602), (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237), (2, 0, -1, 1, 55413), (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573), (0, 0, 2, 1, 17198), (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822), (2, -1, 0, -1, 8216), (2, 0, -2, -1, 4324), (2, 0, 1, 1, 4200),
]

PHASES = [  # (nazwa, ikona w opisie) - 8 faz co 45 stopni elongacji
    "Nów", "Przybywający sierp", "Pierwsza kwadra", "Przybywający garb",
    "Pełnia", "Ubywający garb", "Ostatnia kwadra", "Ubywający sierp",
]
MAIN_PHASES = ["Nów", "Pierwsza kwadra", "Pełnia", "Ostatnia kwadra"]


def _jd(dt_utc: datetime) -> float:
    return dt_utc.timestamp() / 86400.0 + 2440587.5


def _from_jd(jd: float) -> datetime:
    """Dzień juliański -> czas lokalny (naive) wg strefy systemu."""
    utc = datetime.fromtimestamp((jd - 2440587.5) * 86400.0, tz=timezone.utc)
    return utc.astimezone().replace(tzinfo=None)


def _local_midnight_jd(day: date) -> float:
    return _jd(datetime(day.year, day.month, day.day).astimezone())


def _moon_ecliptic(jd: float):
    """(długość, szerokość) ekliptyczna Księżyca w stopniach."""
    t = (jd - 2451545.0) / 36525.0
    lp = 218.3164477 + 481267.88123421 * t
    d = math.radians(297.8501921 + 445267.1114034 * t)
    m = math.radians(357.5291092 + 35999.0502909 * t)
    mp = math.radians(134.9633964 + 477198.8675055 * t)
    f = math.radians(93.2720950 + 483202.0175233 * t)
    e = 1 - 0.002516 * t
    lon = lat = 0.0
    for cd, cm, cmp_, cf, coef in _LON:
        lon += coef * (e ** abs(cm)) * math.sin(cd * d + cm * m + cmp_ * mp + cf * f)
    for cd, cm, cmp_, cf, coef in _LAT:
        lat += coef * (e ** abs(cm)) * math.sin(cd * d + cm * m + cmp_ * mp + cf * f)
    return (lp + lon / 1e6) % 360, lat / 1e6


def _sun_longitude(jd: float) -> float:
    t = (jd - 2451545.0) / 36525.0
    l0 = 280.46646 + 36000.76983 * t
    m = math.radians(357.52911 + 35999.05029 * t)
    c = (1.914602 - 0.004817 * t) * math.sin(m) + 0.019993 * math.sin(2 * m) + 0.000289 * math.sin(3 * m)
    return (l0 + c) % 360


def elongation(jd: float) -> float:
    """Kąt Księżyc-Słońce po ekliptyce 0-360: 0 nów, 90 I kwadra, 180 pełnia, 270 III kwadra."""
    return (_moon_ecliptic(jd)[0] - _sun_longitude(jd)) % 360


def phase_info(when: datetime = None) -> dict:
    """{"phase": 0-1 (0 nów, 0,5 pełnia), "illumination": 0-1, "age": dni, "name"}."""
    when = when or datetime.now()
    jd = _jd(when.astimezone())
    el = elongation(jd)
    phase = el / 360
    return {"phase": phase, "illumination": (1 - math.cos(math.radians(el))) / 2,
            "age": phase * SYNODIC_MONTH, "name": PHASES[int((el + 22.5) % 360 // 45)]}


def next_phases(start: datetime = None, count: int = 8) -> list:
    """Najbliższe główne fazy: [(datetime lokalny, nazwa, indeks 0-3)]."""
    start = start or datetime.now()
    jd = _jd(start.astimezone())
    result = []
    step = 0.25                                  # 6 h
    prev = elongation(jd)
    while len(result) < count:
        jd2 = jd + step
        cur = elongation(jd2)
        for k in range(4):
            target = 90 * k
            a = (prev - target + 180) % 360 - 180      # różnica do celu w (-180, 180]
            b = (cur - target + 180) % 360 - 180
            if a < 0 <= b and b - a < 90:              # przejście przez cel
                lo, hi = jd, jd2
                for _ in range(30):
                    mid = (lo + hi) / 2
                    if (elongation(mid) - target + 180) % 360 - 180 < 0:
                        lo = mid
                    else:
                        hi = mid
                result.append((_from_jd((lo + hi) / 2), MAIN_PHASES[k], k))
        jd, prev = jd2, cur
    return sorted(result)[:count]


def _altitude(jd: float, lat: float, lon: float) -> float:
    """Wysokość Księżyca nad horyzontem (stopnie) dla obserwatora lat/lon (stopnie)."""
    lam, beta = _moon_ecliptic(jd)
    t = (jd - 2451545.0) / 36525.0
    eps = math.radians(23.4393 - 0.0130 * t)
    lam, beta = math.radians(lam), math.radians(beta)
    ra = math.atan2(math.sin(lam) * math.cos(eps) - math.tan(beta) * math.sin(eps), math.cos(lam))
    dec = math.asin(math.sin(beta) * math.cos(eps) + math.cos(beta) * math.sin(eps) * math.sin(lam))
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0)
    ha = math.radians(gmst + lon) - ra
    phi = math.radians(lat)
    return math.degrees(math.asin(math.sin(phi) * math.sin(dec)
                                  + math.cos(phi) * math.cos(dec) * math.cos(ha)))


def rise_set(day: date, latitude: float, longitude: float) -> dict:
    """{"rise": datetime|None, "set": datetime|None} w danej dobie lokalnej
    (Księżyc nie co dzień wschodzi i zachodzi - wtedy None)."""
    start = _local_midnight_jd(day)
    end = _local_midnight_jd(day + timedelta(days=1))
    step = 10 / 1440                             # co 10 minut, potem dokładnie
    result = {"rise": None, "set": None}
    jd = start
    prev = _altitude(jd, latitude, longitude) - H0
    while jd < end:
        jd2 = min(jd + step, end)
        cur = _altitude(jd2, latitude, longitude) - H0
        if (prev < 0) != (cur < 0):
            lo, hi, flo = jd, jd2, prev
            for _ in range(20):
                mid = (lo + hi) / 2
                fm = _altitude(mid, latitude, longitude) - H0
                if (fm < 0) == (flo < 0):
                    lo, flo = mid, fm
                else:
                    hi = mid
            key = "rise" if prev < 0 else "set"
            if result[key] is None:
                result[key] = _from_jd((lo + hi) / 2)
        jd, prev = jd2, cur
    return result


def month_phases(year: int, month: int) -> list:
    """Faza każdego dnia miesiąca o 21:00: [(date, phase_info)]."""
    days = []
    d = date(year, month, 1)
    while d.month == month:
        days.append((d, phase_info(datetime(d.year, d.month, d.day, 21))))
        d += timedelta(days=1)
    return days
