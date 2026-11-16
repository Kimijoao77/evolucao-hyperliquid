"""A vida de um robô de cofres, refeita do nascimento a cada rodada (sobre os índices guardados, que nunca mudam).

A cada leitura dos cofres (de 6 em 6 horas):
1. na hora da revisão, escolhe os cofres com o que se sabia naquele instante (índice e ficha até ali) e deposita;
   sai dos que deixaram de passar no filtro (quem continua passando fica, sem mexer no valor);
2. a parada (gene) tira o robô de um cofre que caiu demais desde o pico, até a próxima revisão;
3. o Predador abate o robô que caiu 30 % desde o maior valor que já teve.

Do lucro de cada depósito sai a comissão do dono do cofre (o HLP não cobra). Um depósito fica preso pelo menos 1 dia
(4 no HLP), como na Hyperliquid. Na conta gêmea de estresse, cada depósito e cada saque só acontece 1 dia depois da
decisão e a comissão é 5 pontos maior.
"""
from __future__ import annotations

import bisect

from .. import DIA
from .mercado import HLP

PRESO_DIAS = {"hlp": 4, "outro": 1}


class Cofres:
    """Os índices e as fichas, prontos para consultar por instante."""

    def __init__(self, cofres: dict[str, dict]):
        self.c = cofres
        self.ts = {e: [p[0] for p in c["pts"]] for e, c in cofres.items()}
        self.tf = {e: [f[0] for f in c.get("fichas", [])] for e, c in cofres.items()}

    def idx(self, e: str, t: int) -> float | None:
        j = bisect.bisect_right(self.ts.get(e, []), t)
        return self.c[e]["pts"][j - 1][1] if j else None

    def ficha(self, e: str, t: int):
        j = bisect.bisect_right(self.tf.get(e, []), t)
        return self.c[e]["fichas"][j - 1] if j else None

    def medidas(self, e: str, t: int, janela_dias: int) -> dict | None:
        """Retorno, maior queda e semanas no azul na janela (t - janela, t], só com pontos até t."""
        c, ts = self.c[e], self.ts[e]
        de = t - janela_dias * DIA
        j1 = bisect.bisect_right(ts, t)
        if j1 < 2 or ts[0] > de + 0.2 * janela_dias * DIA or t - ts[j1 - 1] > 2 * DIA:
            return None                                   # pouco histórico na janela, ou dado velho
        j0 = max(0, bisect.bisect_right(ts, de) - 1)
        pts = c["pts"][j0:j1]
        if len(pts) < 4 or pts[0][1] <= 0:
            return None
        ret = pts[-1][1] / pts[0][1] - 1
        pico, queda = pts[0][1], 0.0
        for _, x in pts:
            pico = max(pico, x)
            queda = max(queda, 1 - x / pico)
        sem, ini, base = [], pts[0][0], pts[0][1]
        for tt, x in pts:
            if tt - ini >= 7 * DIA:
                sem.append(x / base - 1)
                ini, base = tt, x
        return {"ret": ret, "queda": queda, "semanas": sum(1 for s in sem if s > 0) / len(sem) if sem else 0.0}


CRITERIOS = {
    "retorno": lambda m: (m["ret"], -m["queda"]),
    "constancia": lambda m: (m["semanas"], m["ret"]),
    "eficiencia": lambda m: (m["ret"] / max(0.02, m["queda"]), m["ret"]),
}


def escolher(g: dict, cf: Cofres, t: int, fora=()) -> list[str]:
    """Os cofres de trader que este DNA escolheria agora (o HLP entra à parte, pelo peso_hlp)."""
    ok = []
    for e, c in cf.c.items():
        if e == HLP or e in fora or c.get("filho"):
            continue
        f = cf.ficha(e, t)
        if not f or t - f[0] > 2 * DIA or not f[2] or f[3]:
            continue                                      # sem ficha recente, sem depósito ou fechado
        if f[1] < g["min_tvl"] or (t - c.get("criado", t)) / DIA < g["min_idade_dias"]:
            continue
        m = cf.medidas(e, t, g["janela_dias"])
        if not m or m["ret"] <= 0 or m["queda"] > g["max_queda"]:
            continue
        ok.append((CRITERIOS[g["criterio"]](m), e))
    ok.sort(reverse=True)
    return [e for _, e in ok[:g["n_cofres"]]]


def _valor(h: dict, x: float | None, com: float) -> float:
    if x is None or h["e0"] <= 0:
        return h["a"]
    bruto = h["a"] * x / h["e0"]
    return h["a"] + (bruto - h["a"]) * (1 - com) if bruto > h["a"] else bruto


