#!/usr/bin/env python3
# AEB-STREAM — main.py  (O Cérebro)
#
# Lê o log do HeraclitusDB, reconstrói o grafo temporal dos satélites, corre os
# detectores de anomalia e grava eventos `Anomalia` (com proveniência → OrbitState,
# tornando-os rastreáveis por PROVENANCE/WHY). Prioriza por ativação ACT-R.
#
# Uso:
#   python main.py --once                 # uma passagem sobre todo o log
#   python main.py --daemon --interval 30 # vigília contínua
#   python main.py --reset                # reprocessa do início (ignora checkpoint)

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, r"D:\DEV\AEB")
sys.path.insert(0, r"D:\DEV\HeraclitusDB\sdk\python")

from agent.act_r import ActR            # noqa: E402
from agent.anomalias import detectar    # noqa: E402
from agent.graph import SatGraph        # noqa: E402

log = logging.getLogger("aeb.cerebro")

AEB_SERVER = os.environ.get("AEB_SERVER", "127.0.0.1:7476")
CKPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "cerebro.ckpt")
SEVERIDADE_ICON = {"CRITICA": "🔴", "ALTA": "🟠", "MEDIA": "🟡"}


def carregar_ckpt() -> int:
    try:
        with open(CKPT) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def gravar_ckpt(lsn: int) -> None:
    os.makedirs(os.path.dirname(CKPT), exist_ok=True)
    with open(CKPT, "w") as f:
        f.write(str(lsn))


def ler_eventos(client, desde_lsn: int, ate: int) -> list[dict]:
    """Lê eventos do log na janela (desde_lsn, ate]. AEB é pequena → 1 query."""
    gql = f"MATCH (n) WHERE n.lsn > {desde_lsn} AND n.lsn <= {ate} RETURN n"
    r = client.query(gql)
    rows = r if isinstance(r, list) else []
    return sorted(rows, key=lambda n: int(n.get("lsn", 0)))


def emitir_anomalia(client, est, codigo, severidade, descricao) -> int:
    """Grava o evento Anomalia, apontando para o OrbitState (proveniência)."""
    content = f"ANOMALIA {codigo} [{severidade}] {est.satellite_id}: {descricao}"
    attrs = {
        "satellite_id": est.satellite_id,
        "catnr": est.catnr,
        "codigo": codigo,
        "severidade": severidade,
        "descricao": descricao,
        "orbitstate_lsn": str(est.lsn),
        "ts": est.ts,
    }
    return client.append(
        "Anomalia", content, agent_id="aeb-cerebro",
        attrs=attrs, parents=[est.event_id] if est.event_id else None,
    )


def passagem(client, graph: SatGraph, actr: ActR, desde: int) -> tuple[int, int]:
    """Uma passagem: lê novos eventos, detecta, emite. Devolve (novo_ckpt, n_alertas)."""
    head = json.loads(client.stats()["message"])["head"]
    if head <= desde:
        return desde, 0
    eventos = ler_eventos(client, desde, head)
    n_alertas = 0
    for node in eventos:
        est = graph.ingest(node)
        if est is None:        # Satelite ou outro kind — só atualiza o grafo
            continue
        for codigo, severidade, descricao in detectar(graph, est):
            lsn = emitir_anomalia(client, est, codigo, severidade, descricao)
            actr.reference(est.catnr)
            n_alertas += 1
            log.warning("%s %s %-12s %s (Anomalia LSN %s)",
                        SEVERIDADE_ICON.get(severidade, "•"), severidade,
                        est.satellite_id, descricao, lsn)
    return head, n_alertas


def resumo(graph: SatGraph, actr: ActR, total_alertas: int) -> None:
    s = graph.stats()
    log.info("─" * 60)
    log.info("Grafo: %d satélites, %d estados orbitais | %d alertas nesta sessão",
             s["satelites"], s["estados"], total_alertas)
    ranking = [(c, a) for c, a in actr.ranked() if a > float("-inf")]
    if ranking:
        log.info("Prioridade ACT-R (satélites mais anómalos):")
        for catnr, act in ranking[:5]:
            nome = graph.satelites.get(catnr).nome if catnr in graph.satelites else catnr
            log.info("   %-12s ativação=%.3f", nome, act)


def main():
    p = argparse.ArgumentParser(description="AEB-STREAM — O Cérebro (deteção de anomalias)")
    p.add_argument("--server", default=AEB_SERVER)
    p.add_argument("--daemon", action="store_true", help="vigília contínua")
    p.add_argument("--once", action="store_true", help="uma passagem")
    p.add_argument("--interval", type=int, default=30, help="segundos entre passagens (daemon)")
    p.add_argument("--reset", action="store_true", help="reprocessar do início")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    import heraclitusdb
    client = heraclitusdb.connect(args.server)
    log.info("O Cérebro ligado ao HeraclitusDB (AEB) em %s", args.server)

    graph, actr = SatGraph(), ActR()
    desde = 0 if args.reset else carregar_ckpt()
    total = 0

    while True:
        novo, n = passagem(client, graph, actr, desde)
        total += n
        if novo > desde:
            gravar_ckpt(novo)
            desde = novo
        resumo(graph, actr, total)
        if not args.daemon:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
