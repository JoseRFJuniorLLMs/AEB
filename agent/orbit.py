# AEB-STREAM — agent/orbit.py
# Mecânica orbital: parse de TLE, propagação SGP4 e projeção para a variedade
# produto H × S × E do HeraclitusDB.
#
# Convenção geométrica (spec AEB):
#   S (esférico)   -> posição orbital: ponto subsatélite na esfera unitária (lat/lon)
#   E (euclidiano) -> métricas contínuas lineares (altitude, telemetria: temp, tensão…)
#   H (hiperbólico)-> hierarquia profunda do hardware (Satelite→Payload→Camera→Sensor)
#
# Sem dependências pesadas: só `sgp4` para a propagação. A conversão TEME→geodésico
# (lat/lon/alt) é implementada aqui (GMST + WGS84), não delegada a skyfield.

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sgp4.api import Satrec, jday

# WGS84
_WGS84_A = 6378.137          # semieixo maior (km)
_WGS84_F = 1.0 / 298.257223563
_WGS84_E2 = _WGS84_F * (2.0 - _WGS84_F)
_MU_EARTH = 398600.4418      # km^3/s^2 (GM da Terra)


@dataclass
class OrbitalElements:
    """Elementos médios extraídos diretamente do TLE (sem propagação)."""
    catnr: int
    name: str
    epoch: datetime
    inclination_deg: float
    raan_deg: float            # ascensão reta do nó ascendente
    eccentricity: float
    arg_perigee_deg: float
    mean_anomaly_deg: float
    mean_motion_revday: float  # revoluções por dia
    bstar: float

    @property
    def semi_major_axis_km(self) -> float:
        """a = (μ / n²)^(1/3), com n em rad/s."""
        n_rad_s = self.mean_motion_revday * 2.0 * math.pi / 86400.0
        return (_MU_EARTH / (n_rad_s * n_rad_s)) ** (1.0 / 3.0)

    @property
    def period_min(self) -> float:
        return 1440.0 / self.mean_motion_revday if self.mean_motion_revday else 0.0


@dataclass
class SubPoint:
    """Posição subsatélite num instante (resultado da propagação)."""
    when: datetime
    lat_deg: float
    lon_deg: float
    alt_km: float
    r_teme_km: tuple[float, float, float] = field(default=(0.0, 0.0, 0.0))


def _tle_epoch_to_datetime(line1: str) -> datetime:
    """Campo de época do TLE (cols 19-32 da linha 1): YYDDD.DDDDDDDD."""
    raw = line1[18:32].strip()
    yy = int(raw[:2])
    year = 2000 + yy if yy < 57 else 1900 + yy   # convenção NORAD
    doy = float(raw[2:])
    base = datetime(year, 1, 1, tzinfo=timezone.utc)
    return base.fromordinal(base.toordinal() + int(doy) - 1).replace(
        tzinfo=timezone.utc
    ) + _frac_day(doy)


def _frac_day(doy: float):
    from datetime import timedelta
    return timedelta(days=doy - int(doy))


def parse_tle(line1: str, line2: str, name: str = "") -> OrbitalElements:
    """Extrai os elementos médios das duas linhas do TLE (formato de colunas fixas)."""
    line1 = line1.rstrip()
    line2 = line2.rstrip()
    if not (line1.startswith("1 ") and line2.startswith("2 ")):
        raise ValueError("TLE inválido: as linhas devem começar por '1 ' e '2 '")

    catnr = int(line2[2:7])
    # bstar: campo 54-61, mantissa implícita + expoente (ex.: ' 12345-3' => 0.12345e-3)
    bstar_raw = line1[53:61].strip()
    bstar = _expfield(bstar_raw)

    return OrbitalElements(
        catnr=catnr,
        name=name or f"CATNR-{catnr}",
        epoch=_tle_epoch_to_datetime(line1),
        inclination_deg=float(line2[8:16]),
        raan_deg=float(line2[17:25]),
        eccentricity=float("0." + line2[26:33].strip()),
        arg_perigee_deg=float(line2[34:42]),
        mean_anomaly_deg=float(line2[43:51]),
        mean_motion_revday=float(line2[52:63]),
        bstar=bstar,
    )


def _expfield(s: str) -> float:
    """Campo exponencial empacotado do TLE, ex.: '12345-3' -> 0.12345e-3."""
    if not s or s in ("00000-0", "00000+0"):
        return 0.0
    s = s.replace(" ", "")
    sign = -1.0 if s[0] == "-" else 1.0
    s = s.lstrip("+-")
    if "-" in s[1:] or "+" in s[1:]:
        # separa mantissa e expoente
        for i in range(1, len(s)):
            if s[i] in "+-":
                mant = float("0." + s[:i])
                exp = int(s[i:])
                return sign * mant * (10.0 ** exp)
    return sign * float("0." + s)