def viver(g: dict, cf: Cofres, grade: list[int], t0: int, ate: int, capital: float, queda_abate: float,
          estresse: bool = False) -> dict:
    atraso = DIA if estresse else 0
    extra = 0.05 if estresse else 0.0
    i0, i1 = bisect.bisect_left(grade, t0), bisect.bisect_right(grade, ate)
    caixa, hold = capital, {}
    pico_abs = capital
    pts, eq, ops = [], [], []
    revisar_em, bloq = t0, set()
    pend: list[tuple[int, str, str, float]] = []          # (quando, "sai"/"entra", cofre, peso)
    morte = morreu_em = None
    com = lambda e: min(0.5, cf.c[e].get("comissao", 0.10) + extra)  # noqa: E731

    def sair(e: str, t: int) -> None:
        nonlocal caixa
        h = hold.pop(e)
        caixa += _valor(h, cf.idx(e, t), com(e))
        ops.append(t)

    for t in grade[i0:i1]:
        # 1. o que foi decidido antes e chegou a hora (na conta normal, na mesma hora)
        agora_pend = [p for p in pend if p[0] <= t]
        pend = [p for p in pend if p[0] > t]
        total = caixa + sum(_valor(h, cf.idx(e, t), com(e)) for e, h in hold.items())
        for _, tipo, e, peso in sorted(agora_pend, key=lambda p: (p[1] != "sai", p[2])):
            if tipo == "sai" and e in hold:
                sair(e, t)
            elif tipo == "entra" and e not in hold:
                x = cf.idx(e, t)
                a = min(caixa, total * peso)
                if x and a >= 10:
                    caixa -= a
                    hold[e] = {"a": a, "e0": x, "pico": a, "desde": t}
                    ops.append(t)
        # 2. revisão
        if t >= revisar_em:
            bloq = set()
            quer = escolher(g, cf, t)
            pesos = {}
            if g.get("peso_hlp") and cf.idx(HLP, t):
                pesos[HLP] = g["peso_hlp"]
            for e in quer:
                pesos[e] = (1 - pesos.get(HLP, 0.0)) / len(quer)
            for e in hold:
                if e not in pesos and not any(p[2] == e and p[1] == "sai" for p in pend):
                    pend.append((t + atraso, "sai", e, 0.0))
            for e, p in pesos.items():
                if e not in hold:
                    pend.append((t + atraso, "entra", e, p))
            revisar_em = t + g["revisao_dias"] * DIA
            if not atraso:                                # na conta normal o depósito sai na mesma leitura
                total = caixa + sum(_valor(h, cf.idx(e, t), com(e)) for e, h in hold.items())
                for _, tipo, e, peso in sorted(pend, key=lambda p: (p[1] != "sai", p[2])):
                    if tipo == "sai" and e in hold:
                        sair(e, t)
                for _, tipo, e, peso in sorted(pend, key=lambda p: p[2]):
                    if tipo == "entra" and e not in hold:
                        x = cf.idx(e, t)
                        a = min(caixa, total * peso)
                        if x and a >= 10:
                            caixa -= a
                            hold[e] = {"a": a, "e0": x, "pico": a, "desde": t}
                            ops.append(t)
                pend = []
        # 3. parada em cada cofre
        for e, h in list(hold.items()):
            v = _valor(h, cf.idx(e, t), com(e))
            h["pico"] = max(h["pico"], v)
            preso = PRESO_DIAS["hlp" if e == HLP else "outro"] * DIA
            if g.get("parada") and v < (1 - g["parada"]) * h["pico"] and t - h["desde"] >= preso and e not in bloq:
                bloq.add(e)
                if atraso:
                    pend.append((t + atraso, "sai", e, 0.0))
                else:
                    sair(e, t)
        total = caixa + sum(_valor(h, cf.idx(e, t), com(e)) for e, h in hold.items())
        pico_abs = max(pico_abs, total)
        pts.append(t)
        eq.append(total)
        # 4. o Predador
        if total <= (1 - queda_abate) * pico_abs:
            for e in list(hold):
                sair(e, t)
            eq[-1] = caixa
            morte, morreu_em = f"abatido: caiu {round(100 * queda_abate)} % desde o pico", t
            for tt in grade[bisect.bisect_right(grade, t):i1]:
                pts.append(tt)
                eq.append(caixa)
            break
    return {"pts": pts, "eq": eq, "ops": ops, "freios": [], "morte": morte, "morreu_em": morreu_em,
            "descanso_ate": None, "capital": capital, "em": sorted(hold)}
