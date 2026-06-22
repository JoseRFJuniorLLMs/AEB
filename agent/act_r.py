# AEB-STREAM — agent/act_r.py
# Ativação sub-simbólica ACT-R: dá *boost* a entidades (satélites/sensores/anomalias)
# que são RECORRENTES e RECENTES. Usado pelo daemon para priorizar quais anomalias
# merecem alerta imediato vs. ruído transitório.
#
# Activation base-level (Anderson):  B_i = ln( Σ_j  t_j^(-d) )
#   t_j = tempo (s) desde a j-ésima referência da entidade;  d = decaimento (0.5).
# Entidades referenciadas muitas vezes e há pouco tempo têm ativação alta.

from __future__ import annotations

import math
import time


class ActR:
    DECAY = 0.5          # parâmetro d do ACT-R
    THRESHOLD = 0.0      # ativação acima da qual a entidade é "saliente"

    def __init__(self) -> None:
        self._refs: dict[str, list[float]] = {}

    def reference(self, entity: str, when: float | None = None) -> None:
        """Regista uma referência (ex.: uma anomalia observada nesta entidade)."""
        self._refs.setdefault(entity, []).append(when if when is not None else time.time())

    def activation(self, entity: str, now: float | None = None) -> float:
        now = now if now is not None else time.time()
        refs = self._refs.get(entity)
        if not refs:
            return float("-inf")
        s = sum(max(now - t, 1e-3) ** (-self.DECAY) for t in refs)
        return math.log(s) if s > 0 else float("-inf")

    def salient(self, entity: str, now: float | None = None) -> bool:
        return self.activation(entity, now) >= self.THRESHOLD

    def ranked(self, now: float | None = None) -> list[tuple[str, float]]:
        now = now if now is not None else time.time()
        return sorted(
            ((e, self.activation(e, now)) for e in self._refs),
            key=lambda x: -x[1],
        )
