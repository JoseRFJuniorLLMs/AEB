# AEB-STREAM — agent/anomalias.py
# Detectores de anomalia sobre o grafo de caso. Cada detector é puro:
# recebe o grafo + a nova leitura e devolve uma lista de alertas.
#
# Um alerta = (codigo, severidade, descricao). Severidades: MEDIA | ALTA | CRITICA.

from __future__ import annotations

from .graph import EstadoOrbital, SatGraph

# Janelas nominais de operação (ajustar por satélite/missão).
#
# Nota de calibração: a altitude GEODÉSICA varia naturalmente ~±15 km ao longo de
# uma órbita quase-circular (a Terra é oblata; nos polos a superfície está mais
# perto). E a temperatura oscila ~±27°C nas transições sol↔sombra. Os limiares
# abaixo são folgados o suficiente para NÃO disparar com essa variação normal —
# só com desvios genuínos (manobra, decaimento, falha térmica/elétrica).
TEMP_NOMINAL = (-20.0, 45.0)   # °C — bateria (janela absoluta de operação)
MAX_SALTO_TEMP = 40.0          # °C entre leituras (acima da oscilação de eclipse)
TENSAO_MIN_SOL = 30.0          # V — tensão mínima fora de eclipse
DESVIO_ALT_MAX = 30.0          # km — desvio de altitude vs. média (> oblateness)


def detectar(graph: SatGraph, est: EstadoOrbital) -> list[tuple[str, str, str]]:
    """Corre todos os detectores sobre a leitura `est` no contexto do grafo."""
    out: list[tuple[str, str, str]] = []
    ultimos = graph.ultimos(est.catnr, 2)
    anterior = ultimos[-2] if len(ultimos) >= 2 else None

    # 1) Térmica — fora da janela nominal absoluta
    if est.battery_temp is not None and not (
        TEMP_NOMINAL[0] <= est.battery_temp <= TEMP_NOMINAL[1]
    ):
        out.append((
            "TERMICA", "CRITICA",
            f"Temperatura de bateria {est.battery_temp:.1f}°C fora da janela "
            f"nominal {TEMP_NOMINAL[0]:.0f}..{TEMP_NOMINAL[1]:.0f}°C",
        ))

    # 2) Térmica — salto brusco entre leituras
    if anterior and anterior.battery_temp is not None and est.battery_temp is not None:
        delta = abs(est.battery_temp - anterior.battery_temp)
        if delta > MAX_SALTO_TEMP:
            out.append((
                "TERMICA_SALTO", "ALTA",
                f"Variação térmica abrupta de {delta:.1f}°C entre leituras "
                f"({anterior.battery_temp:.1f}→{est.battery_temp:.1f}°C)",
            ))

    # 3) Energia — tensão baixa fora de eclipse (perda de potência inesperada)
    if (not est.eclipse and est.solar_voltage is not None
            and est.solar_voltage < TENSAO_MIN_SOL):
        out.append((
            "ENERGIA", "CRITICA",
            f"Tensão dos painéis {est.solar_voltage:.1f}V abaixo de "
            f"{TENSAO_MIN_SOL:.0f}V FORA de eclipse — possível falha de geração",
        ))

    # 4) Órbita — desvio de altitude vs. média (manobra não prevista ou decaimento)
    media = graph.media_altitude(est.catnr)
    if media and est.alt_km and abs(est.alt_km - media) > DESVIO_ALT_MAX:
        out.append((
            "ORBITA", "MEDIA",
            f"Altitude {est.alt_km:.1f}km desvia {est.alt_km - media:+.1f}km da "
            f"média {media:.1f}km — possível manobra ou decaimento",
        ))

    return out
