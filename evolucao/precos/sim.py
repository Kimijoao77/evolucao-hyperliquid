"""Os simuladores dos robôs de preço, com as velas de 1 hora da Hyperliquid (vindos do laboratório de grade do
radar-hyperliquid, lab/grade.py, com duas mudanças: os custos viram parâmetro, para a conta gêmea de estresse, e cada
simulação devolve a curva hora a hora inteira).

Grade: divide uma faixa de preço (em volta do preço do começo) em N degraus; compra embaixo e vende no degrau de cima.
DCA: compra um pouco; se cair, compra mais (cada compra maior); vende tudo quando passa do alvo acima do preço médio.
Tendência: comprado na alta, vendido na queda, sempre no mercado (cruzamento de médias ou rompimento de canal).
Reversão: compra depois de uma queda forte em 24 h (e, com "ambos", vende depois de uma alta forte); sai no repique.

Em cada vela o caminho do preço dentro da hora não é conhecido: a conta é conservadora (nunca compra e vende o mesmo
degrau na mesma hora; se a parada e o alvo cabem na mesma vela, conta a parada). Funding real da Hyperliquid.
"""
from __future__ import annotations

from collections import deque

HORA = 3600 * 1000
ANO_H = 24 * 365
MAKER, TAKER = 0.00015, 0.00045
SLIP = 0.0002                                             # derrapagem de uma ordem a mercado (valores pequenos em moedas grandes)
CUSTO = {"maker": MAKER, "taker": TAKER, "slip": SLIP}


def _custos(custo: dict | None) -> tuple[float, float, float]:
    c = custo or CUSTO
    return c["maker"], c["taker"], c["slip"]
BANDA = 0.002                                             # cruzamento de médias: só vira quando a curta passa 0,2 % da longa


def _queda(curva: list[float]) -> float:
    pico, pior = 0.0, 0.0
    for v in curva:
        pico = max(pico, v)
        if pico > 0:
            pior = max(pior, (pico - v) / pico)
    return pior


def _taxas(velas: list[dict], funding: dict | None) -> list[float] | None:
    """Taxa de funding paga no fim de cada vela (a Hyperliquid paga de hora em hora), alinhada com as velas.
    funding: {hora_em_ms: taxa por hora}. Hora sem dado repete a última taxa conhecida (0 se ainda não houve nenhuma)."""
    if not funding:
        return None
    out, ult = [], 0.0
    for v in velas:
        ult = funding.get(int(v["t"]) + HORA, ult)
        out.append(float(ult))
    return out


