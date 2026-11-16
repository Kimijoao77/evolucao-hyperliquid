"""A ficha de cada trader, só com o que já se sabia naquele instante.

Quando um robô revisa quem copiar (no instante t), ele enxerga as operações que o trader FECHOU até t e as fotos da
conta até t. Nada do que aconteceu depois entra na ficha. É isso que mantém o teste honesto: o robô escolhe com o
passado do trader e é julgado pelo que acontece depois.
"""
from __future__ import annotations

import bisect
from statistics import median

from . import DIA, HORA
from .mercado import parte_terceiros


def operacoes(fills: list[dict]) -> list[tuple[int, int, float]]:
    """Operações fechadas e completas (posição saiu de zero e voltou a zero ou virou de lado), a partir dos fills.
    Volta [(t1, t0, resultado líquido)] em ordem de fechamento. A que já estava aberta no começo dos dados não conta."""
    abertas: dict[str, list] = {}                         # moeda → [t0, resultado, completa]
    ops: list[tuple[int, int, float]] = []
    for f in sorted(fills, key=lambda f: (f["t"], f.get("id") or 0)):
        moeda, sp, z = f["c"], float(f.get("sp", 0.0)), float(f["z"])
        if z <= 0:
            continue
        depois = sp + (z if f["s"] == "B" else -z)
        eps = 1e-9 * max(1.0, abs(sp), abs(depois))
        s0 = 0 if abs(sp) <= eps else (1 if sp > 0 else -1)
        s1 = 0 if abs(depois) <= eps else (1 if depois > 0 else -1)
        op = abertas.get(moeda)
        if op is None and s0 != 0:                        # os dados começam no meio de uma posição
            op = abertas[moeda] = [f["t"], 0.0, False]
        if op is not None and s0 == 0:                    # fills faltando: descarta a operação que estava na memória
            abertas.pop(moeda, None)
            op = None
        liquido = float(f.get("pnl", 0.0)) - float(f.get("f", 0.0))
        if s0 == 0:
            abertas[moeda] = [f["t"], liquido, True]
        elif s1 == s0:                                    # aumentou ou reduziu sem zerar
            op[1] += liquido
        else:                                             # zerou ou virou de lado
            fecha = abs(sp) / z if s1 != 0 else 1.0       # virou: só a parte que fecha é desta operação
            op[1] += float(f.get("pnl", 0.0)) - float(f.get("f", 0.0)) * fecha
            if op[2]:
                ops.append((f["t"], op[0], op[1]))
            abertas.pop(moeda, None)
            if s1 != 0:
                abertas[moeda] = [f["t"], -float(f.get("f", 0.0)) * (1 - fecha), True]
    ops.sort()
    return ops


class Traders:
    def __init__(self, fills: dict[str, list[dict]], fotos: dict[str, list[dict]], cfg: dict | None = None):
        cfg = cfg or {}
        self.conta_minima = cfg.get("conta_minima_para_copiar", 1000)
        self.dias_parado = cfg.get("dias_parado_max", 7)
        self.max_terceiros = cfg.get("max_terceiros", 0.8)
        self.ops = {w: operacoes(fs) for w, fs in fills.items()}
        self.t1 = {w: [o[0] for o in ops] for w, ops in self.ops.items()}
        self.tf = {w: sorted(f["t"] for f in fs) for w, fs in fills.items()}
        self.terceiros = {w: parte_terceiros(fs) for w, fs in fills.items()}
        self.fotos = {w: sorted((f["t"], float(f.get("v") or 0), float(f.get("ntl") or 0)) for f in fs)
                      for w, fs in fotos.items()}
        self.tfoto = {w: [x[0] for x in fs] for w, fs in self.fotos.items()}
        self._cache: dict[tuple, dict | None] = {}

    def ficha(self, w: str, t: int, janela_dias: int) -> dict | None:
        """Os números do trader na janela (t - janela, t]. None se ele não serve para ninguém (regras do ambiente)."""
        chave = (w, t // HORA, janela_dias)
        if chave not in self._cache:
            self._cache[chave] = self._ficha(w, t, janela_dias)
        return self._cache[chave]

    def _ficha(self, w: str, t: int, janela_dias: int) -> dict | None:
        tf = self.tf.get(w) or []
        i = bisect.bisect_right(tf, t) - 1
        if i < 0 or t - tf[i] > self.dias_parado * DIA:
            return None                                   # sumiu: não opera há dias
        if self.terceiros.get(w, 0.0) > self.max_terceiros:
            return None                                   # quase tudo em mercados de terceiros: não dá para copiar
        fotos = self.fotos.get(w) or []
        j = bisect.bisect_right(self.tfoto.get(w) or [], t) - 1
        conta = fotos[j][1] if j >= 0 else 0.0
        if conta < self.conta_minima:
            return None                                   # conta pequena demais ou quebrada
        de = t - janela_dias * DIA
        t1 = self.t1.get(w) or []
        ops = self.ops[w][bisect.bisect_right(t1, de):bisect.bisect_right(t1, t)]
        if not ops:
            return None
        res = [o[2] for o in ops]
        ganhos = sum(x for x in res if x > 0)
        perdas = -sum(x for x in res if x < 0)
        por_dia: dict[int, float] = {}
        for o in ops:
            por_dia[o[0] // DIA] = por_dia.get(o[0] // DIA, 0.0) + o[2]
        expo = [n / v for tt, v, n in fotos[bisect.bisect_right(self.tfoto[w], de):j + 1] if v > 0 and n > 0]
        total = sum(res)
        return {"n": len(ops), "resultado": round(total, 2),
                "fator_lucro": round(min(10.0, ganhos / perdas), 3) if perdas > 0 else (10.0 if ganhos > 0 else 0.0),
                "duracao_min": round(median((o[0] - o[1]) / 60_000 for o in ops), 1),
                "constancia": round(sum(1 for v in por_dia.values() if v > 0) / len(por_dia), 3),
                "retorno": round(total / conta, 4), "conta": conta,
                "exposicao": round(median(expo), 3) if expo else None}


CRITERIOS = {
    "fator_lucro": lambda f: (f["fator_lucro"], f["retorno"]),
    "retorno": lambda f: (f["retorno"], f["fator_lucro"]),
    "constancia": lambda f: (f["constancia"], f["fator_lucro"]),
}


def escolher(genes: dict, t: int, traders: Traders, ativas, fora=()) -> list[tuple[str, dict]]:
    """Quem este DNA copiaria agora: passa pelos mínimos do filtro e fica com os melhores pelo critério dele."""
    ok = []
    for w in sorted(ativas):
        if w in fora:
            continue
        f = traders.ficha(w, t, genes["janela_dias"])
        if not f or f["resultado"] <= 0 or f["n"] < genes["min_operacoes"]:
            continue
        if f["fator_lucro"] < genes["min_fator_lucro"] or f["duracao_min"] < genes["duracao_min"]:
            continue
        ok.append((w, f))
    nota = CRITERIOS[genes["criterio"]]
    ok.sort(key=lambda x: (nota(x[1]), x[0]), reverse=True)
    return ok[:genes["max_carteiras"]]
