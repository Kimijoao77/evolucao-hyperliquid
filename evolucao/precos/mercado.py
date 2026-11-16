"""As velas de 1 hora e o funding de cada moeda, guardados no ramo `estado` e completados a cada rodada.

dados/precos/velas/<moeda>.json     [[t, o, h, l, c], ...] (t = abertura da vela, em ms; só velas já fechadas)
dados/precos/funding/<moeda>.json   {"<hora em ms>": taxa por hora}

Só guarda o que algum robô vivo ainda pode precisar: desde 800 h antes do nascimento do robô mais velho (as médias e
os canais da tendência olham até 700 h para trás).
"""
from __future__ import annotations

import math

from .. import HORA
from .. import dados as D

GUARDAR_ANTES_H = 800


def _arq(tipo: str, moeda: str):
    return D.pasta() / "precos" / tipo / f"{moeda}.json"


def ler_velas(moeda: str) -> list[dict]:
    return [{"t": int(v[0]), "o": v[1], "h": v[2], "l": v[3], "c": v[4]} for v in D.ler_json(_arq("velas", moeda), [])]


def ler_funding(moeda: str) -> dict[int, float]:
    return {int(h): float(x) for h, x in D.ler_json(_arq("funding", moeda), {}).items()}


def baixar_funding(api, moeda: str, desde: int, ate: int) -> dict[int, float]:
    """fundingHistory, 500 por chamada: {hora em ms: taxa por hora}."""
    out, t = {}, int(desde)
    while t < ate:
        pag = api._post({"type": "fundingHistory", "coin": moeda, "startTime": t, "endTime": int(ate)}, 20) or []
        api.lim.gastar(math.ceil(len(pag) / 20))
        for r in pag:
            out[int(r["time"]) // HORA * HORA] = float(r["fundingRate"])
        if len(pag) < 500:
            break
        t = max(int(r["time"]) for r in pag) + 1
    return out


def atualizar(api, moedas, agora: int, desde: int, log: list[str]) -> dict[str, list[dict]]:
    """Completa as velas e o funding de cada moeda até agora e apaga o que ficou velho demais. Uma moeda que falhar
    fica com o que já estava guardado (os robôs dela simplesmente não andam nesta rodada)."""
    corte = desde - GUARDAR_ANTES_H * HORA
    velas = {}
    for m in moedas:
        vs = [v for v in ler_velas(m) if v["t"] >= corte]
        try:
            de = vs[-1]["t"] + HORA if vs else corte
            while de + HORA <= agora:
                pag = api.velas(m, "1h", de, agora)
                novas = [{"t": int(v["t"]), "o": float(v["o"]), "h": float(v["h"]), "l": float(v["l"]), "c": float(v["c"])}
                         for v in pag if int(v["t"]) >= de and int(v["t"]) + HORA <= agora]
                if not novas:
                    break
                vs += novas
                de = novas[-1]["t"] + HORA
            fu = {h: x for h, x in ler_funding(m).items() if h >= corte}
            ini = max(fu) + 1 if fu else corte
            if agora - ini >= HORA:
                fu.update(baixar_funding(api, m, ini, agora))
            D.gravar_json(_arq("funding", m), {str(h): x for h, x in sorted(fu.items())})
        except Exception as e:  # noqa: BLE001
            log.append(f"preços: {m} falhou ({str(e)[:80]}); fica com o que já estava guardado")
        vs = sorted({v["t"]: v for v in vs}.values(), key=lambda v: v["t"])
        D.gravar_json(_arq("velas", m), [[v["t"], v["o"], v["h"], v["l"], v["c"]] for v in vs])
        velas[m] = vs
    return velas