def grade(velas: list[dict], faixa: float, niveis: int, alav: float = 1.0, capital: float = 1000.0, ops: list | None = None,
          funding: dict | None = None, custo: dict | None = None) -> dict:
    """Grade "neutra" de compra: faixa ±faixa em volta do preço de abertura da primeira vela."""
    MAKER, TAKER, SLIP = _custos(custo)
    p0 = float(velas[0]["o"])
    baixo, alto = p0 * (1 - faixa), p0 * (1 + faixa)
    L = [baixo + (alto - baixo) * i / niveis for i in range(niveis + 1)]
    qtd = capital * alav / niveis / p0                        # mesma quantidade em cada degrau
    caixa, moeda = capital, 0.0
    segura = []                                               # por degrau i (L[i] → L[i+1]): comprado?
    for i in range(niveis):
        if L[i + 1] > p0:                                     # degraus acima do preço: já compra no começo
            caixa -= qtd * p0 * (1 + TAKER)
            moeda += qtd
            segura.append(True)
        else:
            segura.append(False)
    if ops is not None and any(segura):
        n0 = sum(segura)
        ops.append({"t": int(velas[0]["t"]), "tipo": "compra", "px": p0, "valor": round(qtd * p0 * n0, 2), "obs": f"{n0} degraus de começo"})
    ciclos, lucro_grade, fora, liquidada = 0, 0.0, 0, False
    curva, ts = [], []
    tx, pago = _taxas(velas, funding), 0.0
    for k, v in enumerate(velas):
        lo, hi, c = float(v["l"]), float(v["h"]), float(v["c"])
        vendeu = set()
        for i in range(niveis):                               # vendas primeiro (degraus comprados)
            if segura[i] and hi >= L[i + 1]:
                caixa += qtd * L[i + 1] * (1 - MAKER)
                moeda -= qtd
                segura[i] = False
                vendeu.add(i)
                ciclos += 1
                lucro_grade += qtd * (L[i + 1] - L[i])
                if ops is not None:
                    ops.append({"t": int(v["t"]), "tipo": "venda", "px": L[i + 1], "valor": round(qtd * L[i + 1], 2), "lucro": round(qtd * (L[i + 1] - L[i]) - qtd * (L[i] + L[i + 1]) * MAKER, 2)})
        for i in range(niveis):                               # depois as compras (não no degrau que acabou de vender)
            if not segura[i] and i not in vendeu and lo <= L[i]:
                caixa -= qtd * L[i] * (1 + MAKER)
                moeda += qtd
                segura[i] = True
                if ops is not None:
                    ops.append({"t": int(v["t"]), "tipo": "compra", "px": L[i], "valor": round(qtd * L[i], 2)})
        if c < baixo or c > alto:
            fora += 1
        if tx is not None and moeda > 0:                      # funding: quem está comprado paga (a taxa é sobre o valor da posição)
            pg = moeda * c * tx[k]
            caixa -= pg
            pago += pg
        patrimonio = caixa + moeda * c
        if alav > 1 and patrimonio <= capital * 0.05:          # com alavancagem: a margem acabou
            liquidada, patrimonio = True, 0.0
            curva.append(0.0); ts.append(int(v["t"]))
            break
        curva.append(patrimonio); ts.append(int(v["t"]))
    return _resumo(velas, curva, ts, capital, {"ciclos": ciclos, "lucro_dos_degraus": round(lucro_grade, 2),
                                               "fora_da_faixa": round(fora / max(1, len(curva)), 3), "liquidada": liquidada,
                                               "funding_pago": round(pago, 2)})


