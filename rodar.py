"""A rodada de 2 em 2 horas (GitHub Actions): coleta os traders, avança a população e grava o resumo que o app lê.
Nada aqui compra ou vende: só consulta a API pública da Hyperliquid e faz contas com dinheiro de mentira."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from evolucao import dados as D  # noqa: E402
from evolucao.api import Hyperliquid  # noqa: E402
from evolucao.coletor import coletar  # noqa: E402
from evolucao.motor import EvolutionEngine  # noqa: E402


def main() -> int:
    cfg = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    api = Hyperliquid(cfg.get("peso_por_minuto", 1000))
    agora = D.agora_ms()

    def ler_radar(arquivo: str = "relatorio.json") -> dict:
        r = requests.get(cfg["radar"] + arquivo, timeout=60)
        r.raise_for_status()
        return r.json()

    c = coletar(cfg, api, agora, ler_radar=ler_radar)
    print("\n".join(c["log"]))
    motor = EvolutionEngine(cfg, api=api, agora=agora, ler_radar=ler_radar)
    motor.rodar()
    print("\n".join(motor.log))
    print(f"peso gasto na Hyperliquid: {api.lim.total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
