#!/usr/bin/env python3
# AEB-STREAM — stream.py  (simulação ao vivo)
#
# Propaga continuamente as órbitas (SGP4) e faz append de OrbitState no
# HeraclitusDB, com TEMPO ACELERADO — assim os satélites orbitam à vista no
# dashboard e os contactos (hits) com as antenas acendem/apagam ao passarem
# sobre o Brasil. O Cérebro (main.py --daemon) corre em paralelo e deteta anomalias.
#
#   python stream.py                       # 60x, ciclo de 3s (todos os BR)
#   python stream.py --accel 120 --interval 2
#   python stream.py --catnr 47699 25504   # só alguns
#
# A telemetria é simulada; substituir por feed real da estação terrena.

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"D:\DEV\AEB")
sys.path.insert(0, r"D:\DEV\HeraclitusDB\sdk\python")

import heraclitusdb  # noqa: E402

import pipeline  # noqa: E402
from agent import orbit  # noqa: E402

log = logging.getLogger("aeb.stream")


def main():
    p = argparse.ArgumentParser(description="AEB-STREAM — simulação orbital ao vivo")
    p.add_argument("--server", default=pipeline.AEB_SERVER)
    p.add_argument("--catnr", type=int, nargs="*")
    p.add_argument("--accel", type=float, default=60.0, help="fator de aceleração do tempo")
    p.add_argument("--interval", type=float, default=3.0, help="segundos reais por ciclo")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    catnrs = args.catnr or list(pipeline.SATELITES_BR)
    client = heraclitusdb.connect(args.server)
    log.info("Streaming → %s | %dx tempo real | ciclo %.1fs | %d satélites",
             args.server, args.accel, args.interval, len(catnrs))

    # carrega TLEs (cache) e garante os nós Satelite uma vez
    tles, ulids, els = {}, {}, {}
    for c in catnrs:
        tle = pipeline.fetch_tle(c)
        if not tle:
            log.warning("Sem TLE para %s — fora do stream", c)
            continue
        name, l1, l2 = tle
        els[c] = orbit.parse_tle(l1, l2, name or pipeline.SATELITES_BR.get(c, ""))
        tles[c] = (l1, l2)
        ulids[c] = pipeline.ensure_satelite(client, els[c])

    sim = datetime.now(timezone.utc)
    ciclo = 0
    while True:
        ciclo += 1
        sim += timedelta(seconds=args.accel * args.interval)
        n = 0
        for c, (l1, l2) in tles.items():
            try:
                sub = orbit.propagate(l1, l2, sim)
                tele = pipeline.simular_telemetria(els[c], sub)
                pipeline.append_orbit_state(client, els[c], sub, tele, ulids[c])
                n += 1
            except RuntimeError as e:
                log.warning("%s: propagação falhou — %s", c, e)
        log.info("ciclo %d @ sim %s — %d satélites atualizados",
                 ciclo, sim.strftime("%H:%M:%S"), n)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