def dca(velas: list[dict], passo: float, alvo: float, ordens: int = 5, escala: float = 1.5, alav: float = 1.0, capital: float = 1000.0,
        ops: list | None = None, media_h: int = 0, historico: list[float] | None = None, funding: dict | None = None, custo: dict | None = None) -> dict:
    """Robô de DCA comprado: 1 compra base + até `ordens` compras de segurança a cada `passo` de queda; vende com `alvo` de lucro.
    media_h > 0: pausa na tendência de queda — só abre um ciclo novo se o último fechamento estiver acima da média das
    últimas `media_h` horas (o ciclo já aberto segue normal). `historico`: fechamentos de antes, para a média já valer."""
    MAKER, TAKER, SLIP = _custos(custo)
    pesos = [escala ** k for k in range(ordens + 1)]
    base = capital * alav / sum(pesos)
    caixa, qtd, gasto, n_comp = capital, 0.0, 0.0, 0
    p_ent = None
    ciclos, horas_presas, maior_preso, preso_desde = 0, 0, 0, None
    liquidada = False
    curva, ts = [], []
    fechados = list(historico or [])[-media_h:] if media_h else []
    soma, pausadas = sum(fechados), 0
    tx, pago = _taxas(velas, funding), 0.0
    for k, v in enumerate(velas):
        lo, hi, c, t = float(v["l"]), float(v["h"]), float(v["c"]), int(v["t"])
        if qtd == 0 and media_h and len(fechados) >= media_h and fechados[-1] < soma / media_h:
            pausadas += 1                                     # tendência de queda: fica no caixa nesta hora
            curva.append(caixa); ts.append(t)
            fechados.append(c); soma += c - fechados.pop(0)
            continue
        if qtd == 0:                                          # abre um ciclo na abertura da vela
            p_ent = float(v["o"])
            q = base / p_ent
            caixa -= q * p_ent / alav + q * p_ent * TAKER
            qtd, gasto, n_comp = q, q * p_ent, 1
            preso_desde = t
            if ops is not None:
                ops.append({"t": t, "tipo": "compra", "px": p_ent, "valor": round(q * p_ent, 2), "obs": "compra base"})
        # compras de segurança
        while n_comp <= ordens and lo <= p_ent * (1 - passo * n_comp):
            px = p_ent * (1 - passo * n_comp)
            q = base * pesos[n_comp] / px
            caixa -= q * px / alav + q * px * MAKER
            qtd += q; gasto += q * px; n_comp += 1
            if ops is not None:
                ops.append({"t": t, "tipo": "compra", "px": px, "valor": round(q * px, 2), "obs": f"compra de segurança {n_comp - 1}"})
        medio = gasto / qtd
        if hi >= medio * (1 + alvo):                          # alvo: vende tudo
            px = medio * (1 + alvo)
            receita = qtd * px * (1 - MAKER)
            caixa += gasto / alav + (receita - gasto)
            ciclos += 1
            if ops is not None:
                ops.append({"t": t, "tipo": "venda", "px": px, "valor": round(receita, 2), "lucro": round(receita - gasto, 2), "obs": "alvo atingido"})
            maior_preso = max(maior_preso, (t - preso_desde) / HORA)
            qtd = gasto = 0.0
            n_comp = 0
            patrimonio = caixa
        else:
            horas_presas += 1
            if tx is not None:                                # funding: a posição comprada paga a taxa sobre o valor dela
                pg = qtd * c * tx[k]
                caixa -= pg
                pago += pg
            aberto = (qtd * c - gasto)                        # ganho ou perda da posição aberta
            patrimonio = caixa + gasto / alav + aberto
            if alav > 1 and patrimonio <= capital * 0.05:
                liquidada, patrimonio = True, 0.0
                curva.append(0.0); ts.append(t)
                break
        curva.append(patrimonio); ts.append(t)
        if media_h:
            fechados.append(c); soma += c
            if len(fechados) > media_h:
                soma -= fechados.pop(0)
    if qtd and preso_desde:
        maior_preso = max(maior_preso, (ts[-1] - preso_desde) / HORA)
    return _resumo(velas, curva, ts, capital, {"ciclos": ciclos, "horas_com_posicao": round(horas_presas / max(1, len(curva)), 3),
                                               "maior_tempo_preso_h": round(maior_preso), "liquidada": liquidada,
                                               "horas_pausado": round(pausadas / max(1, len(curva)), 3), "funding_pago": round(pago, 2)})


def _ema(valores: list[float], n: int) -> list[float]:
    """Média móvel exponencial de n horas (começa no primeiro valor)."""
    k, out, e = 2 / (n + 1), [], None
    for x in valores:
        e = x if e is None else e + k * (x - e)
        out.append(e)
    return out


def _janela(valores: list[float], n: int, maior: bool) -> list[float | None]:
    """Para cada posição i, o maior (ou o menor) dos n valores ANTES dela; None enquanto não há n valores."""
    out, fila = [], deque()
    for i, x in enumerate(valores):
        while fila and fila[0] < i - n:
            fila.popleft()
        out.append(valores[fila[0]] if fila and i >= n else None)
        while fila and (valores[fila[-1]] <= x if maior else valores[fila[-1]] >= x):
            fila.pop()
        fila.append(i)
    return out


