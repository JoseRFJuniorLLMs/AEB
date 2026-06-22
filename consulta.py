#!/usr/bin/env python3
# AEB-STREAM — consulta.py
#
# Os três operadores forenses nativos do HeraclitusDB aplicados ao domínio AEB:
#   AS OF LSN  — estado dos sensores no instante anterior a uma falha
#   PROVENANCE — cadeia de custódia do dado (estação → processamento)
#   WHY        — cadeia causal mínima que gerou um alerta de anomalia
#
# Uso:
#   python consulta.py asof  <lsn> [--catnr 47699]
#   python consulta.py prov  <event_id>
#   python consulta.py why   <event_id>

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, r"D:\DEV\HeraclitusDB\sdk\python")


def _connect(server: str):
    import heraclitusdb
    return heraclitusdb.connect(server)


def estado_antes_de(client, lsn: int, catnr: int | None = None) -> list:
    """AS OF — telemetria do(s) satélite(s) no estado do log ANTES de `lsn`.
    Para perícia: 'como estavam os sensores no instante anterior à falha?'."""
    filtro = f' AND n.catnr = "{catnr}"' if catnr else ""
    # janela de cauda + AS OF para o estado imediatamente anterior à falha
    lo = max(0, lsn - 200_000)
    gql = (
        f'MATCH (n) WHERE n.lsn >= {lo} AND n.lsn < {lsn} '
        f'AND n.tipo = "OrbitState"{filtro} AS OF LSN {lsn} RETURN n'
    )
    r = client.query(gql)
    return r if isinstance(r, list) else []


def proveniencia(client, event_id: str) -> list:
    """PROVENANCE — cadeia de custódia: de onde veio este dado (Satelite-raiz,
    estação terrena, etc.)."""
    r = client.query(f'PROVENANCE ("{event_id}")')
    return r if isinstance(r, list) else []


def porque(client, event_id: str, k: int = 5):
    """WHY — cadeia causal mínima que sustenta um alerta de anomalia."""
    return client.query(f'WHY ("{event_id}", {k})')


def _print_orbitstates(rows: list):
    if not rows:
        print("  (sem registos)")
        return
    for n in rows:
        a = n.get("attrs", {}) or {}
        print(
            f"  [{n.get('lsn')}] {a.get('satellite_id','?'):12} "
            f"lat={a.get('latitude','?')} lon={a.get('longitude','?')} "
            f"alt={a.get('altitude_km','?')}km  bat={a.get('battery_temp','?')}°C "
            f"V={a.get('solar_voltage','?')}"
            + ("  ⚠ECLIPSE" if a.get("eclipse") == "True" else "")
        )


def main():
    p = argparse.ArgumentParser(description="AEB-STREAM — consultas forenses (HeraclitusDB)")
    p.add_argument("op", choices=["asof", "prov", "why"])
    p.add_argument("alvo", help="LSN (asof) ou event_id (prov/why)")
    p.add_argument("--catnr", type=int, help="filtrar por satélite (asof)")
    p.add_argument("--server", default=os.environ.get("AEB_SERVER", "127.0.0.1:7476"))
    args = p.parse_args()

    c = _connect(args.server)

    if args.op == "asof":
        rows = estado_antes_de(c, int(args.alvo), args.catnr)
        print(f"AS OF LSN {args.alvo} — estado dos sensores ANTES da falha:")
        _print_orbitstates(rows)
    elif args.op == "prov":
        chain = proveniencia(c, args.alvo)
        print(f"PROVENANCE ({args.alvo}) — cadeia de custódia:")
        for item in chain:
            # PROVENANCE devolve ULIDs (strings); resolve cada nó para detalhe.
            uid = item if isinstance(item, str) else item.get("id")
            row = c.query(f'MATCH (n) WHERE n.id = "{uid}" RETURN n LIMIT 1')
            n = row[0] if isinstance(row, list) and row else {}
            print(f"  {uid}  kind={n.get('kind','?')}  {(n.get('content') or '')[:70]}")
    elif args.op == "why":
        print(f"WHY ({args.alvo}) — cadeia causal do alerta:")
        print(" ", porque(c, args.alvo))


if __name__ == "__main__":
    main()
