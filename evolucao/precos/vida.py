"""A vida de um robô de preço, recalculada inteira desde o nascimento a cada rodada.

As velas fechadas não mudam, então refazer a conta desde o nascimento dá sempre o mesmo resultado até onde ela já
tinha chegado: não há estado para guardar nem para corromper. O simulador só vê a vela da hora e as de antes.

Por cima do simulador entram as regras de fora dele:
- FREIO (gene): a conta caiu `freio` desde o pico do trecho → fecha tudo a mercado, descansa 3 dias e recomeça do zero
  com o que sobrou (a grade, por exemplo, recentra a faixa no preço do recomeço);
- ABATE (limite duro do Predador): caiu 30 % desde o maior valor que já teve, ou foi liquidado → fecha tudo e morre.
"""
from __future__ import annotations

import bisect

from .. import DIA, HORA
from . import sim

ANTES = 700                       # velas de antes do começo de um trecho, para as médias e os canais já valerem


def simular(regra: dict, velas: list[dict], antes: list[dict], funding: dict | None, capital: float, custo: dict,
            ops: list) -> dict:
    t = regra["tipo"]
    if t == "grade":
        return sim.grade(velas, regra["faixa"], regra["niveis"], regra["alav"], capital, ops, funding, custo=custo)
    if t == "tendencia":
        return sim.tendencia(velas, regra["modo"], regra["a"], regra.get("b"), regra["alav"], capital, ops, antes, funding, custo=custo)
    if t == "reversao":
        return sim.reversao(velas, regra["gatilho"], regra["alvo"], regra["lados"], regra["alav"], capital, ops, antes, funding, custo=custo)
    mh = regra.get("media_h") or 0
    hist = [float(v["c"]) for v in antes][-mh:] if mh else None
    return sim.dca(velas, regra["passo"], regra["alvo"], alav=regra["alav"], capital=capital, ops=ops, media_h=mh,
                   historico=hist, funding=funding, custo=custo)


def viver(regra: dict, freio: float, velas: list[dict], funding: dict | None, t0: int, ate: int, capital: float,
          custo: dict, queda_abate: float, descanso_h: int = 72) -> dict:
    """A conta do robô do nascimento (t0) até `ate`, hora a hora. pts: o fechamento de cada vela (ms); eq: o
    patrimônio naquele instante; ops: o instante de cada ordem."""
    ts = [v["t"] for v in velas]
    i0, i1 = bisect.bisect_left(ts, t0), bisect.bisect_right(ts, ate - HORA)
    pts: list[int] = []
    eq: list[float] = []
    ops_t: list[int] = []
    freios: list[int] = []
    cap = pico_abs = capital
    morte = morreu_em = descanso_ate = None
    s = i0
    while s < i1:
        ops: list = []
        r = simular(regra, velas[s:i1], velas[max(0, s - ANTES):s], funding, cap, custo, ops)
        e = r["eq"]
        pico, corte, motivo = cap, None, None
        for k, v in enumerate(e):
            pico_abs, pico = max(pico_abs, v), max(pico, v)
            if v <= 0 or r.get("liquidada") and k == len(e) - 1:
                corte, motivo = k, "abatido: a conta zerou (liquidada)"
                break
            if v <= (1 - queda_abate) * pico_abs:
                corte, motivo = k, f"abatido: caiu {round(100 * queda_abate)} % desde o pico"
                break
            if freio and v <= (1 - freio) * pico:
                corte, motivo = k, "freio"
                break
        n = len(e) if corte is None else corte + 1
        for k in range(n):
            pts.append(velas[s + k]["t"] + HORA)
            eq.append(e[k])
        ops_t += [o["t"] for o in ops if o["t"] <= velas[s + n - 1]["t"]]
        if corte is None:
            break
        # fecha tudo a mercado no fechamento desta vela (custo calculado como se a posição inteira estivesse aberta)
        eq[-1] = max(0.0, eq[-1] - eq[-1] * regra["alav"] * (custo["taker"] + custo["slip"]))
        ops_t.append(velas[s + n - 1]["t"])
        if motivo != "freio":
            morte, morreu_em = motivo, pts[-1]
            for k in range(s + n, i1):                    # morto: a conta para (o resto é só para o desenho)
                pts.append(velas[k]["t"] + HORA)
                eq.append(eq[-1])
            break
        freios.append(pts[-1])
        cap, parou = eq[-1], pts[-1]
        fim = min(i1, s + n + descanso_h)
        for k in range(s + n, fim):
            pts.append(velas[k]["t"] + HORA)
            eq.append(cap)
        if s + n + descanso_h > i1:
            descanso_ate = parou + descanso_h * HORA
        s = fim
    return {"pts": pts, "eq": eq, "ops": ops_t, "freios": freios, "morte": morte, "morreu_em": morreu_em,
            "descanso_ate": descanso_ate, "capital": capital}


def valor_em(v: dict, t: int) -> float:
    """O patrimônio no instante t (o último fechamento até t; antes do primeiro, o capital)."""
    j = bisect.bisect_right(v["pts"], t)
    return v["eq"][j - 1] if j else v["capital"]


def medir(v: dict, de: int, ate: int) -> dict:
    """As medidas do robô na geração (de, ate]: retorno, maior queda, retorno sem o melhor dia e ordens."""
    pts, eq = v["pts"], v["eq"]
    base = valor_em(v, de)
    j, k = bisect.bisect_right(pts, de), bisect.bisect_right(pts, ate)
    fim = eq[k - 1] if k > j else base
    r = fim / base - 1 if base > 0 else -1.0
    pico, queda = base, 0.0
    melhor, ant, dia_ant = 0.0, base, None
    for i in range(j, k):
        pico = max(pico, eq[i])
        if pico > 0:
            queda = max(queda, 1 - eq[i] / pico)
        dia = (pts[i] - 1) // DIA
        if dia_ant is not None and dia != dia_ant:        # virou o dia: fecha o dia anterior
            melhor = max(melhor, eq[i - 1] / ant - 1 if ant > 0 else 0.0)
            ant = eq[i - 1]
        dia_ant = dia
    if k > j and ant > 0:
        melhor = max(melhor, eq[k - 1] / ant - 1)
    ordens = sum(1 for t in v["ops"] if de <= t < ate)
    return {"r": r, "queda": queda, "sm": r - max(0.0, melhor), "ordens": ordens}