def tendencia(velas: list[dict], modo: str, a: int, b: int | None = None, alav: float = 1.0, capital: float = 1000.0,
              ops: list | None = None, antes: list[dict] | None = None, funding: dict | None = None, custo: dict | None = None) -> dict:
    """Robô de tendência, comprado ou vendido, sempre no mercado.
    modo "medias": comprado se a média de `a` horas está acima da de `b` horas (vendido se abaixo), com uma faixa de 0,2 %.
    modo "rompe": comprado quando o fechamento passa da máxima das últimas `a` horas; vendido quando passa da mínima.
    A decisão sai no fechamento de uma vela e vale na abertura da próxima. `antes`: velas de antes do começo, para as
    médias e os canais já valerem. Liquidada se, no pior ponto da vela, sobrar menos de 5 % do capital."""
    MAKER, TAKER, SLIP = _custos(custo)
    antes = list(antes or [])
    todas = antes + list(velas)
    n0 = len(antes)
    fech = [float(v["c"]) for v in todas]
    if modo == "medias":
        rapida, lenta = _ema(fech, a), _ema(fech, b)
        pronto = b                                            # as médias precisam de ~b horas para fazer sentido
    else:
        topo, fundo = _janela([float(v["h"]) for v in todas], a, True), _janela([float(v["l"]) for v in todas], a, False)
        pronto = a
    tx, pago = _taxas(velas, funding), 0.0
    real, q, pe, pos, alvo = capital, 0.0, 0.0, 0, 0          # real = dinheiro sem a posição aberta; q = unidades (negativo = vendido)
    trocas, horas_pos, horas_comp, liquidada = 0, 0, 0, False
    curva, ts = [], []
    for k, v in enumerate(velas):
        i = n0 + k
        o, hi, lo, c, t = float(v["o"]), float(v["h"]), float(v["l"]), float(v["c"]), int(v["t"])
        if alvo != pos:                                       # a decisão do fechamento anterior vale na abertura desta vela
            if pos:
                lucro = q * (o - pe) - abs(q) * o * (TAKER + SLIP)
                real += lucro
                if ops is not None:
                    ops.append({"t": t, "tipo": "venda" if q > 0 else "compra", "px": o, "valor": round(abs(q) * o, 2),
                                "lucro": round(lucro, 2), "obs": "fecha a posição comprada" if q > 0 else "fecha a posição vendida"})
                q, pos = 0.0, 0
            if alvo:
                q = alvo * real * alav / o
                real -= abs(q) * o * (TAKER + SLIP)
                pe, pos = o, alvo
                if ops is not None:
                    ops.append({"t": t, "tipo": "compra" if alvo > 0 else "venda", "px": o, "valor": round(abs(q) * o, 2),
                                "obs": "abre comprado: preço em alta" if alvo > 0 else "abre vendido: preço em queda"})
            trocas += 1
        if pos and real + q * ((lo if pos > 0 else hi) - pe) <= capital * 0.05:   # margem acabou no pior ponto da hora
            liquidada = True
            curva.append(0.0); ts.append(t)
            break
        if pos and tx is not None:                            # funding: comprado paga, vendido recebe (taxa positiva)
            pg = q * c * tx[k]
            real -= pg
            pago += pg
        curva.append(real + (q * (c - pe) if pos else 0.0)); ts.append(t)
        if pos:
            horas_pos += 1
            horas_comp += pos > 0
        if i >= pronto:                                       # decide para a próxima vela
            if modo == "medias":
                alvo = 1 if rapida[i] > lenta[i] * (1 + BANDA) else -1 if rapida[i] < lenta[i] * (1 - BANDA) else alvo
            else:
                alvo = 1 if topo[i] is not None and c > topo[i] else -1 if fundo[i] is not None and c < fundo[i] else alvo
    return _resumo(velas, curva, ts, capital, {"ciclos": trocas, "horas_com_posicao": round(horas_pos / max(1, len(curva)), 3),
                                               "horas_comprado": round(horas_comp / max(1, horas_pos), 3), "liquidada": liquidada,
                                               "funding_pago": round(pago, 2)})


REV_N = 24                                                # reversão: o tamanho do movimento é medido nas últimas 24 h
REV_PRAZO = 48                                            # reversão: no máximo 48 h na posição


