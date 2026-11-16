"""O mercado visto pela simulação: preços (velas da Hyperliquid), a posição de cada trader ao longo do tempo e as
contas de mentira que copiam. É a mesma mecânica da "cópia fiel" do radar-hyperliquid (lab/copia.py):

- cada mudança de posição do trader vira uma ordem do copiador, executada com atraso, no preço daquele minuto;
- o copiador segue em proporção da conta: se o trader põe 30 % do saldo vendido em ETH, a subconta põe 30 % do
  saldo dela (vezes o fator de alavancagem);
- paga a taxa de quem executa a mercado e um escorregamento por ordem;
- só os perpétuos da Hyperliquid (spot e mercados de terceiros têm saldo separado e ficam de fora);
- funding não entra na conta.

O atraso, a taxa e o escorregamento são do AMBIENTE (config.json), não do DNA: um robô não escolhe pagar menos.
"""
from __future__ import annotations

import bisect
import math

from . import MINUTO

LIMITE_1M = int(3.2 * 86_400_000)      # a Hyperliquid guarda ~5000 velas por intervalo: 1 min cobre ~3,4 dias


# ---------------------------------------------------------------- preços
class Precos:
    """Preço de cada moeda em qualquer instante, interpolando dentro da vela (abertura → fechamento)."""

    def __init__(self):
        self.v: dict[str, list[tuple[int, int, float, float]]] = {}   # moeda → [(t0, t1, abre, fecha)] em ordem
        self._t: dict[str, list[int]] = {}

    def juntar(self, moeda: str, velas: list[dict]) -> None:
        atual = {x[0]: x for x in self.v.get(moeda, [])}
        for c in velas or []:
            try:
                t0, t1 = int(c["t"]), int(c["T"])
                atual[t0] = (t0, t1, float(c["o"]), float(c["c"]))
            except (KeyError, TypeError, ValueError):
                continue
        limpa: list[tuple[int, int, float, float]] = []
        for x in sorted(atual.values()):
            # vela de 1 min por cima da de 5 min: tira as maiores que se sobrepõem às menores
            while limpa and limpa[-1][1] > x[0] and (limpa[-1][1] - limpa[-1][0]) > (x[1] - x[0]):
                limpa.pop()
            if limpa and limpa[-1][1] > x[0]:
                continue
            limpa.append(x)
        self.v[moeda] = limpa
        self._t[moeda] = [x[0] for x in limpa]

    def ultimo(self, moeda: str, t: int) -> float | None:
        """O último fechamento até `t`, mesmo velho (mercado encerrado): só para zerar uma posição que sobrou."""
        vs = self.v.get(moeda)
        if not vs:
            return None
        i = bisect.bisect_right(self._t[moeda], t) - 1
        return vs[i][3] if i >= 0 else None

    def em(self, moeda: str, t: int) -> float | None:
        vs = self.v.get(moeda)
        if not vs:
            return None
        i = bisect.bisect_right(self._t[moeda], t) - 1
        if i < 0:
            return None
        t0, t1, a, f = vs[i]
        if t >= t1:                                     # depois da vela (buraco ou fim): usa o fechamento
            if i + 1 < len(vs) or t - t1 < 10 * MINUTO:
                return f
            return None
        return a + (f - a) * (t - t0) / max(1, t1 - t0)


class PrecosVivos(Precos):
    """Busca as velas na Hyperliquid só das moedas que alguém pergunta, do instante pedido até `ate`."""

    def __init__(self, api, agora: int, ate: int):
        super().__init__()
        self.api, self.agora, self.ate = api, agora, ate
        self.cobre: dict[str, int] = {}                 # moeda → desde quando já temos velas
        self.falhas: dict[str, str] = {}

    def garantir(self, moeda: str, t: int) -> None:
        ini = self.cobre.get(moeda)
        if ini is not None and t >= ini:
            return
        de = t - 15 * MINUTO
        fim = self.ate if ini is None else ini
        pedacos = []
        if de < self.agora - LIMITE_1M:
            pedacos.append(("5m", de, min(fim, self.agora - LIMITE_1M + 3_600_000)))
        pedacos.append(("1m", max(de, self.agora - LIMITE_1M), fim))
        for intervalo, a, b in pedacos:
            if b <= a:
                continue
            try:
                self.juntar(moeda, self.api.velas(moeda, intervalo, a, b))
            except Exception as e:  # noqa: BLE001  (moeda sem velas ou a API não respondeu: fica sem preço)
                self.falhas[moeda] = str(e)[:120]
        self.cobre[moeda] = de

    def em(self, moeda: str, t: int) -> float | None:
        self.garantir(moeda, t)
        return super().em(moeda, t)

    def ultimo(self, moeda: str, t: int) -> float | None:
        self.garantir(moeda, t)
        return super().ultimo(moeda, t)


# ---------------------------------------------------------------- o trader copiado
def posicao_apos(f: dict) -> float:
    """Posição do trader na moeda depois do fill (sp = antes; B = compra)."""
    return float(f.get("sp", 0.0)) + (float(f["z"]) if f.get("s") == "B" else -float(f["z"]))