def _gmst_rad(jd: float, fr: float) -> float:
    """Greenwich Mean Sidereal Time (rad) — fórmula IAU 1982 (suficiente p/ PoC)."""
    # T em séculos julianos desde J2000.0
    tut1 = ((jd - 2451545.0) + fr) / 36525.0
    gmst_sec = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * tut1
        + 0.093104 * tut1 * tut1
        - 6.2e-6 * tut1 * tut1 * tut1
    )
    gmst = math.radians((gmst_sec % 86400.0) / 240.0)  # 1s = 1/240 grau
    return gmst % (2.0 * math.pi)


def _teme_to_geodetic(r_km, jd: float, fr: float) -> tuple[float, float, float]:
    """TEME → ECEF (rotação por GMST) → geodésico WGS84 (lat, lon graus; alt km)."""
    gmst = _gmst_rad(jd, fr)
    x, y, z = r_km
    # rotação TEME->ECEF em torno de Z por -GMST (ignora nutação/movimento polar)
    cos_g, sin_g = math.cos(gmst), math.sin(gmst)
    xe = cos_g * x + sin_g * y
    ye = -sin_g * x + cos_g * y
    ze = z

    lon = math.atan2(ye, xe)
    # latitude geodésica por iteração (Bowring)
    p = math.hypot(xe, ye)
    lat = math.atan2(ze, p * (1.0 - _WGS84_E2))
    for _ in range(6):
        sin_lat = math.sin(lat)
        n = _WGS84_A / math.sqrt(1.0 - _WGS84_E2 * sin_lat * sin_lat)
        alt = p / math.cos(lat) - n
        lat = math.atan2(ze, p * (1.0 - _WGS84_E2 * n / (n + alt)))
    sin_lat = math.sin(lat)
    n = _WGS84_A / math.sqrt(1.0 - _WGS84_E2 * sin_lat * sin_lat)
    alt = p / math.cos(lat) - n
    return math.degrees(lat), (math.degrees(lon) + 540.0) % 360.0 - 180.0, alt


def propagate(line1: str, line2: str, when: datetime | None = None) -> SubPoint:
    """Propaga o TLE via SGP4 para `when` (UTC, default=agora) e devolve o subponto."""
    when = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    sat = Satrec.twoline2rv(line1.rstrip(), line2.rstrip())
    jd, fr = jday(
        when.year, when.month, when.day,
        when.hour, when.minute, when.second + when.microsecond / 1e6,
    )
    err, r, _v = sat.sgp4(jd, fr)
    if err != 0:
        raise RuntimeError(f"SGP4 falhou (código {err}) — TLE possivelmente expirado")
    lat, lon, alt = _teme_to_geodetic(r, jd, fr)
    return SubPoint(when=when, lat_deg=lat, lon_deg=lon, alt_km=alt, r_teme_km=tuple(r))


# ── Projeção para a variedade produto H × S × E ────────────────────────────────

def spherical_vector(sub: SubPoint) -> list[float]:
    """S — ponto subsatélite na esfera unitária S² (vetor direção, |v|=1)."""
    lat = math.radians(sub.lat_deg)
    lon = math.radians(sub.lon_deg)
    return [
        math.cos(lat) * math.cos(lon),
        math.cos(lat) * math.sin(lon),
        math.sin(lat),
    ]


def euclidean_vector(el: OrbitalElements, sub: SubPoint, telemetry: dict | None = None) -> list[float]:
    """E — métricas contínuas lineares. Sem telemetria, usa escalares orbitais."""
    t = telemetry or {}
    return [
        float(sub.alt_km),
        float(el.eccentricity),
        float(el.mean_motion_revday),
        float(t.get("battery_temp", 0.0)),
        float(t.get("solar_voltage", 0.0)),
        float(t.get("current_a", 0.0)),
    ]


def hyperbolic_vector(catnr: int, depth: int = 0, dim: int = 4) -> list[float]:
    """H — embutimento hiperbólico da hierarquia de hardware.

    Convenção do Poincaré ball: |x| = profundidade (raiz≈origem, folhas→borda).
    Para o nó Satélite (depth=0) fica perto da origem; subsistemas mais profundos
    afastam-se radialmente. A direção é derivada do CATNR (determinística), o raio
    da profundidade. Mantém |x| < 1 (dentro da bola).
    """
    # raio cresce com a profundidade mas satura antes da borda (anti-colapso)
    radius = 1.0 - 1.0 / (1.0 + 0.6 * (depth + 1))   # depth0≈0.375, cresce p/ <1
    # direção pseudo-aleatória estável a partir do CATNR
    ang = [((catnr * (i + 1) * 2654435761) % 100000) / 100000.0 * 2 * math.pi
           for i in range(dim)]
    raw = [math.cos(a) for a in ang]
    norm = math.sqrt(sum(c * c for c in raw)) or 1.0
    return [radius * c / norm for c in raw]
