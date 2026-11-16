"""As moedas novas da Hyperliquid: a estreia de cada uma, as velas de 1 hora e o funding das primeiras semanas.

dados/listagens/conhecidas.json   {"<moeda>": {"visto": t, "estreia": t ou null, "alav_max": n, "fora": bool}}
dados/listagens/m/<moeda>.json     {"estreia", "alav_max", "fora", "velas": [[t, o, h, l, c]], "funding": {"<hora>": taxa}}

Só as moedas que estrearam a partir de 15 dias antes do começo do teste interessam (um robô espera no máximo 14 dias
para vender). As velas e o funding são guardados até 46 dias depois da estreia (14 de espera + 30 de prazo + folga).
"""
from __future__ import annotations

import math

from .. import DIA, HORA
from .. import dados as D

JANELA_H = 46 * 24
ULTIMAS = 40                     # na primeira vez, confere a estreia das 40 últimas moedas da lista


def pasta():
    return D.pasta() / "listagens"


def estreia_de(funding: list[dict]) -> int | None:
    """A hora da estreia: o primeiro funding é pago no fim da primeira hora cheia de negociação."""
    ts = [int(f["time"]) for f in funding or [] if f.get("time") is not None]
    return (min(ts) // HORA - 1) * HORA if ts else None


def _funding(api, moeda: str, desde: int, ate: int) -> dict[int, float]:
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


def ler(moeda: str) -> dict | None:
    return D.ler_json(pasta() / "m" / f"{moeda}.json", None)


def todas() -> dict[str, dict]:
    out = {}
    for arq in sorted((pasta() / "m").glob("*.json")):
        m = D.ler_json(arq, None)
        if m:
            m["velas"] = [{"t": int(v[0]), "o": v[1], "h": v[2], "l": v[3], "c": v[4]} for v in m.get("velas", [])]
            m["funding"] = {int(h): float(x) for h, x in (m.get("funding") or {}).items()}
            out[arq.stem] = m
    return out


def atualizar(api, agora: int, inicio: int, log: list[str]) -> None:
    con = D.ler_json(pasta() / "conhecidas.json", {})
    primeira = not con
    univ = (api._post({"type": "meta"}, 20) or {}).get("universe", [])
    nomes = [m["name"] for m in univ]
    novas = 0
    for i, m in enumerate(univ):
        n = m["name"]
        c = con.get(n)
        if c is None:
            c = con[n] = {"visto": agora, "estreia": None}
            if not primeira or i >= len(univ) - ULTIMAS:      # moeda nova (ou, na primeira vez, das últimas da lista)
                try:
                    c["estreia"] = estreia_de(api._post({"type": "fundingHistory", "coin": n, "startTime": 0}, 20) or [])
                except Exception as e:  # noqa: BLE001
                    log.append(f"moedas novas: {n} falhou ({str(e)[:60]})")
                    del con[n]
                    continue
                novas += 1
        c["alav_max"] = m.get("maxLeverage", 3)
        c["fora"] = bool(m.get("isDelisted"))
    for n, c in con.items():
        if n not in nomes:
            c["fora"] = True
    D.gravar_json(pasta() / "conhecidas.json", con)
    for n, c in con.items():
        e = c.get("estreia")
        if not e or e < inicio - 15 * DIA or e > agora:
            continue
        arq = pasta() / "m" / f"{n}.json"
        d = D.ler_json(arq, None) or {"estreia": e, "velas": [], "funding": {}}
        d["alav_max"], d["fora"] = c.get("alav_max", 3), c.get("fora", False)
        fim = min(agora, e + JANELA_H * HORA)
        de = d["velas"][-1][0] + HORA if d["velas"] else e
        if de + HORA > fim:
            D.gravar_json(arq, d)
            continue
        try:
            vs = api.velas(n, "1h", de, fim)
            d["velas"] += [[int(v["t"]), float(v["o"]), float(v["h"]), float(v["l"]), float(v["c"])]
                           for v in vs if int(v["t"]) >= de and int(v["t"]) + HORA <= agora]
            fu = {int(h): x for h, x in d["funding"].items()}
            fu.update(_funding(api, n, max(fu) + 1 if fu else e, fim))
            d["funding"] = {str(h): x for h, x in sorted(fu.items())}
        except Exception as ex:  # noqa: BLE001
            log.append(f"moedas novas: velas de {n} falharam ({str(ex)[:60]})")
        D.gravar_json(arq, d)
    log.append(f"moedas novas: {len(univ)} moedas na Hyperliquid, {novas} estreias conferidas agora")
