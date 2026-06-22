#!/usr/bin/env python3
# AEB-STREAM — pipeline.py  (Os Sentidos)
#
# Consome dados orbitais reais (TLE) da CelesTrak, propaga via SGP4, projeta para
# a variedade produto H × S × E e faz append gRPC no HeraclitusDB (o Rio).
#
# Camadas (LABRA-AGU): pipeline ingere SEM opinar; o append é imutável e leva a
# proveniência (cada OrbitState aponta para o nó Satelite como parent ULID).
#
# Uso:
#   python pipeline.py --dry-run                 # só busca/parse, não grava
#   python pipeline.py --catnr 47699 44883       # Amazonia-1 + CBERS-4A
#   python pipeline.py --grupo --once            # catálogo de satélites BR
#   python pipeline.py --interval 60             # streaming contínuo
#
# Fontes: CelesTrak GP API (sem auth). Space-Track/INPE ficam como TODO (auth).

from __future__ import annotations

import argparse
import logging
import math
import os
import random
import sys
import time
from datetime import datetime, timezone

import requests

sys.path.insert(0, r"D:\DEV\AEB")
sys.path.insert(0, r"D:\DEV\HeraclitusDB\sdk\python")

from agent import orbit  # noqa: E402

log = logging.getLogger("aeb.pipeline")

# Instância DEDICADA da AEB (separada de outros domínios).
AEB_SERVER = os.environ.get("AEB_SERVER", "127.0.0.1:7476")
# Cache local de TLE — resiliência offline + não martelar a CelesTrak.
TLE_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "tle")

# Catálogo de satélites brasileiros (NORAD CATNR) — AEB/INPE.
SATELITES_BR = {
    47699: "AMAZONIA-1",
    44883: "CBERS-4A",
    40336: "CBERS-4",
    25504: "SCD-2",
    22490: "SCD-1",
    43226: "SGDC-1",        # geoestacionário de comunicações
}

CELESTRAK_TIMEOUT = 20


# ── Ingestão de TLE (CelesTrak) ────────────────────────────────────────────────

def _cache_path(catnr: int) -> str:
    return os.path.join(TLE_CACHE_DIR, f"{catnr}.tle")


def _cache_save(catnr: int, text: str):
    try:
        os.makedirs(TLE_CACHE_DIR, exist_ok=True)
        with open(_cache_path(catnr), "w", encoding="utf-8") as f:
            f.write(text)
    except OSError as e:
        log.debug("CATNR %s: não consegui escrever cache — %s", catnr, e)


def _cache_load(catnr: int) -> tuple[str, str, str] | None:
    path = _cache_path(catnr)
    if not os.path.exists(path):
        return None
    age_h = (time.time() - os.path.getmtime(path)) / 3600.0
    with open(path, encoding="utf-8") as f:
        parsed = _parse_tle_text(f.read())
    if parsed:
        log.warning("CATNR %s: usando TLE do CACHE (%.1f h de idade)", catnr, age_h)
    return parsed


def fetch_tle(catnr: int, retries: int = 3) -> tuple[str, str, str] | None:
    """Busca o TLE na CelesTrak; em falha, recorre ao cache local. Em sucesso,
    atualiza o cache. Devolve (nome, linha1, linha2)."""
    urls = [
        f"https://celestrak.org/NORAD/elements/gp.php?CATNR={catnr}&FORMAT=TLE",
        f"https://celestrak.org/api/readdata.php?CATNR={catnr}",
    ]
    for attempt in range(retries):
        for url in urls:
            try:
                resp = requests.get(url, timeout=CELESTRAK_TIMEOUT)
                if resp.status_code == 200 and "1 " in resp.text:
                    _cache_save(catnr, resp.text)         # atualiza cache
                    return _parse_tle_text(resp.text)
                log.warning("CATNR %s: HTTP %s em %s", catnr, resp.status_code, url)
            except requests.RequestException as e:
                log.warning("CATNR %s: rede falhou (%s) — %s", catnr, url, e)
        time.sleep(1.5 * (attempt + 1))  # backoff
    log.error("CATNR %s: CelesTrak indisponível — tentando cache", catnr)
    return _cache_load(catnr)                              # fallback offline


