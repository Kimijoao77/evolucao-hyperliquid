"""O DNA de um robô de moedas novas: vende (short) moeda recém-listada na Hyperliquid, esperando a queda que costuma
vir nas semanas depois da estreia (quem ganhou de airdrop vende; o preço de estreia costuma vir inflado).

Bloco     Gene           O que decide
entrada   espera_h       quantas horas depois da estreia vende
entrada   teto_estreia   só vende se o preço ainda estiver abaixo de X vezes o preço de estreia (0 = vende sempre)
saida     parada         sobe isso desde a venda: sai (a mercado)
saida     alvo           cai isso desde a venda: sai com lucro (0 = sem alvo)
saida     prazo_dias     sai depois de tantos dias, de qualquer jeito
risco     parte          a margem de cada moeda, em fração do patrimônio
risco     alav           alavancagem
risco     max_abertas    quantas moedas vendidas ao mesmo tempo
"""
from __future__ import annotations

from ..genoma import Genoma

GENES: dict[str, dict] = {
    "espera_h": {"bloco": "entrada", "tipo": "int", "faixa": (1, 336), "log": True},
    "teto_estreia": {"bloco": "entrada", "tipo": "real", "faixa": (0.6, 3.0), "log": True, "desliga": True},
    "parada": {"bloco": "saida", "tipo": "real", "faixa": (0.08, 0.8), "log": True},
    "alvo": {"bloco": "saida", "tipo": "real", "faixa": (0.08, 0.8), "log": True, "desliga": True},
    "prazo_dias": {"bloco": "saida", "tipo": "int", "faixa": (1, 30), "log": True},
    "parte": {"bloco": "risco", "tipo": "real", "faixa": (0.03, 0.25), "log": True},
    "alav": {"bloco": "risco", "tipo": "real", "faixa": (1.0, 3.0)},
    "max_abertas": {"bloco": "risco", "tipo": "int", "faixa": (2, 15)},
}
BLOCOS = ("entrada", "saida", "risco")

ESPECIES: dict[str, dict] = {
    "rapida": {"nome": "Rápida", "letra": "R", "descricao": "vende logo depois da estreia e sai em poucos dias",
               "faixas": {"espera_h": (1, 48), "prazo_dias": (1, 7)}},
    "paciente": {"nome": "Paciente", "letra": "P", "descricao": "espera a moeda assentar e fica semanas",
                 "faixas": {"espera_h": (72, 336), "prazo_dias": (10, 30)}},
    "apertada": {"nome": "Apertada", "letra": "J", "descricao": "parada curta e alvo de lucro",
                 "faixas": {"parada": (0.08, 0.25), "alvo": (0.08, 0.4)}},
    "espacosa": {"nome": "Espaçosa", "letra": "E", "descricao": "parada larga e pouca margem em cada moeda",
                 "faixas": {"parada": (0.35, 0.8), "parte": (0.03, 0.08)}},
}


class DNAListagem(Genoma):
    GENES, BLOCOS, ESPECIES = GENES, BLOCOS, ESPECIES

    @classmethod
    def teto(cls, gene: str, b: float, limites: dict | None) -> float:
        if gene == "alav" and limites:
            return min(b, limites["exposicao_max"])
        return b


def _pct(x: float) -> str:
    return f"{x * 100:.3g} %".replace(".", ",")


def nome(g: dict) -> str:
    esp = f"{g['espera_h']} h" if g["espera_h"] < 48 else f"{round(g['espera_h'] / 24, 1):g} dias".replace(".", ",")
    teto = f" se estiver abaixo de {g['teto_estreia']:.2g}× a estreia".replace(".", ",") if g.get("teto_estreia") else ""
    alvo = f", alvo −{_pct(g['alvo'])}" if g.get("alvo") else ""
    alav = "" if g["alav"] <= 1.05 else f", {str(round(g['alav'], 1)).replace('.', ',')}×"
    return (f"vende {esp} depois da estreia{teto}; parada +{_pct(g['parada'])}{alvo}, até {g['prazo_dias']} dias; "
            f"{_pct(g['parte'])} por moeda{alav}, até {g['max_abertas']} moedas")
