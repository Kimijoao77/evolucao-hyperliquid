"""O DNA de um robô de cofres: quais cofres da Hyperliquid escolhe, quanto põe em cada um e quando sai.

Num cofre (vault) você deposita e o dono opera com o dinheiro de todos; ele fica com uma parte do lucro (a comissão do
cofre, quase sempre 10 %). O HLP é o cofre do próprio protocolo e não cobra comissão.

Bloco      Gene            O que decide
filtro     janela_dias     quantos dias do histórico do cofre o robô olha
filtro     criterio        como ordena os aprovados: retorno, constância (semanas no azul) ou eficiência (retorno ÷ queda)
filtro     max_queda       a maior queda que aceita no histórico olhado
filtro     min_idade_dias  idade mínima do cofre
filtro     min_tvl         dinheiro mínimo no cofre (US$)
alocacao   n_cofres        em quantos cofres (além do HLP) divide o dinheiro
alocacao   peso_hlp        a parte que vai sempre para o HLP (0 = nada)
alocacao   revisao_dias    de quantos em quantos dias revê a escolha
risco      parada          queda desde o pico (num cofre) que faz sair dele até a próxima revisão (0 = sem)
"""
from __future__ import annotations

from ..genoma import Genoma

GENES: dict[str, dict] = {
    "janela_dias": {"bloco": "filtro", "tipo": "int", "faixa": (30, 365), "log": True},
    "criterio": {"bloco": "filtro", "tipo": "opcao", "opcoes": ("retorno", "constancia", "eficiencia")},
    "max_queda": {"bloco": "filtro", "tipo": "real", "faixa": (0.05, 0.6), "log": True},
    "min_idade_dias": {"bloco": "filtro", "tipo": "int", "faixa": (30, 365), "log": True},
    "min_tvl": {"bloco": "filtro", "tipo": "real", "faixa": (100_000.0, 20_000_000.0), "log": True},
    "n_cofres": {"bloco": "alocacao", "tipo": "int", "faixa": (1, 8)},
    "peso_hlp": {"bloco": "alocacao", "tipo": "real", "faixa": (0.1, 1.0), "desliga": True},
    "revisao_dias": {"bloco": "alocacao", "tipo": "int", "faixa": (7, 60), "log": True},
    "parada": {"bloco": "risco", "tipo": "real", "faixa": (0.05, 0.4), "log": True, "desliga": True},
}
BLOCOS = ("filtro", "alocacao", "risco")

ESPECIES: dict[str, dict] = {
    "ancora": {"nome": "Âncora", "letra": "H", "descricao": "boa parte no HLP e poucos cofres de trader",
               "faixas": {"peso_hlp": (0.5, 1.0), "n_cofres": (1, 3)}},
    "diversificada": {"nome": "Diversificada", "letra": "D", "descricao": "muitos cofres ao mesmo tempo",
                      "faixas": {"n_cofres": (4, 8), "peso_hlp": (0.1, 0.3)}},
    "agressiva": {"nome": "Agressiva", "letra": "X", "descricao": "atrás do maior retorno, aceita queda grande",
                  "faixas": {"max_queda": (0.25, 0.6), "janela_dias": (30, 120)}, "opcoes": {"criterio": ("retorno",)}},
    "constante": {"nome": "Constante", "letra": "K", "descricao": "cofres que sobem devagar e caem pouco",
                  "faixas": {"max_queda": (0.05, 0.2), "janela_dias": (90, 365)}, "opcoes": {"criterio": ("constancia", "eficiencia")}},
}


class DNACofre(Genoma):
    GENES, BLOCOS, ESPECIES = GENES, BLOCOS, ESPECIES


def _pct(x: float) -> str:
    return f"{x * 100:.3g} %".replace(".", ",")


CRITERIOS = {"retorno": "maior retorno", "constancia": "mais semanas no azul", "eficiencia": "retorno ÷ queda"}


def nome(g: dict) -> str:
    hlp = f"{_pct(g['peso_hlp'])} no HLP + " if g.get("peso_hlp") else ""
    tvl = g["min_tvl"]
    tvl_txt = f"US$ {tvl / 1e6:.2g} mi".replace(".", ",") if tvl >= 1e6 else f"US$ {tvl / 1e3:.0f} mil"
    return (f"{hlp}{g['n_cofres']} {'cofre' if g['n_cofres'] == 1 else 'cofres'} por {CRITERIOS[g['criterio']]} em {g['janela_dias']} dias, "
            f"queda até {_pct(g['max_queda'])}, {tvl_txt} ou mais, revê a cada {g['revisao_dias']} dias")
