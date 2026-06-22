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

# Injeção de anomalias: índice da leitura -> telemetria forçada
ANOMALIAS = {
    4: {"battery_temp": 57.3, "solar_voltage": 47.9, "current_a": 3.1, "eclipse": False},   # térmica
    8: {"battery_temp": 24.1, "solar_voltage": 11.4, "current_a": 0.2, "eclipse": False},    # perda de energia
}


def semear(server: str, catnr: int = 47699):
    tle = pipeline.fetch_tle(catnr)
    if not tle:
        log.error("Sem TLE (nem online nem cache) para %s — abortado", catnr)
        return
    name, l1, l2 = tle
    el = orbit.parse_tle(l1, l2, name or pipeline.SATELITES_BR.get(catnr, ""))
    client = heraclitusdb.connect(server)
    sat_ulid = pipeline.ensure_satelite(client, el)
    log.info("Satelite %s (ULID %s)", el.name, sat_ulid)

    agora = datetime.now(timezone.utc)
    n_anom = 0
    for i in range(PASSOS):
        t = agora - timedelta(minutes=(PASSOS - 1 - i) * INTERVALO_MIN)
        sub = orbit.propagate(l1, l2, t)
        tele = ANOMALIAS.get(i) or pipeline.simular_telemetria(el, sub)
        lsn = pipeline.append_orbit_state(client, el, sub, tele, sat_ulid)
        flag = "  ⚠ ANOMALIA INJETADA" if i in ANOMALIAS else ""
        if i in ANOMALIAS:
            n_anom += 1
        log.info("  [%2d] %s lat=%7.3f alt=%6.1fkm bat=%.1f°C V=%.1f (LSN %s)%s",
                 i, t.strftime("%H:%M"), sub.lat_deg, sub.alt_km,
                 tele["battery_temp"], tele["solar_voltage"], lsn, flag)
    log.info("Semeadas %d leituras (%d com anomalia injetada) para %s",
             PASSOS, n_anom, el.name)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    semear(pipeline.AEB_SERVER)
