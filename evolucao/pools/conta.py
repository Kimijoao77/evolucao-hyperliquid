"""A matemática de uma posição de liquidez concentrada (vinda do laboratório de pools do radar-hyperliquid,
lab/concentradas.py): quanto vale a posição em cada preço, quanto dela virou moeda e que fatia da taxa ela leva."""
from __future__ import annotations

import math

def eficiencia(r: float) -> float:
    """Quanto uma faixa ±r concentra o dinheiro em relação à faixa inteira (Uniswap v3)."""
    return 1 / (1 - ((1 - r) / (1 + r)) ** 0.25)


DEGRAUS_LADO = 34      # posição padrão da Meteora: 69 degraus, 34 de cada lado do preço


def faixa_tipica(bin_step: float | None) -> float:
    """Meia-largura da posição típica numa pool DLMM: 34 degraus de bin_step (em pontos-base) para cada lado.
    Sem o bin step, ±5 %."""
    b = num(bin_step)
    if b <= 0:
        return 0.05
    return min(0.6, (1 + b / 10000) ** DEGRAUS_LADO - 1)


def fator(r: float, bin_step: float, tvl: float, dolares: float) -> float:
    """Quantas vezes a taxa média da pool (sobre o dinheiro dela) a posição recebe com o preço dentro da faixa: a
    concentração da nossa faixa contra a das outras posições, dividindo a taxa com o nosso próprio dinheiro."""
    e_nossa = eficiencia(r)
    e_pool = eficiencia(faixa_tipica(bin_step))
    tvl = max(1.0, num(tvl))
    return e_nossa / e_pool / (1 + dolares * e_nossa / (tvl * e_pool))


def num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def balanco(closes: list[float]) -> float | None:
    """Desvio das variações de 1 h (log) nas últimas 24 velas; None se a pool tem menos de 24 h de velas."""
    cs = [c for c in closes if c > 0][-25:]
    if len(cs) < 25:
        return None
    rets = [math.log(cs[i] / cs[i - 1]) for i in range(1, len(cs))]
    m = sum(rets) / len(rets)
    return math.sqrt(sum((r - m) ** 2 for r in rets) / len(rets))


def parte_moeda(L: float, p: float, a: float, b: float) -> float:
    """Fração do valor da posição que está na moeda (o resto está em SOL/USDC)."""
    v = valor_y(L, p, a, b)
    if v <= 0 or p >= b:
        return 0.0
    if p <= a:
        return 1.0
    sp, sb = math.sqrt(p), math.sqrt(b)
    return L * (1 / sp - 1 / sb) * p / v


def liquidez(valor_y: float, p0: float, a: float, b: float) -> float:
    """L de uma posição com valor_y (em unidades da moeda de cotação) no preço p0, faixa [a, b]."""
    sp, sa, sb = math.sqrt(min(p0, b)), math.sqrt(a), math.sqrt(b)
    por_l = (1 / sp - 1 / sb) * p0 + (sp - sa)          # valor (em y) de L = 1 (no topo da faixa: tudo em y)
    return valor_y / por_l


def valor_y(L: float, p: float, a: float, b: float) -> float:
    """Valor da posição em unidades de y no preço p."""
    sa, sb = math.sqrt(a), math.sqrt(b)
    if p <= a:
        return L * (1 / sa - 1 / sb) * p
    if p >= b:
        return L * (sb - sa)
    sp = math.sqrt(p)
    return L * (1 / sp - 1 / sb) * p + L * (sp - sa)


