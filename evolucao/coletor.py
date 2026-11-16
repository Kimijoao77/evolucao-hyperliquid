"""O universo de traders e a coleta (só consulta à API pública da Hyperliquid).

O radar-hyperliquid acompanha poucas carteiras, já aprovadas por ele. Para a evolução ter o que escolher, este
coletor mantém um universo próprio e mais largo (até 120):

1. Uma vez por semana monta a fila de entrada: primeiro as carteiras do radar (lidas do relatório público dele),
   depois um sorteio entre as que passam num pré-filtro do ranking da Hyperliquid (conta, volume e ROI do mês).
   Sorteio, e não "as melhores": quem decide quem presta são os robôs, com as fichas.
2. A cada rodada baixa os fills novos e tira uma foto do saldo de cada carteira ativa.
3. Com o tempo que sobrar, traz as da fila: 90 dias de histórico de cada uma (o passado do TRADER, que os robôs usam
   para escolher; o resultado dos ROBÔS só conta daqui para a frente).

Quem para de operar por 30 dias ou fica com a conta quase zerada sai da coleta, mas continua registrado: trader que
quebrou faz parte da história.
"""
from __future__ import annotations

import random
import time

from . import DIA
from . import dados as D
from .mercado import parte_terceiros

SEMANA = 7 * DIA


def _janelas(linha: dict) -> dict:
    return {nome: {k: float(v.get(k) or 0) for k in ("pnl", "roi", "vlm")}
            for nome, v in linha.get("windowPerformances") or []}


def passa(linha: dict, f: dict) -> bool:
    """Pré-filtro com o que o ranking já traz (sem gastar consultas)."""
    conta = float(linha.get("accountValue") or 0)
    j = _janelas(linha)
    mes, tot = j.get("month", {}), j.get("allTime", {})
    if conta < f["conta_minima"] or mes.get("vlm", 0) < f["volume_mes_minimo"]:
        return False
    if not (f["roi_mes_minimo"] <= mes.get("roi", 0) <= f["roi_mes_maximo"]):
        return False
    return not (f.get("exigir_pnl_total_positivo") and tot.get("pnl", 0) <= 0)


def curto(a: str) -> str:
    return f"{a[:6]}…{a[-4:]}"


def montar_fila(uni: dict, linhas: list[dict], do_radar: list[dict], cfg: dict, agora: int) -> list[dict]:
    """A fila da semana: as do radar na frente, depois um sorteio entre as que passam no pré-filtro."""
    cart = uni["carteiras"]
    volta = cfg.get("dias_para_testar_de_novo", 30) * DIA

    def livre(a: str) -> bool:
        c = cart.get(a)
        return not c or (c["situacao"] != "ativa" and agora - c.get("em", 0) > volta)

    fila, visto = [], set()
    for c in do_radar:
        a = (c.get("carteira") or "").lower()
        if a and a not in visto and livre(a):
            visto.add(a)
            fila.append({"a": a, "apelido": c.get("apelido") or "", "origem": "radar"})
    ok = sorted((l for l in linhas if passa(l, cfg["filtro"])), key=lambda l: l["ethAddress"].lower())
    random.Random(f"fila-{agora // SEMANA}").shuffle(ok)
    ativas = sum(1 for c in cart.values() if c["situacao"] == "ativa")
    quantas = len(fila) + 2 * max(0, cfg["max_carteiras"] - ativas - len(fila))   # o dobro: várias são recusadas
    for l in ok:
        if len(fila) >= quantas:
            break
        a = l["ethAddress"].lower()
        if a not in visto and livre(a):
            visto.add(a)
            fila.append({"a": a, "apelido": l.get("displayName") or "", "origem": "ranking"})
    nomes = {l["ethAddress"].lower(): l.get("displayName") for l in linhas if l.get("displayName")}
    for a, c in cart.items():                             # o apelido pode mudar
        if nomes.get(a):
            c["apelido"] = nomes[a]
    return fila


def foto(api, a: str, agora: int) -> float:
    st = api.estado(a)
    ms = st.get("marginSummary") or {}
    pos = []
    for p in st.get("assetPositions") or []:
        q = p.get("position") or {}
        if float(q.get("szi") or 0):
            pos.append([q.get("coin"), float(q["szi"]), float(q.get("entryPx") or 0)])
    v = round(float(ms.get("accountValue") or 0), 2)
    D.anexar_foto({"t": agora, "a": a, "v": v, "ntl": round(float(ms.get("totalNtlPos") or 0), 2), "pos": pos})
    return v


