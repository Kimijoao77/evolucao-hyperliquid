"""O DNA de um robô de pools concentradas (DLMM da Meteora, na Solana): em quais pools pôr dinheiro, numa faixa de
preço de que largura, por quanto tempo.

Numa pool concentrada o dinheiro só trabalha (recebe a taxa de quem troca) enquanto o preço está dentro da faixa
escolhida. Faixa estreita: mais taxa por dólar, mas o preço sai dela mais depressa e a posição vira a moeda que caiu.

Bloco      Gene             O que decide
pool       criterio         como ordena as pools: taxa sobre o dinheiro nas últimas 24 h, na última hora, ou volume
pool       balanco_max      só pools com o preço calmo: desvio das variações de 1 h nas últimas 24 h (0 = sem filtro)
pool       tvl_min          dinheiro mínimo na pool (US$)
posicao    posicao          faixa logo abaixo do preço (entra só com SOL/USDC) ou centrada no preço (troca metade)
posicao    r                a largura da faixa (abaixo: até −2r; centrada: ±r)
posicao    n_pools          em quantas pools divide o dinheiro
saida      prazo_h          sai depois de tantas horas
saida      espera_acima_h   preço acima da faixa: espera tantas horas antes de sair e reabrir no preço novo
"""
from __future__ import annotations

from ..genoma import Genoma

GENES: dict[str, dict] = {
    "criterio": {"bloco": "pool", "tipo": "opcao", "opcoes": ("taxa_24h", "taxa_1h", "volume")},
    "balanco_max": {"bloco": "pool", "tipo": "real", "faixa": (0.005, 0.06), "log": True, "desliga": True},
    "tvl_min": {"bloco": "pool", "tipo": "real", "faixa": (10_000.0, 2_000_000.0), "log": True},
    "posicao": {"bloco": "posicao", "tipo": "opcao", "opcoes": ("abaixo", "centrada")},
    "r": {"bloco": "posicao", "tipo": "real", "faixa": (0.01, 0.35), "log": True},
    "n_pools": {"bloco": "posicao", "tipo": "int", "faixa": (1, 5)},
    "prazo_h": {"bloco": "saida", "tipo": "int", "faixa": (4, 96), "log": True},
    "espera_acima_h": {"bloco": "saida", "tipo": "int", "faixa": (1, 12), "log": True},
}
BLOCOS = ("pool", "posicao", "saida")

ESPECIES: dict[str, dict] = {
    "estreita": {"nome": "Estreita", "letra": "N", "descricao": "faixa curta: muita taxa enquanto o preço fica dentro",
                 "faixas": {"r": (0.01, 0.05)}},
    "larga": {"nome": "Larga", "letra": "L", "descricao": "faixa larga: menos taxa, aguenta mais o preço andar",
              "faixas": {"r": (0.12, 0.35)}},
    "calma": {"nome": "Calma", "letra": "C", "descricao": "só pools com o preço quieto",
              "faixas": {"balanco_max": (0.005, 0.015)}},
    "rapida": {"nome": "Rápida", "letra": "Q", "descricao": "posições curtas, troca de pool toda hora",
               "faixas": {"prazo_h": (4, 12), "espera_acima_h": (1, 3)}},
}


class DNAPool(Genoma):
    GENES, BLOCOS, ESPECIES = GENES, BLOCOS, ESPECIES


CRITERIOS = {"taxa_24h": "maior taxa em 24 h", "taxa_1h": "maior taxa na última hora", "volume": "mais volume"}


def _pct(x: float) -> str:
    return f"{x * 100:.3g} %".replace(".", ",")


def nome(g: dict) -> str:
    faixa = f"faixa até −{_pct(2 * g['r'])}" if g["posicao"] == "abaixo" else f"faixa ±{_pct(g['r'])}"
    calma = f", balanço até {_pct(g['balanco_max'])}/h" if g.get("balanco_max") else ""
    return (f"{g['n_pools']} {'pool' if g['n_pools'] == 1 else 'pools'} por {CRITERIOS[g['criterio']]}{calma}; {faixa}; "
            f"até {g['prazo_h']} h")
