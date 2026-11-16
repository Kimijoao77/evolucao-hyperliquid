"""Um robô vivendo: a conta de mentira dele andando no tempo com as regras do DNA.

Cada robô tem DUAS contas, com o mesmo DNA: a normal e a gêmea de estresse (atraso e escorregamento piores). A gêmea
mostra quanto do resultado depende de execução perfeita.

A conta tem um caixa e uma subconta por trader copiado. A cada 5 minutos de mercado:
1. se chegou a hora, revê quem copia (com a ficha dos traders até aquele instante);
2. aplica as mudanças de posição dos traders copiados (com o atraso do ambiente);
3. confere cada posição (corte, ganho, tempo máximo), cada trader (parada) e o robô inteiro (freio);
4. o Predador confere os limites duros: passou, o robô é abatido na hora.
"""
from __future__ import annotations

import bisect

from . import DIA, HORA, MINUTO
from . import mercado as M
from .traders import escolher

PASSO = 5 * MINUTO
APORTE_MINIMO = 50.0


def nova_conta(capital: float, t: int) -> dict:
    return {"caixa": capital, "subs": {}, "pat": capital, "base": capital, "pico": capital, "pico_g": capital,
            "pico_abs": capital, "queda": 0.0, "vivo": True, "morte": None, "descanso_ate": 0, "revisar_em": t,
            "bloqueadas": {}, "ordens": 0, "taxas": 0.0, "fechado": {}, "freios": 0, "paradas": 0, "pulos": {},
            "expo_max": 0.0, "t": t}


class Mundo:
    """O que todas as contas enxergam numa rodada: preços, traders, eventos e os limites do ambiente."""

    def __init__(self, precos, traders, fills: dict, fotos: dict, ativas, limites: dict, predador):
        self.precos, self.traders, self.fills, self.fotos = precos, traders, fills, fotos
        self.ativas, self.limites, self.predador = set(ativas), limites, predador
        self.saldos = traders.saldos                       # o mesmo saldo que a ficha usa (fotos ou o de referência)
        self._evs: dict[tuple, tuple[list, list]] = {}
        self.diario: list[dict] = []                      # o que aconteceu de notável (paradas, freios, abates)

    def eventos(self, w: str, atraso_ms: int) -> tuple[list[dict], list[int]]:
        chave = (w, atraso_ms)
        if chave not in self._evs:
            evs = M.eventos(self.fills.get(w, []), atraso_ms, self.fotos.get(w))
            evs.sort(key=lambda e: (e["t"], e["moeda"]))
            self._evs[chave] = (evs, [e["t"] for e in evs])
        return self._evs[chave]


def patrimonio(conta: dict, precos, t: int) -> float:
    return conta["caixa"] + sum(M.patrimonio(s, precos, t) for s in conta["subs"].values())


def exposicao(conta: dict, precos, t: int) -> float:
    return sum(M.exposicao(s, precos, t) for s in conta["subs"].values())


def fechar_sub(conta: dict, w: str, mundo: Mundo, t: int, amb: dict) -> None:
    """Zera as posições copiadas deste trader e devolve o dinheiro ao caixa."""
    sub = conta["subs"].pop(w)
    for m in list(sub["pos"]):
        M.fechar_posicao(conta, sub, m, mundo.precos, t, amb)
    conta["caixa"] += sub["colateral"]
    conta["fechado"][w] = conta["fechado"].get(w, 0.0) + sub["colateral"] - sub["base"]


def fechar_tudo(conta: dict, mundo: Mundo, t: int, amb: dict) -> None:
    for w in list(conta["subs"]):
        fechar_sub(conta, w, mundo, t, amb)


def revisar(conta: dict, genes: dict, mundo: Mundo, t: int, amb: dict) -> None:
    """Revê quem copiar: sai de quem deixou de passar no filtro e entra nos novos, com o dinheiro que estiver no caixa."""
    escolhidos = escolher(genes, t, mundo.traders, mundo.ativas, fora=conta["bloqueadas"])
    quer = {w for w, _ in escolhidos}
    for w in [w for w in conta["subs"] if w not in quer]:
        fechar_sub(conta, w, mundo, t, amb)
    total = patrimonio(conta, mundo.precos, t)
    lim = mundo.limites
    fatia = min(total / max(1, len(escolhidos)), lim["peso_max_por_carteira"] * total)
    for w, ficha in escolhidos:
        if w in conta["subs"]:
            continue
        aporte = min(fatia, conta["caixa"])
        if aporte < APORTE_MINIMO:
            break
        x = ficha.get("exposicao")
        fator = max(0.05, min(1.0, genes["alvo"] / x)) if x and x > 0 else 1.0
        teto = min(lim["exposicao_max"], genes["alvo"] * 1.5)
        conta["caixa"] -= aporte
        conta["subs"][w] = M.nova_sub(w, t, aporte, fator, teto)
    conta["revisar_em"] = t + genes["revisao_dias"] * DIA


