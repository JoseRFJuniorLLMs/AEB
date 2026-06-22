#!/usr/bin/env python3
# AEB-STREAM — seed_demo.py
#
# Popula a instância AEB com uma SÉRIE TEMPORAL realista (propagação SGP4 do TLE em
# vários instantes) + injeta algumas ANOMALIAS, para demonstrar o Cérebro e o
# dashboard sem depender de a CelesTrak estar online (usa o cache de TLE).
#
#   python seed_demo.py            # semeia ~12 leituras + 2 anomalias
#
# Não substitui o pipeline real; é só material de demonstração.

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"D:\DEV\AEB")
sys.path.insert(0, r"D:\DEV\HeraclitusDB\sdk\python")

import heraclitusdb  # noqa: E402

import pipeline  # noqa: E402
from agent import orbit  # noqa: E402

log = logging.getLogger("aeb.seed")

PASSOS = 12            # nº de leituras
INTERVALO_MIN = 10     # minutos entre leituras

# Anomalias a injetar POR satélite (catnr -> {índice_leitura -> telemetria forçada}).
# Só alguns satélites têm anomalia — o resto fica nominal (realista).
ANOMALIAS_POR_SAT = {
    47699: {  # Amazonia-1: pico térmico + perda de energia
        4: {"battery_temp": 57.3, "solar_voltage": 47.9, "current_a": 3.1, "eclipse": False},
        8: {"battery_temp": 24.1, "solar_voltage": 11.4, "current_a": 0.2, "eclipse": False},
    },
    44883: {  # CBERS-4A: perda de energia fora de eclipse
        6: {"battery_temp": 25.0, "solar_voltage": 9.8, "current_a": 0.1, "eclipse": False},
    },
    25504: {  # SCD-2: sobreaquecimento
        5: {"battery_temp": 61.5, "solar_voltage": 47.0, "current_a": 3.0, "eclipse": False},
    },
}


def semear(client, catnr: int, anomalias: dict | None = None) -> bool:
    tle = pipeline.fetch_tle(catnr)
    if not tle:
        log.warning("Sem TLE (online nem cache) para %s — saltado", catnr)
        return False
    name, l1, l2 = tle
    try:
        el = orbit.parse_tle(l1, l2, name or pipeline.SATELITES_BR.get(catnr, ""))
    except ValueError as e:
        log.warning("TLE inválido para %s — %s", catnr, e)
        return False
    anomalias = anomalias or {}
    sat_ulid = pipeline.ensure_satelite(client, el)

    agora = datetime.now(timezone.utc)
    n_anom = 0
    for i in range(PASSOS):
        t = agora - timedelta(minutes=(PASSOS - 1 - i) * INTERVALO_MIN)
        sub = orbit.propagate(l1, l2, t)
        tele = anomalias.get(i) or pipeline.simular_telemetria(el, sub)
        pipeline.append_orbit_state(client, el, sub, tele, sat_ulid)
        if i in anomalias:
            n_anom += 1
    log.info("  %-12s %2d leituras%s", el.name, PASSOS,
             f"  (+{n_anom} anomalia injetada)" if n_anom else "")
    return True


def semear_todos(server: str):
    client = heraclitusdb.connect(server)
    log.info("Semeando o catálogo BR na AEB (%s)…", server)
    ok = 0
    for catnr in pipeline.SATELITES_BR:
        if semear(client, catnr, ANOMALIAS_POR_SAT.get(catnr)):
            ok += 1
    log.info("Semeados %d/%d satélites", ok, len(pipeline.SATELITES_BR))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    semear_todos(pipeline.AEB_SERVER)
