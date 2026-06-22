# AEB-STREAM — agent/graph.py
# Grafo de caso temporal: reconstrói, a partir do log do HeraclitusDB, o estado
# acumulado de cada satélite (nó-raiz de hardware) e a série de OrbitState. É a
# memória sobre a qual o daemon corre os detectores de anomalia.
#
# Não toca nas fontes: só consome eventos imutáveis (Satelite, OrbitState).

from __future__ import annotations

from dataclasses import dataclass, field


def _clean_kind(k) -> str:
    s = str(k or "")
    if s.startswith('Custom("') and s.endswith('")'):
        return s[8:-2]
    return s


@dataclass
class EstadoOrbital:
    """Uma leitura OrbitState normalizada (do log)."""
    lsn: int
    event_id: str
    catnr: str
    satellite_id: str
    ts: str
    lat: float
    lon: float
    alt_km: float
    battery_temp: float | None
    solar_voltage: float | None
    current_a: float | None
    eclipse: bool


@dataclass
class Satelite:
    catnr: str
    nome: str
    ulid: str | None = None
    inclinacao_deg: float | None = None
    historico: list[EstadoOrbital] = field(default_factory=list)


class SatGraph:
    """Grafo acumulativo: satélites + a sua série temporal de OrbitState."""

    def __init__(self) -> None:
        self.satelites: dict[str, Satelite] = {}   # catnr -> Satelite
        self.por_evento: dict[str, EstadoOrbital] = {}

    # ── ingestão de eventos do log ────────────────────────────────────────────
    def ingest(self, node: dict) -> EstadoOrbital | None:
        kind = _clean_kind(node.get("kind"))
        attrs = node.get("attrs") or {}
        if kind == "Satelite":
            self._ingest_satelite(node, attrs)
            return None
        if kind == "OrbitState":
            return self._ingest_state(node, attrs)
        return None

    def _ingest_satelite(self, node: dict, attrs: dict) -> None:
        catnr = str(attrs.get("catnr", ""))
        if not catnr:
            return
        sat = self.satelites.setdefault(catnr, Satelite(catnr, attrs.get("nome", catnr)))
        sat.ulid = node.get("id") or sat.ulid
        sat.nome = attrs.get("nome", sat.nome)
        sat.inclinacao_deg = _f(attrs.get("inclinacao_deg"))

    def _ingest_state(self, node: dict, attrs: dict) -> EstadoOrbital | None:
        catnr = str(attrs.get("catnr", ""))
        if not catnr:
            return None
        est = EstadoOrbital(
            lsn=int(node.get("lsn", 0)),
            event_id=node.get("id", ""),
            catnr=catnr,
            satellite_id=attrs.get("satellite_id", catnr),
            ts=attrs.get("ts", ""),
            lat=_f(attrs.get("latitude")) or 0.0,
            lon=_f(attrs.get("longitude")) or 0.0,
            alt_km=_f(attrs.get("altitude_km")) or 0.0,
            battery_temp=_f(attrs.get("battery_temp")),
            solar_voltage=_f(attrs.get("solar_voltage")),
            current_a=_f(attrs.get("current_a")),
            eclipse=str(attrs.get("eclipse", "")).lower() == "true",
        )
        sat = self.satelites.setdefault(
            catnr, Satelite(catnr, est.satellite_id)
        )
        sat.historico.append(est)
        self.por_evento[est.event_id] = est
        return est

    # ── consultas usadas pelos detectores ─────────────────────────────────────
    def ultimos(self, catnr: str, n: int = 2) -> list[EstadoOrbital]:
        return self.satelites.get(catnr, Satelite(catnr, catnr)).historico[-n:]

    def media_altitude(self, catnr: str) -> float | None:
        h = self.satelites.get(catnr)
        if not h or not h.historico:
            return None
        alts = [e.alt_km for e in h.historico if e.alt_km]
        return sum(alts) / len(alts) if alts else None

    def stats(self) -> dict:
        return {
            "satelites": len(self.satelites),
            "estados": sum(len(s.historico) for s in self.satelites.values()),
        }


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
