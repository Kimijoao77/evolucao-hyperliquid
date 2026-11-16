"""Os cofres acompanhados: o índice de rendimento de cada um, guardado no ramo `estado` e completado de 6 em 6 horas.

dados/cofres/rodadas.json            os instantes em que os cofres foram lidos (a grade de tempo das contas)
dados/cofres/c/<endereço>.json        {"nome", "criado", "comissao", "hlp", "filho", "pts": [[t, índice]],
                                       "fichas": [[t, tvl, aceita depósito, fechado]]}

O índice só anda com o LUCRO do cofre (depósitos e saques não contam), como no laboratório de cofres do radar. Na
primeira vez que um cofre aparece, entra o histórico inteiro dele (é o passado que um robô pode olhar para escolher).
Daí em diante cada leitura só ACRESCENTA um ponto: o quanto o índice andou desde o último ponto guardado, medido na
série que a Hyperliquid devolve agora. O que já estava guardado nunca muda, então refazer a conta de um robô dá
sempre o mesmo passado.
"""
from __future__ import annotations

import bisect

from .. import DIA, HORA
from .. import dados as D

LISTA = "https://stats-data.hyperliquid.xyz/Mainnet/vaults"
HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"
CADA_H = 6                      # lê os cofres de 6 em 6 horas
ACOMPANHAR = 60                 # os maiores cofres (por dinheiro) que passam no pré-filtro
TVL_MINIMO = 100_000
IDADE_MINIMA_DIAS = 30


def pasta():
    return D.pasta() / "cofres"


def indice(portfolio, janela: str = "allTime") -> list[list[float]]:
    """[[t, índice]] a partir do histórico de saldo e de lucro: só anda com o lucro (depósito e saque não contam)."""
    jan = dict((k, v) for k, v in portfolio) if portfolio and isinstance(portfolio[0], list) else {}
    d = jan.get(janela) or {}
    av = [(int(t), float(x)) for t, x in d.get("accountValueHistory", [])]
    pnl = [(int(t), float(x)) for t, x in d.get("pnlHistory", [])]
    if len(av) < 2 or len(pnl) != len(av):
        return []
    out, idx = [[av[0][0], 1.0]], 1.0
    for i in range(1, len(av)):
        base = av[i - 1][1]
        if base > 0:
            idx *= 1 + max(-0.99, (pnl[i][1] - pnl[i - 1][1]) / base)
        out.append([av[i][0], idx])
    return out


def interpolar(serie: list[list[float]], t: int) -> float | None:
    ts = [p[0] for p in serie]
    j = bisect.bisect_right(ts, t)
    if j == 0:
        return None
    if j == len(serie):
        return serie[-1][1]
    (t0, a), (t1, b) = serie[j - 1], serie[j]
    return a + (b - a) * (t - t0) / (t1 - t0) if t1 > t0 else b


def andou(portfolio, desde: int) -> tuple[int, float] | None:
    """Quanto o índice andou de `desde` até o último ponto, na série mais fina que ainda cobre `desde`."""
    for jan in ("day", "week", "month", "allTime"):
        s = indice(portfolio, jan)
        if len(s) >= 2 and s[0][0] <= desde < s[-1][0]:
            a = interpolar(s, desde)
            if a and a > 0:
                return s[-1][0], s[-1][1] / a
    return None


def ler(cofre: str) -> dict | None:
    return D.ler_json(pasta() / "c" / f"{cofre}.json", None)


def todos() -> dict[str, dict]:
    out = {}
    for arq in sorted((pasta() / "c").glob("*.json")):
        c = D.ler_json(arq, None)
        if c:
            out[arq.stem] = c
    return out


def rodadas() -> list[int]:
    return D.ler_json(pasta() / "rodadas.json", [])


def atualizar(api, baixar_lista, agora: int, manter: set[str], log: list[str]) -> bool:
    """Lê a lista pública, escolhe quem acompanhar e acrescenta um ponto ao índice de cada um. Devolve True se leu."""
    rs = rodadas()
    if rs and agora - rs[-1] < CADA_H * HORA - 10 * 60 * 1000:
        return False
    lista = baixar_lista()
    resumo = {}
    for v in lista:
        s = v.get("summary") or {}
        end = (s.get("vaultAddress") or "").lower()
        if end:
            resumo[end] = s
    enderecos = set(resumo)
    cands = []
    for end, s in resumo.items():
        if s.get("isClosed") or float(s.get("tvl") or 0) < TVL_MINIMO:
            continue
        criado = int(s.get("createTimeMillis") or agora)
        if (agora - criado) / DIA < IDADE_MINIMA_DIAS:
            continue
        cands.append((float(s.get("tvl") or 0), end))
    cands.sort(reverse=True)
    alvo = [e for _, e in cands[:ACOMPANHAR]]
    guardados = todos()
    for e in [HLP, *sorted(manter), *sorted(guardados)]:        # quem já está guardado continua sendo lido
        if e not in alvo:
            alvo.append(e)
    lidos = 0
    for e in alvo:
        c = guardados.get(e)
        s = resumo.get(e) or {}
        if c and not s and agora - (c.get("fichas") or [[0]])[-1][0] > 30 * DIA:
            continue                                            # sumiu da lista há um mês: para de ler
        try:
            d = api._post({"type": "vaultDetails", "vaultAddress": e}, 20) or {}
        except Exception as ex:  # noqa: BLE001
            log.append(f"cofres: {e[:10]} falhou ({str(ex)[:60]})")
            continue
        port = d.get("portfolio") or []
        lider = (s.get("leader") or d.get("leader") or "").lower()
        if c is None:
            pts = [[int(t), round(x, 8)] for t, x in indice(port, "allTime")]
            if len(pts) < 2:
                continue
            c = {"nome": d.get("name") or s.get("name") or "", "criado": int(s.get("createTimeMillis") or pts[0][0]),
                 "hlp": e == HLP, "pts": pts, "fichas": []}
        else:
            a = andou(port, c["pts"][-1][0])
            if a and a[0] > c["pts"][-1][0]:
                c["pts"].append([a[0], round(c["pts"][-1][1] * a[1], 8)])
        c["comissao"] = 0.0 if e == HLP else float(d.get("leaderCommission") if d.get("leaderCommission") is not None else 0.10)
        c["filho"] = (d.get("relationship") or {}).get("type") == "child" or lider in enderecos
        c["fichas"].append([agora, round(float(s.get("tvl") or 0)), bool(d.get("allowDeposits", True)), bool(s.get("isClosed", False))])
        c["fichas"] = c["fichas"][-2000:]
        D.gravar_json(pasta() / "c" / f"{e}.json", c)
        lidos += 1
    rs.append(agora)
    D.gravar_json(pasta() / "rodadas.json", rs)
    log.append(f"cofres: {len(lista)} na lista, {len(cands)} passam no pré-filtro, {lidos} lidos")
    return True