def trazer(api, item: dict, cfg: dict, agora: int) -> dict:
    """Uma carteira da fila: baixa o histórico e decide se entra no universo."""
    a = item["a"]
    fills = [D.compactar(f) for f in api.fills_desde(a, agora - cfg["dias_de_historico"] * DIA)]
    base = {"apelido": item.get("apelido", ""), "origem": item["origem"], "em": agora}
    if not fills:
        return {**base, "situacao": "recusada", "motivo": "sem operações em 90 dias"}
    dias = max(1.0, (agora - fills[0]["t"]) / DIA)
    if len(fills) / dias > cfg["max_fills_por_dia"]:
        return {**base, "situacao": "recusada", "motivo": f"{len(fills) / dias:.0f} execuções por dia: rápida demais para copiar"}
    if parte_terceiros(fills) > 0.8:
        return {**base, "situacao": "recusada", "motivo": "quase tudo em mercados de terceiros"}
    D.anexar_fills(a, fills)
    v = foto(api, a, agora)
    return {**base, "situacao": "ativa", "entrou": agora, "ultimo_t": fills[-1]["t"], "coletado_em": agora, "conta": v}


def coletar(cfg_todo: dict, api, agora: int, limite_min: float = 12.0, ler_radar=None) -> dict:
    cfg = cfg_todo["universo"]
    inicio = time.monotonic()
    tempo = lambda: time.monotonic() - inicio < limite_min * 60  # noqa: E731
    arq = D.pasta() / "universo.json"
    uni = D.ler_json(arq, {})
    uni.setdefault("carteiras", {})
    uni.setdefault("fila", [])
    cart = uni["carteiras"]
    log = []

    # 1. a fila da semana
    if agora - uni.get("fila_em", 0) >= SEMANA:
        try:
            do_radar = (ler_radar() if ler_radar else {}).get("carteiras", [])
        except Exception as e:  # noqa: BLE001
            do_radar = []
            log.append(f"não li o relatório do radar: {str(e)[:100]}")
        try:
            uni["fila"] = montar_fila(uni, api.leaderboard(), do_radar, cfg, agora)
            uni["fila_em"] = agora
            log.append(f"fila da semana: {len(uni['fila'])} carteiras ({sum(1 for x in uni['fila'] if x['origem'] == 'radar')} do radar)")
        except Exception as e:  # noqa: BLE001
            log.append(f"o ranking não respondeu: {str(e)[:100]}")

    # 2. fills e fotos das ativas (primeiro as que estão há mais tempo sem coleta)
    feitas = erros = novos = 0
    for a in sorted((a for a, c in cart.items() if c["situacao"] == "ativa"), key=lambda a: cart[a].get("coletado_em", 0)):
        if not tempo():
            log.append("tempo esgotado na coleta: o resto fica para a próxima rodada")
            break
        c = cart[a]
        try:
            fills = [D.compactar(f) for f in api.fills_desde(a, c.get("ultimo_t", agora - DIA) + 1)]
            novos += D.anexar_fills(a, fills)
            if fills:
                c["ultimo_t"] = max(f["t"] for f in fills)
            c["conta"] = foto(api, a, agora)
            c["coletado_em"] = agora
            c.pop("erro", None)
            feitas += 1
        except Exception as e:  # noqa: BLE001
            erros += 1
            c["erro"] = str(e)[:160]
            continue
        if agora - c.get("ultimo_t", agora) > cfg["dias_sem_operar_para_sair"] * DIA:
            c.update(situacao="parada", em=agora, motivo=f"sem operar há {cfg['dias_sem_operar_para_sair']} dias")
        elif c["conta"] < cfg["conta_minima_para_ficar"]:
            c.update(situacao="quebrou", em=agora, motivo=f"a conta caiu para US$ {c['conta']:.0f}")

    # 3. as da fila, enquanto houver tempo e vaga
    entraram = recusadas = 0
    while uni["fila"] and tempo() and entraram < cfg["entram_por_rodada"]:
        if sum(1 for c in cart.values() if c["situacao"] == "ativa") >= cfg["max_carteiras"]:
            break
        item = uni["fila"].pop(0)
        try:
            c = trazer(api, item, cfg, agora)
        except Exception as e:  # noqa: BLE001
            log.append(f"não trouxe {curto(item['a'])}: {str(e)[:100]}")
            continue
        cart[item["a"]] = c
        if c["situacao"] == "ativa":
            entraram += 1
        else:
            recusadas += 1

    apagados = D.podar(agora, cfg["dias_guardados"])
    ativas = sum(1 for c in cart.values() if c["situacao"] == "ativa")
    uni["ultima"] = {"em": agora, "ativas": ativas, "coletadas": feitas, "erros": erros, "fills_novos": novos,
                     "entraram": entraram, "recusadas": recusadas, "fila": len(uni["fila"]),
                     "peso": getattr(getattr(api, "lim", None), "total", None),
                     "minutos": round((time.monotonic() - inicio) / 60, 1)}
    D.gravar_json(arq, uni, compacto=False)
    log.append(f"coleta: {ativas} ativas, {feitas} coletadas, {novos} fills novos, {erros} erros; entraram {entraram}, "
               f"recusadas {recusadas}, fila {len(uni['fila'])}" + (f"; {apagados} arquivos velhos apagados" if apagados else ""))
    return {"log": log, **uni["ultima"]}
