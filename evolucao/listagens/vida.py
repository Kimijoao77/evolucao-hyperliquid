"""A vida de um robô de moedas novas, refeita do nascimento a cada rodada.

Cada moeda que estreia vira uma venda, se o robô tiver vaga: entra `espera_h` horas depois da estreia (na abertura da
primeira vela depois disso, a mercado), com `parte` do patrimônio de margem. Sai na parada (o preço subiu demais), no
alvo (caiu o bastante), no prazo ou quando a moeda sai da Hyperliquid. Na vela em que a parada e o alvo cabem juntos,
conta a parada (o pior caso). Se o preço passa do ponto de liquidação, perde a margem inteira daquela moeda.
Vendido recebe o funding quando ele é positivo e paga quando é negativo.
"""
from __future__ import annotations

import bisect

from .. import HORA

TAXA = 0.00045


def manutencao(alav_max) -> float:
    return 1 / (2 * max(1.0, float(alav_max or 3)))


def _r(rel: float, fund: float, alav: float, custo: float, manut: float) -> float:
    """Resultado sobre a margem, como se fechasse com o preço em `rel` vezes o da venda."""
    if rel >= 1 + 1 / alav - manut:
        return -1.0
    return max(-1.0, alav * ((1 - rel) - custo - custo * rel + fund))


def viver(g: dict, moedas: dict[str, dict], t0: int, ate: int, capital: float, queda_abate: float,
          estresse: bool = False) -> dict:
    custo = TAXA + (0.003 if estresse else 0.001)            # taxa + escorregamento em cada ponta (livro fino)
    atraso = HORA if estresse else 0
    # as entradas possíveis, em ordem
    entradas = []
    for n, m in moedas.items():
        vs = m["velas"]
        alvo_t = m["estreia"] + g["espera_h"] * HORA + atraso
        if alvo_t < t0 or alvo_t >= ate:
            continue
        ts = [v["t"] for v in vs]
        k = bisect.bisect_left(ts, alvo_t)
        if k < len(vs) and vs[k]["t"] + HORA <= ate:
            entradas.append((vs[k]["t"], n, k))
    entradas.sort()
    grade = list(range(t0 // HORA * HORA + HORA, ate // HORA * HORA + 1, HORA))
    caixa, abertas, pico_abs = capital, [], capital
    pts, eq, ops = [], [], []
    morte = morreu_em = None
    ie = 0
    for T in grade:                                          # T = fechamento da vela que abriu em T - HORA
        while ie < len(entradas) and entradas[ie][0] <= T - HORA:
            te, n, k = entradas[ie]
            ie += 1
            m = moedas[n]
            px = m["velas"][k]["o"]
            if len(abertas) >= g["max_abertas"] or px <= 0:
                continue
            p0 = m["velas"][0]["o"] if m["velas"] else px
            if g.get("teto_estreia") and px > g["teto_estreia"] * p0:
                continue
            margem = g["parte"] * (caixa + sum(a["valor"] for a in abertas))
            if margem < 10:
                continue
            caixa -= margem
            abertas.append({"n": n, "k": k, "px": px, "m": margem, "fund": 0.0, "fim": te + g["prazo_dias"] * 24 * HORA,
                            "manut": manutencao(m.get("alav_max")), "valor": margem * (1 + _r(1.0, 0.0, g["alav"], custo, manutencao(m.get("alav_max"))))})
            ops.append(te)
        for a in list(abertas):
            vs = moedas[a["n"]]["velas"]
            fu = moedas[a["n"]].get("funding") or {}
            fechou = None
            while a["k"] < len(vs) and vs[a["k"]]["t"] + HORA <= T:
                v = vs[a["k"]]
                a["k"] += 1
                para, meta = a["px"] * (1 + g["parada"]), a["px"] * (1 - g["alvo"]) if g.get("alvo") else None
                if v["h"] >= para:
                    fechou = max(v["o"], para) / a["px"]
                    break
                if meta is not None and v["l"] <= meta:
                    fechou = min(v["o"], meta) / a["px"]
                    break
                a["fund"] += fu.get(v["t"] + HORA, 0.0) * v["c"] / a["px"]
                rel = v["c"] / a["px"]
                if v["t"] + HORA >= a["fim"]:
                    fechou = rel
                    break
                a["valor"] = a["m"] * (1 + _r(rel, a["fund"], g["alav"], custo, a["manut"]))
                if a["valor"] <= 0:
                    fechou = rel
                    break
            sumiu = moedas[a["n"]].get("fora") and a["k"] >= len(vs) and fechou is None and T - (vs[-1]["t"] + HORA if vs else T) > 6 * HORA
            if fechou is not None or sumiu:
                rel = fechou if fechou is not None else vs[-1]["c"] / a["px"]
                caixa += a["m"] * (1 + _r(rel, a["fund"], g["alav"], custo, a["manut"]))
                abertas.remove(a)
                ops.append(T)
        total = caixa + sum(a["valor"] for a in abertas)
        pico_abs = max(pico_abs, total)
        pts.append(T)
        eq.append(total)
        if total <= (1 - queda_abate) * pico_abs:            # o Predador: fecha tudo e morre
            for a in abertas:
                caixa += a["valor"] * (1 - custo * g["alav"])
            abertas = []
            eq[-1] = max(0.0, caixa)
            morte, morreu_em = f"abatido: caiu {round(100 * queda_abate)} % desde o pico", T
            for tt in grade[grade.index(T) + 1:]:
                pts.append(tt)
                eq.append(eq[-1])
            break
    return {"pts": pts, "eq": eq, "ops": ops, "freios": [], "morte": morte, "morreu_em": morreu_em, "descanso_ate": None,
            "capital": capital, "em": [a["n"] for a in abertas]}