def copiavel_mercado(moeda: str) -> bool:
    """Só os perpétuos da Hyperliquid: spot ("@n", "A/B") e mercados de terceiros ("xyz:GOLD") ficam de fora."""
    return not (moeda.startswith("@") or "/" in moeda or ":" in moeda)


def _perto(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def em_ordem(fills: list[dict]) -> list[dict]:
    """Os fills de UMA moeda em ordem: por tempo e, no mesmo instante (a API não garante a ordem), seguindo a cadeia
    posição antes (sp) → posição depois."""
    fs = sorted(fills, key=lambda f: f["t"])
    out: list[dict] = []
    pos = None
    i = 0
    while i < len(fs):
        j = i
        while j < len(fs) and fs[j]["t"] == fs[i]["t"]:
            j += 1
        resto = fs[i:j]
        while resto:
            k = None
            if pos is not None:                       # continua a cadeia de onde parou
                k = next((n for n, f in enumerate(resto) if _perto(float(f.get("sp", 0.0)), pos)), None)
            if k is None:                             # começo da cadeia: o "antes" que não é o "depois" de outro fill
                depois = [posicao_apos(f) for f in resto]
                k = next((n for n, f in enumerate(resto)
                          if not any(_perto(float(f.get("sp", 0.0)), d) for m, d in enumerate(depois) if m != n)), 0)
            f = resto.pop(k)
            out.append(f)
            pos = posicao_apos(f)
        i = j
    return out


def parte_terceiros(fills: list[dict]) -> float:
    """Que fração dos fills em perpétuos foi em mercados de terceiros (HIP-3)."""
    perps = [f for f in fills if not (f["c"].startswith("@") or "/" in f["c"])]
    return sum(1 for f in perps if ":" in f["c"]) / len(perps) if perps else 0.0


def eventos(fills: list[dict], atraso_ms: int, fotos: list[dict] | None = None) -> list[dict]:
    """Junta os fills de cada moeda por minuto: o copiador olha a posição do trader e age `atraso` depois do último
    fill do minuto. Com as fotos da conta, uma posição que some sem fill de fechamento (mercado encerrado, ajuste da
    bolsa) vira um evento "zerou" na hora da foto.
    Volta [{t (do último fill), exec, moeda, pos, px}] em ordem de execução."""
    por_moeda: dict[str, list[dict]] = {}
    for f in fills:
        if "z" in f and copiavel_mercado(f["c"]):
            por_moeda.setdefault(f["c"], []).append(f)
    evs = []
    caminho: dict[str, tuple[list[int], list[float]]] = {}
    for moeda, fs in por_moeda.items():
        ordem = em_ordem(fs)
        caminho[moeda] = ([f["t"] for f in ordem], [posicao_apos(f) for f in ordem])
        ultimo: dict[int, dict] = {}
        for f in ordem:
            ultimo[f["t"] // MINUTO] = f              # na ordem da cadeia, o último do minuto fica
        for f in ultimo.values():
            evs.append({"t": f["t"], "moeda": moeda, "pos": posicao_apos(f), "px": float(f["p"]),
                        "exec": f["t"] + atraso_ms})
    zerado: dict[str, int] = {}
    for ft in sorted(fotos or [], key=lambda x: x["t"]):
        tem = {p[0] for p in ft.get("pos") or []}
        for moeda, (ts, ps) in caminho.items():
            i = bisect.bisect_right(ts, ft["t"]) - 1
            if i < 0 or moeda in tem or _perto(ps[i], 0.0) or zerado.get(moeda) == ts[i]:
                continue
            zerado[moeda] = ts[i]                     # um "zerou" por posição sumida
            evs.append({"t": ft["t"], "moeda": moeda, "pos": 0.0, "px": None, "exec": ft["t"] + atraso_ms})
    return sorted(evs, key=lambda e: (e["exec"], e["moeda"]))


class Saldos:
    """Saldo do trader ao longo do tempo (as fotos de cada coleta)."""

    def __init__(self, fotos: list[dict], reserva: float | None = None, minimo: float = 0.0):
        fs = sorted((f["t"], f["v"]) for f in fotos or [] if f.get("v", 0) > minimo)
        self.t = [x[0] for x in fs]
        self.v = [x[1] for x in fs]
        self.reserva = reserva                      # saldo de referência (o do ranking), para quem não tem foto com saldo

    def em(self, t: int) -> float | None:
        """O saldo da última foto com saldo até `t`; sem nenhuma, o de referência."""
        i = bisect.bisect_right(self.t, t) - 1
        return self.v[i] if i >= 0 else self.reserva


# ---------------------------------------------------------------- a subconta que copia UM trader
def nova_sub(w: str, inicio: int, capital: float, fator: float, teto: float) -> dict:
    return {"w": w, "inicio": inicio, "capital": capital, "base": capital, "colateral": capital, "pos": {},
            "pico": capital, "ult": inicio, "fator": fator, "teto": teto, "desde": {}, "travas": {}}


def patrimonio(sub: dict, precos: Precos, t: int) -> float:
    total = sub["colateral"]
    for m, (q, a) in sub["pos"].items():
        p = precos.em(m, t)
        if p is not None:
            total += q * (p - a)
    return total


def exposicao(sub: dict, precos: Precos, t: int, sem: str | None = None) -> float:
    s = 0.0
    for m, (q, a) in sub["pos"].items():
        if m == sem:
            continue
        s += abs(q) * (precos.em(m, t) or a)
    return s


def negociar(conta: dict, sub: dict, moeda: str, delta: float, preco: float, t: int, taxa: float) -> float:
    """Executa `delta` (com sinal) a `preco` (já com escorregamento): preço médio, lucro realizado e taxa.
    Devolve o resultado da ordem (realizado menos taxa)."""
    q, a = sub["pos"].get(moeda, (0.0, 0.0))
    custo = abs(delta) * preco * taxa
    realizado = 0.0
    if q == 0 or q * delta > 0:
        nq = q + delta
        na = (q * a + delta * preco) / nq if nq else 0.0
    else:
        fecha = min(abs(delta), abs(q))
        realizado = fecha * (preco - a) * (1 if q > 0 else -1)
        nq = q + delta
        if abs(nq) < 1e-12:
            nq, na = 0.0, 0.0
        elif nq * q < 0:                                  # virou de lado: o resto abre no preço de agora
            na = preco
        else:
            na = a
    sub["colateral"] += realizado - custo
    conta["taxas"] += custo
    conta["ordens"] += 1
    if nq == 0:
        sub["pos"].pop(moeda, None)
        sub["desde"].pop(moeda, None)
    else:
        if q == 0 or nq * q < 0:
            sub["desde"][moeda] = t                       # posição nova (ou virou de lado): o relógio começa aqui
        sub["pos"][moeda] = [nq, na]
    return realizado - custo


def fechar_posicao(conta: dict, sub: dict, moeda: str, precos: Precos, t: int, amb: dict) -> bool:
    q, a = sub["pos"].get(moeda, (0.0, 0.0))
    if not q:
        return False
    p = precos.em(moeda, t) or precos.ultimo(moeda, t) or a   # sem preço nenhum: sai no preço de entrada
    negociar(conta, sub, moeda, -q, p * (1 - amb["escorrega"] if q > 0 else 1 + amb["escorrega"]), t, amb["taxa"])
    return True


def aplicar(conta: dict, sub: dict, ev: dict, saldo_trader: float | None, precos: Precos, amb: dict,
            desvio_max: float) -> str | None:
    """Ajusta a subconta para a nova posição do trader. Volta None (ok) ou o motivo de ter pulado."""
    t, m = ev["exec"], ev["moeda"]
    q = sub["pos"].get(m, (0.0, 0.0))[0]
    trava = sub["travas"].get(m)
    if trava and (ev["pos"] == 0 or ev["pos"] * trava < 0):
        sub["travas"].pop(m, None)                        # o trader saiu (ou virou de lado): a moeda volta a valer
        trava = None
    if ev["pos"] == 0 and q == 0:
        return None
    if trava:
        return "saiu antes do trader"
    p = precos.em(m, t)
    if p is None and ev["pos"] == 0:
        p = precos.ultimo(m, t)                           # para zerar, serve o último preço conhecido
    if p is None:
        return "sem preço"
    if not saldo_trader or saldo_trader <= 0:
        return "sem saldo do trader"
    pat = patrimonio(sub, precos, t)
    if pat <= 0:
        return "subconta zerada"
    fracao = ev["pos"] * ev["px"] / saldo_trader if ev["pos"] else 0.0   # quanto do saldo dele está na moeda
    alvo_valor = fracao * sub["fator"] * pat
    custo = amb["taxa"] + amb["escorrega"]                # o teto já conta o que a própria ordem vai custar
    teto = sub["teto"] * pat / (1 + sub["teto"] * custo) - exposicao(sub, precos, t, sem=m)
    if abs(alvo_valor) > max(0.0, teto):
        alvo_valor = math.copysign(max(0.0, teto), alvo_valor)
    alvo = alvo_valor / p
    aumenta = abs(alvo) > abs(q) + 1e-12 or alvo * q < 0
    if aumenta and ev.get("px"):
        lado = 1 if alvo > 0 else -1
        if (p - ev["px"]) / ev["px"] * lado > desvio_max:  # o preço fugiu desde a ordem do trader: não corre atrás
            if alvo * q < 0:
                alvo = 0.0                                 # ele virou de lado: ao menos sai da posição antiga
            else:
                return "preço fugiu"
    delta = alvo - q
    if abs(delta) * p < amb["ordem_minima"] and not (alvo == 0 and q != 0):
        return "ordem pequena"
    preco = p * (1 + amb["escorrega"]) if delta > 0 else p * (1 - amb["escorrega"])
    negociar(conta, sub, m, delta, preco, t, amb["taxa"])
    return None
