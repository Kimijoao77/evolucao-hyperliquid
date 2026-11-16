"""As pools acompanhadas (Meteora DLMM, Solana): uma foto de cada uma a cada rodada e as velas de 5 minutos.

dados/pools/rodadas.json        [[t, [endereços elegíveis nesta rodada]], ...]
dados/pools/p/<endereço>.json    {"nome", "x" (endereço da moeda), "y" (SOL/USDC), "bin_step",
                                  "fotos": [[t, preço, taxa_1h, taxa_24h, tvl, volume_24h, taxa_pct, preço_y]],
                                  "h1": [[t, fechamento]] (as 26 velas de 1 h de antes da primeira foto),
                                  "m5": [[t, fechamento]] (velas de 5 min, preço da moeda em SOL/USDC)}

A cada rodada (de 2 em 2 horas) entram as 12 pools elegíveis de maior taxa sobre o dinheiro nas últimas 24 h (SOL ou
USDC do outro lado, US$ 10 mil ou mais, US$ 50 mil de volume) e continuam sendo seguidas por 4 dias as que já
estavam (uma posição dura no máximo 96 h). Fonte: a API pública da Meteora e as velas do GeckoTerminal.
"""
from __future__ import annotations

import time

import requests

from .. import DIA, HORA, MINUTO
from .. import dados as D
from .conta import num

API = "https://dlmm.datapi.meteora.ag"
GT = "https://api.geckoterminal.com/api/v2"
QUOTES = {"SOL", "USDC"}
TVL_MIN, VOLUME_MIN = 10_000, 50_000
NOVAS = 12
SEGUIR_DIAS = 4
CADA_MIN = 100

S = requests.Session()
S.headers["User-Agent"] = "evolucao-hyperliquid/1.0"


class Gecko:
    """GeckoTerminal sem chave: uma chamada a cada 4,5 s; com 429 (limite), espera e tenta de novo."""

    def __init__(self, intervalo: float = 4.5, limite_espera: float = 120):
        self.intervalo, self.limite_espera = intervalo, limite_espera
        self.ultima, self.esperou = -1e9, 0.0

    def get(self, caminho: str, **params):
        for tentativa in range(4):
            espera = self.intervalo - (time.monotonic() - self.ultima)
            if espera > 0:
                time.sleep(espera)
            self.ultima = time.monotonic()
            r = S.get(GT + caminho, params=params, timeout=30)
            if r.status_code == 429:
                if self.esperou >= self.limite_espera:
                    break
                self.esperou += 15 * (tentativa + 1)
                time.sleep(15 * (tentativa + 1))
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        raise RuntimeError("GeckoTerminal: limite de chamadas")


def meteora(caminho: str, **params):
    r = S.get(API + caminho, params=params, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def pasta():
    return D.pasta() / "pools"


def rodadas() -> list:
    return D.ler_json(pasta() / "rodadas.json", [])


def todas() -> dict[str, dict]:
    out = {}
    for arq in sorted((pasta() / "p").glob("*.json")):
        p = D.ler_json(arq, None)
        if p:
            out[arq.stem] = p
    return out


def elegiveis(lista: list[dict]) -> list[dict]:
    out = []
    for p in lista:
        y = (p.get("token_y") or {}).get("symbol", "").upper()
        if p.get("is_blacklisted") or y not in QUOTES or num(p.get("tvl")) < TVL_MIN or num((p.get("volume") or {}).get("24h")) < VOLUME_MIN:
            continue
        if num(p.get("current_price")) <= 0 or num((p.get("token_y") or {}).get("price")) <= 0:
            continue
        out.append(p)
    return sorted(out, key=lambda p: -num((p.get("fee_tvl_ratio") or {}).get("24h")))


def _ohlcv(g, addr: str, x: str, tipo: str, limite: int, agregar: int) -> list[list]:
    j = g.get(f"/networks/solana/pools/{addr}/ohlcv/{tipo}", aggregate=agregar, limit=limite, currency="token", token=x)
    vs = (((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    return sorted([[int(v[0]) * 1000 if v[0] < 1e12 else int(v[0]), float(v[4])] for v in vs])


def atualizar(agora: int, desde: int, log: list[str], buscar=meteora, gecko=None) -> bool:
    rs = rodadas()
    if rs and agora - rs[-1][0] < CADA_MIN * MINUTO:
        return False
    g = gecko or Gecko()
    filtro = f"is_blacklisted=false && tvl>={TVL_MIN} && volume_24h>={VOLUME_MIN}"
    lista = (buscar("/pools", page=1, page_size=100, sort_by="fee_tvl_ratio_24h:desc", filter_by=filtro) or {}).get("data") or []
    ele = elegiveis(lista)
    por_end = {p["address"]: p for p in lista}
    guardadas = todas()
    seguir = [p["address"] for p in ele[:NOVAS]]
    seguir += [a for a, p in guardadas.items() if a not in seguir and p.get("fotos") and agora - p["fotos"][-1][0] < SEGUIR_DIAS * DIA
               and p.get("desde", 0) and agora - p.get("desde", 0) < 30 * DIA]
    lidas = 0
    for a in seguir:
        p = guardadas.get(a)
        pool = por_end.get(a)
        try:
            if pool is None:
                pool = buscar(f"/pools/{a}") or {}
            if not pool:
                continue
            if p is None:
                x = pool["token_x"]["address"]
                p = {"nome": pool.get("name", ""), "x": x, "y": (pool.get("token_y") or {}).get("symbol", ""), "desde": agora,
                     "bin_step": num((pool.get("pool_config") or {}).get("bin_step") or pool.get("bin_step")),
                     "fotos": [], "h1": _ohlcv(g, a, x, "hour", 26, 1), "m5": _ohlcv(g, a, x, "minute", 30, 5)}
            else:
                ult = p["m5"][-1][0] if p["m5"] else agora - 2 * HORA
                n = max(2, min(300, int((agora - ult) / (5 * MINUTO)) + 2))
                novas = _ohlcv(g, a, p["x"], "minute", n, 5)
                p["m5"] += [v for v in novas if v[0] > ult and v[0] + 5 * MINUTO <= agora]
        except Exception as e:  # noqa: BLE001
            log.append(f"pools: {(pool or {}).get('name', a[:8])} falhou ({str(e)[:60]})")
            if p is None:
                continue
        p["fotos"].append([agora, num(pool.get("current_price")), num((pool.get("fee_tvl_ratio") or {}).get("1h")),
                           num((pool.get("fee_tvl_ratio") or {}).get("24h")), round(num(pool.get("tvl"))),
                           round(num((pool.get("volume") or {}).get("24h"))),
                           num(pool.get("dynamic_fee_pct") or (pool.get("pool_config") or {}).get("base_fee_pct")),
                           num((pool.get("token_y") or {}).get("price"))])
        corte = desde - 2 * DIA
        p["m5"] = [v for v in p["m5"] if v[0] >= corte]
        D.gravar_json(pasta() / "p" / f"{a}.json", p)
        lidas += 1
    rs.append([agora, [p["address"] for p in ele[:NOVAS]]])
    D.gravar_json(pasta() / "rodadas.json", rs)
    log.append(f"pools: {len(lista)} na lista, {len(ele)} elegíveis, {lidas} lidas")
    return True