def reversao(velas: list[dict], gatilho: float, alvo: float, lados: str = "ambos", alav: float = 1.0, capital: float = 1000.0,
             ops: list | None = None, antes: list[dict] | None = None, funding: dict | None = None, custo: dict | None = None) -> dict:
    """Robô de reversão (versão 6, 10/11/2026): o contrário da tendência. Depois de uma queda forte (o fechamento
    `gatilho` abaixo do de 24 h antes) compra; com lados="ambos", depois de uma alta forte, vende. Sai no repique
    (`alvo` a favor, ordem limitada), na parada (o mesmo `gatilho` contra, a mercado) ou em 48 h (a mercado).
    A decisão sai no fechamento de uma vela e vale na abertura da próxima. Um movimento só dá uma entrada: para entrar
    de novo do mesmo lado, o movimento de 24 h precisa voltar para menos da metade do gatilho. Na vela em que a parada e
    o alvo cabem juntos, conta a parada (o pior caso)."""
    MAKER, TAKER, SLIP = _custos(custo)
    antes = list(antes or [])
    todas = antes + list(velas)
    n0 = len(antes)
    fech = [float(v["c"]) for v in todas]
    tx, pago = _taxas(velas, funding), 0.0
    real, q, pe, pos, ent_t = capital, 0.0, 0.0, 0, 0       # q = unidades (negativo = vendido)
    pendente, arm_c, arm_v = 0, True, True
    ops_n, acertos, horas_pos, liquidada = 0, 0, 0, False
    curva, ts = [], []

    def sair(px: float, t: int, taxa: float, motivo: str) -> None:
        nonlocal real, q, pos, ops_n, acertos
        lucro = q * (px - pe) - abs(q) * px * taxa
        real += lucro
        ops_n += 1
        acertos += lucro > 0
        if ops is not None:
            ops.append({"t": t, "tipo": "venda" if q > 0 else "compra", "px": px, "valor": round(abs(q) * px, 2), "lucro": round(lucro, 2),
                        "obs": motivo})
        q, pos = 0.0, 0

    for k, v in enumerate(velas):
        i = n0 + k
        o, hi, lo, c, t = float(v["o"]), float(v["h"]), float(v["l"]), float(v["c"]), int(v["t"])
        if pendente and not pos:                              # a decisão do fechamento anterior vale na abertura desta vela
            q = pendente * real * alav / o
            real -= abs(q) * o * (TAKER + SLIP)
            pe, pos, ent_t = o, pendente, t
            if ops is not None:
                ops.append({"t": t, "tipo": "compra" if pos > 0 else "venda", "px": o, "valor": round(abs(q) * o, 2),
                            "obs": "compra depois da queda forte" if pos > 0 else "vende depois da alta forte"})
        pendente = 0
        if pos:
            if real + q * ((lo if pos > 0 else hi) - pe) <= capital * 0.05:   # a margem acabou no pior ponto da hora
                liquidada = True
                curva.append(0.0); ts.append(t)
                break
            parada, meta = (pe * (1 - gatilho), pe * (1 + alvo)) if pos > 0 else (pe * (1 + gatilho), pe * (1 - alvo))
            if (lo <= parada) if pos > 0 else (hi >= parada):
                sair(min(o, parada) if pos > 0 else max(o, parada), t, TAKER + SLIP, "parada: o movimento continuou")
            elif (hi >= meta) if pos > 0 else (lo <= meta):
                sair(meta, t, MAKER, "alvo: veio o repique")
            elif t + HORA - ent_t >= REV_PRAZO * HORA:
                sair(c, t, TAKER + SLIP, "prazo de 48 h")
        if pos and tx is not None:                            # funding: comprado paga, vendido recebe (taxa positiva)
            pg = q * c * tx[k]
            real -= pg
            pago += pg
        curva.append(real + (q * (c - pe) if pos else 0.0)); ts.append(t)
        horas_pos += bool(pos)
        if i >= REV_N:
            mov = c / fech[i - REV_N] - 1
            arm_c = arm_c or mov > -gatilho / 2
            arm_v = arm_v or mov < gatilho / 2
            if not pos:
                if mov <= -gatilho and arm_c:
                    pendente, arm_c = 1, False
                elif lados == "ambos" and mov >= gatilho and arm_v:
                    pendente, arm_v = -1, False
    return _resumo(velas, curva, ts, capital, {"ciclos": ops_n, "acertos": acertos, "horas_com_posicao": round(horas_pos / max(1, len(curva)), 3),
                                               "liquidada": liquidada, "funding_pago": round(pago, 2)})


def _resumo(velas, curva, ts, capital, extra) -> dict:
    """A curva hora a hora (patrimônio no FECHAMENTO de cada vela; ts = abertura da vela) e o resumo."""
    final = curva[-1] if curva else capital
    return {"final": final, "retorno": final / capital - 1, "pior_queda": _queda(curva), "eq": curva, "ts": ts, **extra}
