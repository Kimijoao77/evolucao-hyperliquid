"""Peças para montar um mercadinho de mentira nos testes."""
from __future__ import annotations

import json
from pathlib import Path

from evolucao import DIA, HORA, MINUTO
from evolucao.mercado import Precos

CFG = json.loads((Path(__file__).resolve().parent.parent / "config.json").read_text(encoding="utf-8"))
T0 = 1_800_000_000_000 // DIA * DIA          # um dia qualquer, à meia-noite UTC


def fill(t, moeda, lado, preco, qtd, antes, pnl=0.0, taxa=0.0, n=[0]):
    n[0] += 1
    return {"t": t, "c": moeda, "s": lado, "p": preco, "z": qtd, "sp": antes, "pnl": pnl, "f": taxa, "id": n[0]}


def ida_e_volta(t, moeda, entra, sai, qtd, dur=HORA, lado="B"):
    """Uma operação completa do trader: abre e fecha. Devolve os 2 fills."""
    s = 1 if lado == "B" else -1
    return [fill(t, moeda, lado, entra, qtd, 0.0),
            fill(t + dur, moeda, "A" if lado == "B" else "B", sai, qtd, s * qtd, pnl=s * (sai - entra) * qtd)]


def historico(t_fim, moeda="BTC", n=40, ganho=2.0, perda=1.0, cada=6 * HORA, preco=100.0, dur=HORA):
    """`n` operações fechadas antes de t_fim: duas que ganham `ganho` para cada uma que perde `perda` (por unidade)."""
    fs = []
    for i in range(n):
        t = t_fim - (n - i) * cada
        fs += ida_e_volta(t, moeda, preco, preco + (ganho if i % 3 else -perda), 1.0, dur)
    return fs


def fotos_de(w, t_ini, t_fim, valor=10_000.0, ntl=10_000.0, cada=2 * HORA, abertas=()):
    """Fotos da conta do trader. `abertas`: moedas que aparecem com posição (senão a cópia entende que ele zerou)."""
    pos = [[m, 1.0, 1.0] for m in abertas]
    return [{"t": t, "a": w, "v": valor, "ntl": ntl, "pos": pos} for t in range(t_ini, t_fim + 1, cada)]


class PrecoFixo(Precos):
    """Preço por função do tempo: {moeda: f(t)} (ou um número)."""

    def __init__(self, tabela):
        super().__init__()
        self.tabela, self.falhas = tabela, {}

    def em(self, moeda, t):
        f = self.tabela.get(moeda)
        return f(t) if callable(f) else f

    ultimo = em


def degraus(pontos):
    """[(t, preço), ...] → função que devolve o preço do último degrau até t."""
    def f(t):
        p = pontos[0][1]
        for tt, pp in pontos:
            if t >= tt:
                p = pp
        return p
    return f
