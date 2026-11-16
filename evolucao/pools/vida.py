"""A vida de um robô de pools concentradas, refeita do nascimento a cada rodada.

A cada rodada (de 2 em 2 horas):
1. as posições abertas andam pelas velas de 5 min desde a rodada anterior: recebem a taxa nas velas em que o preço
   ficou dentro da faixa (a taxa da pool sobre o dinheiro dela na última hora, vezes a fatia da posição) e saem se o
   preço fechou abaixo da faixa, se ficou acima dela por `espera_acima_h` horas ou no prazo;
2. as vagas livres abrem posições nas pools elegíveis daquela rodada que passam no filtro do DNA (com o que se sabia
   naquela hora).
O valor é contado em SOL/USDC pelo preço do SOL na entrada (o teste mede a pool, não o SOL). Custos: rede 0,02 % por
ponta; na saída, a taxa da pool + 0,2 % sobre a parte que virou moeda; na faixa centrada, também a troca de metade
na entrada. Na conta gêmea de estresse a posição leva metade da fatia da taxa e o escorregamento dobra.
"""
from __future__ import annotations

import bisect

from .. import HORA, MINUTO
from .conta import balanco, fator, liquidez, parte_moeda, valor_y

REDE = 0.0002
ESCORREGA = 0.002


class Pools:
    def __init__(self, pools: dict[str, dict], rodadas: list):
        self.p = pools
        self.rodadas = rodadas
        self.tf = {a: [f[0] for f in p.get("fotos", [])] for a, p in pools.items()}
        self.t5 = {a: [v[0] for v in p.get("m5", [])] for a, p in pools.items()}

    def foto(self, a: str, t: int):
        j = bisect.bisect_right(self.tf.get(a, []), t)
        return self.p[a]["fotos"][j - 1] if j else None

    def balanco(self, a: str, t: int) -> float | None:
        """O balanço das últimas 24 h até t: velas de 1 h de antes da primeira foto + as de 5 min (de hora em hora)."""
        p = self.p[a]
        horas = {v[0] // HORA: v[1] for v in p.get("h1", []) if v[0] + HORA <= t}
        j = bisect.bisect_right(self.t5.get(a, []), t - 5 * MINUTO)
        for v in p.get("m5", [])[:j]:
            horas[v[0] // HORA] = v[1]
        cs = [horas[h] for h in sorted(horas) if h >= t // HORA - 26]
        return balanco(cs)


def _abrir(pp: Pools, a: str, g: dict, dolares: float, t: int, fatia: float) -> dict | None:
    f = pp.foto(a, t)
    if not f or f[1] <= 0 or f[7] <= 0:
        return None
    p0, py, taxa = f[1], f[7], f[6] / 100
    r = g["r"]
    if g["posicao"] == "abaixo":
        lo, hi, custo = p0 * (1 - 2 * r), p0, REDE
    else:
        lo, hi = p0 * (1 - r), p0 * (1 + r)
        custo = REDE + 0.5 * (taxa + ESCORREGA)            # troca metade do SOL/USDC pela moeda
    liq = dolares * (1 - custo)
    return {"a": a, "lo": lo, "hi": hi, "L": liquidez(liq / py, p0, lo, hi), "py": py, "p": p0, "taxas": 0.0,
            "taxa_pct": taxa + ESCORREGA * (2 if fatia < 1 else 1), "desde": t, "ult": t, "acima": None,
            "fator": fator(r, pp.p[a].get("bin_step"), f[4], dolares) * fatia, "d": dolares}


def _valor(pos: dict) -> float:
    return valor_y(pos["L"], pos["p"], pos["lo"], pos["hi"]) * pos["py"] + pos["taxas"]


def _fechar(pos: dict) -> float:
    v = _valor(pos)
    moeda = parte_moeda(pos["L"], pos["p"], pos["lo"], pos["hi"]) * (v - pos["taxas"])
    return v - moeda * pos["taxa_pct"] - v * REDE


def _andar(pp: Pools, pos: dict, ate: int, g: dict) -> bool:
    """Passa as velas de 5 min até `ate`. Devolve True se a posição saiu."""
    m5, ts = pp.p[pos["a"]].get("m5", []), pp.t5.get(pos["a"], [])
    for t, c in m5[bisect.bisect_left(ts, pos["ult"]):]:
        if t + 5 * MINUTO > ate:
            break
        pos["ult"], pos["p"] = t + 5 * MINUTO, c
        if pos["lo"] <= c <= pos["hi"]:
            f = pp.foto(pos["a"], t)
            taxa5 = max(0.0, f[2] if f else 0.0) / 100 / 12 * pos["fator"]
            pos["taxas"] += valor_y(pos["L"], c, pos["lo"], pos["hi"]) * pos["py"] * taxa5
            pos["acima"] = None
        elif c < pos["lo"]:
            return True
        else:
            pos["acima"] = pos["acima"] or t
            if pos["ult"] - pos["acima"] >= g["espera_acima_h"] * HORA:
                return True
        if pos["ult"] >= pos["desde"] + g["prazo_h"] * HORA:
            return True
    return ate >= pos["desde"] + g["prazo_h"] * HORA and pos["ult"] >= ate - 15 * MINUTO


CRITERIO = {"taxa_24h": lambda f: f[3], "taxa_1h": lambda f: f[2], "volume": lambda f: f[5] / max(1.0, f[4])}


def escolher(pp: Pools, g: dict, t: int, elegiveis: list[str], fora=()) -> list[str]:
    ok = []
    for a in elegiveis:
        if a in fora or a not in pp.p:
            continue
        f = pp.foto(a, t)
        if not f or f[0] != t or f[4] < g["tvl_min"]:
            continue
        if g.get("balanco_max"):
            b = pp.balanco(a, t)
            if b is None or b > g["balanco_max"]:
                continue
        ok.append((CRITERIO[g["criterio"]](f), a))
    ok.sort(reverse=True)
    return [a for _, a in ok]


def viver(g: dict, pp: Pools, t0: int, ate: int, capital: float, queda_abate: float, estresse: bool = False) -> dict:
    fatia = 0.5 if estresse else 1.0
    caixa, abertas, pico_abs = capital, [], capital
    pts, eq, ops = [], [], []
    morte = morreu_em = None
    grade = [r for r in pp.rodadas if t0 <= r[0] <= ate]
    for k, (t, ele) in enumerate(grade):
        for pos in list(abertas):
            if _andar(pp, pos, t, g):
                caixa += _fechar(pos)
                abertas.remove(pos)
                ops.append(t)
        vagas = g["n_pools"] - len(abertas)
        if vagas > 0:
            for a in escolher(pp, g, t, ele, {p["a"] for p in abertas})[:vagas]:
                dol = caixa / (g["n_pools"] - len(abertas))
                if dol < 10:
                    break
                pos = _abrir(pp, a, g, dol, t, fatia)
                if pos:
                    caixa -= dol
                    abertas.append(pos)
                    ops.append(t)
        total = caixa + sum(_fechar(p) for p in abertas)
        pico_abs = max(pico_abs, total)
        pts.append(t)
        eq.append(total)
        if total <= (1 - queda_abate) * pico_abs:
            caixa = total
            abertas = []
            morte, morreu_em = f"abatido: caiu {round(100 * queda_abate)} % desde o pico", t
            for tt, _ in grade[k + 1:]:
                pts.append(tt)
                eq.append(caixa)
            break
    return {"pts": pts, "eq": eq, "ops": ops, "freios": [], "morte": morte, "morreu_em": morreu_em, "descanso_ate": None,
            "capital": capital, "em": [pp.p[p["a"]].get("nome", p["a"][:8]) for p in abertas]}
