"""O DNA de um robô de preço: em que moeda opera, qual sinal segue e quanto risco aceita.

Cada espécie é um jeito de operar (tendência, reversão, grade, DCA) e usa só os genes do seu sinal. Os outros genes
ficam no DNA sem efeito: servem quando a mãe de um filho vem de outra espécie (o filho herda a moeda ou o risco dela).

Bloco     Gene        O que decide                                                       Espécie
mercado   moeda       em qual moeda opera                                                todas
sinal     modo        tendência por cruzamento de médias ou por rompimento de canal      tendência
sinal     rapida      a média rápida, em horas                                           tendência (médias)
sinal     lenta_x     a média lenta, em múltiplos da rápida                              tendência (médias)
sinal     canal       o canal do rompimento, em horas                                    tendência (rompimento)
sinal     gatilho     o tamanho da queda (ou alta) em 24 h que faz entrar                reversão
sinal     alvo_rev    o repique que faz sair com lucro                                   reversão
sinal     lados       só compra na queda, ou também vende na alta                        reversão
sinal     faixa       a faixa da grade, para cima e para baixo do preço do começo        grade
sinal     niveis      quantos degraus a grade tem                                        grade
sinal     passo       a queda entre uma compra e a próxima                               DCA
sinal     alvo_dca    o lucro sobre o preço médio que faz vender tudo                    DCA
sinal     pausa_h     a média (em horas) abaixo da qual não abre ciclo novo (0 = sem pausa) DCA
risco     alav        alavancagem                                                        todas
risco     freio       queda desde o pico que faz fechar tudo e descansar 3 dias (0 = sem) todas

O limite duro (abate com 30 % de queda desde o pico) e os custos ficam fora do DNA, no config.json.
"""
from __future__ import annotations

from ..genoma import Genoma

MOEDAS = ("BTC", "ETH", "SOL", "HYPE", "XRP", "AVAX", "kPEPE", "NEAR")

GENES: dict[str, dict] = {
    "moeda": {"bloco": "mercado", "tipo": "opcao", "opcoes": MOEDAS},
    "modo": {"bloco": "sinal", "tipo": "opcao", "opcoes": ("medias", "rompe")},
    "rapida": {"bloco": "sinal", "tipo": "int", "faixa": (6, 96), "log": True},
    "lenta_x": {"bloco": "sinal", "tipo": "real", "faixa": (2.0, 8.0)},
    "canal": {"bloco": "sinal", "tipo": "int", "faixa": (24, 360), "log": True},
    "gatilho": {"bloco": "sinal", "tipo": "real", "faixa": (0.03, 0.15), "log": True},
    "alvo_rev": {"bloco": "sinal", "tipo": "real", "faixa": (0.01, 0.06), "log": True},
    "lados": {"bloco": "sinal", "tipo": "opcao", "opcoes": ("compra", "ambos")},
    "faixa": {"bloco": "sinal", "tipo": "real", "faixa": (0.04, 0.30), "log": True},
    "niveis": {"bloco": "sinal", "tipo": "int", "faixa": (5, 30)},
    "passo": {"bloco": "sinal", "tipo": "real", "faixa": (0.01, 0.06), "log": True},
    "alvo_dca": {"bloco": "sinal", "tipo": "real", "faixa": (0.01, 0.05), "log": True},
    "pausa_h": {"bloco": "sinal", "tipo": "int", "faixa": (24, 336), "log": True, "desliga": True},
    "alav": {"bloco": "risco", "tipo": "real", "faixa": (1.0, 3.0)},
    "freio": {"bloco": "risco", "tipo": "real", "faixa": (0.08, 0.25), "desliga": True},
}
BLOCOS = ("mercado", "sinal", "risco")
COMUNS = ("moeda", "alav", "freio")

ESPECIES: dict[str, dict] = {
    "tendencia": {"nome": "Tendência", "letra": "T", "descricao": "comprado na alta, vendido na queda",
                  "genes": COMUNS + ("modo", "rapida", "lenta_x", "canal")},
    "reversao": {"nome": "Reversão", "letra": "V", "descricao": "compra depois da queda forte e sai no repique",
                 "genes": COMUNS + ("gatilho", "alvo_rev", "lados")},
    "grade": {"nome": "Grade", "letra": "G", "descricao": "compra embaixo e vende em cima, dentro de uma faixa",
              "genes": COMUNS + ("faixa", "niveis")},
    "dca": {"nome": "DCA", "letra": "A", "descricao": "compra mais a cada queda e vende tudo no alvo",
            "genes": COMUNS + ("passo", "alvo_dca", "pausa_h")},
}


class DNAPreco(Genoma):
    GENES, BLOCOS, ESPECIES = GENES, BLOCOS, ESPECIES

    @classmethod
    def teto(cls, gene: str, b: float, limites: dict | None) -> float:
        if gene == "alav" and limites:                    # o limite duro vale mais que qualquer faixa
            return min(b, limites["exposicao_max"])
        return b


def regra(especie: str, g: dict) -> dict:
    """O DNA traduzido para os parâmetros do simulador (sim.py)."""
    if especie == "tendencia":
        if g["modo"] == "medias":
            return {"tipo": "tendencia", "modo": "medias", "a": g["rapida"], "b": max(g["rapida"] + 1, round(g["rapida"] * g["lenta_x"])), "alav": g["alav"]}
        return {"tipo": "tendencia", "modo": "rompe", "a": g["canal"], "alav": g["alav"]}
    if especie == "reversao":
        return {"tipo": "reversao", "gatilho": g["gatilho"], "alvo": g["alvo_rev"], "lados": g["lados"], "alav": g["alav"]}
    if especie == "grade":
        return {"tipo": "grade", "faixa": g["faixa"], "niveis": g["niveis"], "alav": g["alav"]}
    return {"tipo": "dca", "passo": g["passo"], "alvo": g["alvo_dca"], "media_h": g["pausa_h"], "alav": g["alav"]}


def _pct(x: float) -> str:
    return f"{x * 100:.3g} %".replace(".", ",")


def nome(especie: str, g: dict) -> str:
    """O robô numa linha, do jeito que o app mostra."""
    r = regra(especie, g)
    alav = "" if r["alav"] <= 1.05 else f", {str(round(r['alav'], 1)).replace('.', ',')}×"
    if r["tipo"] == "tendencia":
        base = f"médias de {r['a']} h e {r['b']} h" if r["modo"] == "medias" else f"rompimento de {r['a']} h"
    elif r["tipo"] == "reversao":
        lado = "compra na queda" if r["lados"] == "compra" else "compra na queda e vende na alta"
        base = f"{lado} de {_pct(r['gatilho'])} em 24 h, alvo {_pct(r['alvo'])}"
    elif r["tipo"] == "grade":
        base = f"±{_pct(r['faixa'])}, {r['niveis']} degraus"
    else:
        base = f"compra a cada −{_pct(r['passo'])}, alvo +{_pct(r['alvo'])}" + (f", pausa abaixo da média de {r['media_h']} h" if r["media_h"] else "")
    freio = f", freio em {_pct(g['freio'])}" if g.get("freio") else ""
    return f"{g['moeda']}: {base}{alav}{freio}"