def _passo(conta: dict, genes: dict, amb: dict, mundo: Mundo, g: int) -> None:
    precos = mundo.precos
    if conta["descanso_ate"] and g >= conta["descanso_ate"]:          # acabou o descanso: recomeça do zero
        conta["descanso_ate"] = 0
        conta["pico"] = patrimonio(conta, precos, g)
        conta["revisar_em"] = g
    if not conta["descanso_ate"] and g >= conta["revisar_em"]:
        revisar(conta, genes, mundo, g, amb)

    for w in list(conta["subs"]):
        sub = conta["subs"][w]
        if w not in mundo.ativas:                                      # o trader saiu do universo (sumiu ou quebrou)
            fechar_sub(conta, w, mundo, g, amb)
            continue
        evs, ts = mundo.eventos(w, amb["atraso_s"] * 1000)
        for ev in evs[bisect.bisect_right(ts, sub["ult"]):]:
            if ev["exec"] > g:
                break
            motivo = M.aplicar(conta, sub, ev, mundo.saldos[w].em(ev["t"]), precos, amb, genes["desvio_max"])
            if motivo:
                conta["pulos"][motivo] = conta["pulos"].get(motivo, 0) + 1
            sub["ult"] = max(sub["ult"], ev["t"])
        # cada posição: corte, ganho e tempo máximo (sai antes do trader e espera ele sair para voltar à moeda)
        for m in list(sub["pos"]):
            q, a = sub["pos"][m]
            p = precos.em(m, g)
            if p is None or a <= 0:
                continue
            ret = (p - a) / a * (1 if q > 0 else -1)
            sair = ((genes["corte"] and ret <= -genes["corte"]) or (genes["ganho"] and ret >= genes["ganho"])
                    or (genes["tempo_max_h"] and g - sub["desde"].get(m, g) >= genes["tempo_max_h"] * HORA))
            if sair and M.fechar_posicao(conta, sub, m, precos, g, amb):
                sub["travas"][m] = 1 if q > 0 else -1
        # o trader inteiro: parada desde o pico da subconta
        pat = M.patrimonio(sub, precos, g)
        sub["pico"] = max(sub["pico"], pat)
        if pat <= 0 or pat < (1 - genes["parada"]) * sub["pico"]:
            fechar_sub(conta, w, mundo, g, amb)
            conta["bloqueadas"][w] = g                                 # não volta a este trader nesta geração
            conta["paradas"] += 1

    pat = patrimonio(conta, precos, g)
    conta["pat"] = pat
    for k in ("pico", "pico_g", "pico_abs"):
        conta[k] = max(conta[k], pat)
    conta["queda"] = max(conta["queda"], 1 - pat / conta["pico_g"])
    if pat > 0:
        conta["expo_max"] = max(conta["expo_max"], exposicao(conta, precos, g) / pat)
    morte = mundo.predador.abate(conta)
    if morte:
        fechar_tudo(conta, mundo, g, amb)
        conta.update(vivo=False, morte=morte, morreu_em=g, pat=max(0.0, conta["caixa"]))
    elif conta["subs"] and pat < (1 - genes["freio"]) * conta["pico"]:   # freio do robô: fecha tudo e descansa
        fechar_tudo(conta, mundo, g, amb)
        conta["descanso_ate"] = g + int(mundo.limites["descanso_dias"] * DIA)
        conta["freios"] += 1
        conta["pat"] = conta["caixa"]
    conta["t"] = g


def avancar(conta: dict, genes: dict, amb: dict, mundo: Mundo, ate: int) -> None:
    """Leva a conta de onde ela parou até `ate`, de 5 em 5 minutos."""
    while conta["vivo"] and conta["t"] < ate:
        _passo(conta, genes, amb, mundo, min(ate, (conta["t"] // PASSO + 1) * PASSO))
    conta["t"] = max(conta["t"], ate)


def virar_conta(conta: dict, mundo: Mundo, t: int) -> None:
    """Começo de uma geração nova para quem sobreviveu: a conta continua, só as medidas da geração recomeçam."""
    pat = patrimonio(conta, mundo.precos, t)
    for sub in conta["subs"].values():
        sub["base"] = M.patrimonio(sub, mundo.precos, t)
    conta.update(pat=pat, base=pat, pico_g=pat, queda=0.0, ordens=0, taxas=0.0, fechado={}, bloqueadas={},
                 freios=0, paradas=0, pulos={}, expo_max=0.0)


def resultado_por_trader(conta: dict, mundo: Mundo, t: int) -> dict[str, float]:
    """Quanto cada trader copiado rendeu (em dólares) nesta geração."""
    res = dict(conta["fechado"])
    for w, sub in conta["subs"].items():
        res[w] = res.get(w, 0.0) + M.patrimonio(sub, mundo.precos, t) - sub["base"]
    return res
