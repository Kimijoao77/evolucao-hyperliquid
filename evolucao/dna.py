"""O DNA de um robô de copy trading: 14 genes em 4 blocos.

Cada gene tem uma faixa. Os limites de risco de verdade (exposição máxima, queda que mata) NÃO são genes: ficam no
config.json e nenhum robô consegue mexer neles. O DNA só escolhe dentro do que é permitido.

Bloco      Gene              O que decide
filtro     janela_dias       quantos dias do passado do trader o robô olha
filtro     min_operacoes     mínimo de operações fechadas na janela
filtro     min_fator_lucro   ganhos ÷ perdas mínimo na janela
filtro     duracao_min       tempo mediano mínimo que o trader segura a posição (minutos)
filtro     max_carteiras     quantos traders copia ao mesmo tempo
filtro     criterio          como ordena os aprovados (fator de lucro, retorno ou constância)
alocacao   alvo              exposição típica buscada em cada trader (1 = o saldo, sem alavancagem)
alocacao   revisao_dias      de quantos em quantos dias revê quem copia
risco      parada            queda desde o pico que faz largar um trader
risco      freio             queda do robô inteiro que faz parar tudo e descansar
risco      corte             perda numa posição que faz sair antes do trader (0 = desligado)
risco      ganho             lucro numa posição que faz sair antes do trader (0 = desligado)
risco      tempo_max_h       tempo máximo numa posição (0 = desligado)
execucao   desvio_max        quanto o preço pode ter fugido desde a ordem do trader para ainda entrar

Espécie: um jeito de ser. Cada espécie aperta a faixa de alguns genes e tem vagas garantidas na população, para um
vencedor recente não tomar conta de tudo.
"""
from __future__ import annotations

from .genoma import CHANCE_DESLIGADO, Genoma  # noqa: F401  (CHANCE_DESLIGADO: os testes antigos importam daqui)

GENES: dict[str, dict] = {
    "janela_dias": {"bloco": "filtro", "tipo": "int", "faixa": (7, 60)},
    "min_operacoes": {"bloco": "filtro", "tipo": "int", "faixa": (5, 60)},
    "min_fator_lucro": {"bloco": "filtro", "tipo": "real", "faixa": (1.0, 3.0)},
    "duracao_min": {"bloco": "filtro", "tipo": "real", "faixa": (5.0, 240.0), "log": True},
    "max_carteiras": {"bloco": "filtro", "tipo": "int", "faixa": (1, 10)},
    "criterio": {"bloco": "filtro", "tipo": "opcao", "opcoes": ("fator_lucro", "retorno", "constancia")},
    "alvo": {"bloco": "alocacao", "tipo": "real", "faixa": (0.3, 3.0), "log": True},
    "revisao_dias": {"bloco": "alocacao", "tipo": "int", "faixa": (1, 7)},
    "parada": {"bloco": "risco", "tipo": "real", "faixa": (0.05, 0.25)},
    "freio": {"bloco": "risco", "tipo": "real", "faixa": (0.08, 0.25)},
    "corte": {"bloco": "risco", "tipo": "real", "faixa": (0.02, 0.30), "log": True, "desliga": True},
    "ganho": {"bloco": "risco", "tipo": "real", "faixa": (0.03, 1.0), "log": True, "desliga": True},
    "tempo_max_h": {"bloco": "risco", "tipo": "real", "faixa": (6.0, 240.0), "log": True, "desliga": True},
    "desvio_max": {"bloco": "execucao", "tipo": "real", "faixa": (0.001, 0.03), "log": True},
}
BLOCOS = ("filtro", "alocacao", "risco", "execucao")

ESPECIES: dict[str, dict] = {
    "cautelosa": {"nome": "Cautelosa", "letra": "C", "descricao": "pouca exposição e paradas apertadas",
                  "faixas": {"alvo": (0.3, 1.0), "parada": (0.05, 0.12), "freio": (0.08, 0.12)}},
    "diversificada": {"nome": "Diversificada", "letra": "D", "descricao": "copia muitos traders ao mesmo tempo",
                      "faixas": {"max_carteiras": (6, 10), "alvo": (0.5, 2.0)}},
    "curta": {"nome": "Curta", "letra": "R", "descricao": "traders de operações rápidas, olhando o passado recente",
              "faixas": {"duracao_min": (5.0, 45.0), "janela_dias": (7, 21), "revisao_dias": (1, 2)}},
    "exigente": {"nome": "Exigente", "letra": "E", "descricao": "poucos traders, com filtro duro",
                 "faixas": {"max_carteiras": (1, 3), "min_fator_lucro": (1.8, 3.0), "min_operacoes": (25, 60)}},
}


class BotDNA(Genoma):
    """O DNA de um robô de copy trading (as regras de sortear, cruzar e mutar ficam em genoma.py)."""
    GENES, BLOCOS, ESPECIES = GENES, BLOCOS, ESPECIES

    @classmethod
    def teto(cls, gene: str, b: float, limites: dict | None) -> float:
        if gene == "alvo" and limites:                    # o limite duro vale mais que qualquer faixa
            return min(b, limites["exposicao_max"])
        return b


def faixa(gene: str, especie: str, limites: dict | None = None) -> tuple:
    return BotDNA.faixa(gene, especie, limites)