def _parse_tle_text(text: str) -> tuple[str, str, str] | None:
    """Normaliza o texto TLE (com ou sem linha de nome) → (nome, l1, l2)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    l1 = next((l for l in lines if l.startswith("1 ")), None)
    l2 = next((l for l in lines if l.startswith("2 ")), None)
    if not l1 or not l2:
        return None
    name = lines[0] if not lines[0].startswith("1 ") else ""
    return name, l1, l2


# ── Telemetria (simulada para a PoC; substituir por feed real da estação) ──────

def simular_telemetria(el: orbit.OrbitalElements, sub: orbit.SubPoint) -> dict:
    """Gera leituras plausíveis de subsistemas. A temperatura varia com a
    exposição solar (lado iluminado vs. sombra), aproximada pela longitude."""
    eclipse = math.cos(math.radians(sub.lon_deg)) < -0.3   # heurística simples
    base_temp = -5.0 if eclipse else 22.0
    return {
        "battery_temp": round(base_temp + random.uniform(-2, 2), 2),
        "solar_voltage": round((0.0 if eclipse else 48.0) + random.uniform(-1, 1), 2),
        "current_a": round((0.1 if eclipse else 3.2) + random.uniform(-0.2, 0.2), 2),
        "eclipse": eclipse,
    }


# ── Append no HeraclitusDB ─────────────────────────────────────────────────────

def ensure_satelite(client, el: orbit.OrbitalElements) -> str | None:
    """Garante o nó-raiz `Satelite` (hierarquia de hardware) e devolve o seu ULID.
    Idempotente por CATNR: se já existir, reutiliza."""
    existing = client.query(
        f'MATCH (n:Satelite) WHERE n.catnr = "{el.catnr}" RETURN n LIMIT 1'
    )
    if isinstance(existing, list) and existing:
        return existing[0].get("id")

    content = f"Satelite {el.name} (NORAD {el.catnr})"
    attrs = {
        "catnr": str(el.catnr),
        "nome": el.name,
        "inclinacao_deg": f"{el.inclination_deg:.4f}",
        "periodo_min": f"{el.period_min:.2f}",
        "semi_eixo_km": f"{el.semi_major_axis_km:.1f}",
        "agencia": "AEB/INPE",
    }
    lsn = client.append(
        "Satelite", content, agent_id="aeb-pipeline",
        attrs=attrs, hyp=orbit.hyperbolic_vector(el.catnr, depth=0),
    )
    # recupera o ULID pelo lsn (parents exigem ULID, não lsn)
    row = client.query(f"MATCH (n) WHERE n.lsn = {lsn} RETURN n LIMIT 1")
    return row[0].get("id") if isinstance(row, list) and row else None


def append_orbit_state(client, el, sub, telemetry, satelite_ulid: str | None) -> int:
    """Grava um evento OrbitState (telemetria + órbita) com os 3 vetores."""
    content = (
        f"OrbitState {el.name} @ {sub.when.isoformat()} | "
        f"lat={sub.lat_deg:.3f} lon={sub.lon_deg:.3f} alt={sub.alt_km:.1f}km"
    )
    attrs = {
        "satellite_id": el.name,
        "catnr": str(el.catnr),
        "ts": sub.when.isoformat(),
        "latitude": f"{sub.lat_deg:.5f}",
        "longitude": f"{sub.lon_deg:.5f}",
        "altitude_km": f"{sub.alt_km:.2f}",
        "battery_temp": str(telemetry.get("battery_temp", "")),
        "solar_voltage": str(telemetry.get("solar_voltage", "")),
        "current_a": str(telemetry.get("current_a", "")),
        "eclipse": str(telemetry.get("eclipse", "")),
        "fonte": "celestrak",
    }
    return client.append(
        "OrbitState", content, agent_id="aeb-pipeline",
        attrs=attrs,
        sph=orbit.spherical_vector(sub),
        euc=orbit.euclidean_vector(el, sub, telemetry),
        hyp=orbit.hyperbolic_vector(el.catnr, depth=1),
        parents=[satelite_ulid] if satelite_ulid else None,
    )


def ingerir_satelite(client, catnr: int, dry_run: bool) -> bool:
    """Pipeline completo de um satélite: fetch → parse → propaga → append."""
    tle = fetch_tle(catnr)
    if not tle:
        return False
    name, l1, l2 = tle
    try:
        el = orbit.parse_tle(l1, l2, name or SATELITES_BR.get(catnr, ""))
        sub = orbit.propagate(l1, l2)
    except (ValueError, RuntimeError) as e:
        log.error("CATNR %s: parse/propagação falhou — %s", catnr, e)
        return False

    tele = simular_telemetria(el, sub)
    log.info(
        "%-12s lat=%7.3f lon=%8.3f alt=%6.1fkm  bat=%.1f°C V=%.1f%s",
        el.name, sub.lat_deg, sub.lon_deg, sub.alt_km,
        tele["battery_temp"], tele["solar_voltage"],
        " [eclipse]" if tele["eclipse"] else "",
    )
    if dry_run:
        return True

    satelite_ulid = ensure_satelite(client, el)
    lsn = append_orbit_state(client, el, sub, tele, satelite_ulid)
    log.info("   ↳ OrbitState gravado (LSN %s, parent=%s)", lsn, satelite_ulid)
    return True


# ── Orquestração ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="AEB-STREAM — ingestão orbital → HeraclitusDB")
    p.add_argument("--server", default=AEB_SERVER, help="endereço gRPC do HeraclitusDB (AEB)")
    p.add_argument("--catnr", type=int, nargs="*", help="CATNR(s) a ingerir")
    p.add_argument("--grupo", action="store_true", help="ingerir o catálogo de satélites BR")
    p.add_argument("--interval", type=int, default=0, help="segundos entre ciclos (0=uma vez)")
    p.add_argument("--once", action="store_true", help="um único ciclo")
    p.add_argument("--dry-run", action="store_true", help="busca/parse sem gravar")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    catnrs = args.catnr or (list(SATELITES_BR) if args.grupo else [47699])

    client = None
    if not args.dry_run:
        import heraclitusdb
        try:
            client = heraclitusdb.connect(args.server)
            log.info("Ligado ao HeraclitusDB em %s", args.server)
        except Exception as e:
            log.error("Falha ao ligar ao HeraclitusDB (%s): %s", args.server, e)
            sys.exit(1)

    cycle = 0
    while True:
        cycle += 1
        ok = sum(ingerir_satelite(client, c, args.dry_run) for c in catnrs)
        log.info("Ciclo %d: %d/%d satélites ingeridos", cycle, ok, len(catnrs))
        if args.interval <= 0 or args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
