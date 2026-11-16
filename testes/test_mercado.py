from evolucao import HORA, MINUTO
from evolucao import mercado as M
from evolucao.traders import Traders, escolher, operacoes
from testes.base import CFG, T0, PrecoFixo, fill, fotos_de, historico, ida_e_volta

AMB = CFG["ambiente"]


def conta():
    return {"taxas": 0.0, "ordens": 0}


def test_negociar_abre_aumenta_reduz_e_vira():
    c, s = conta(), M.nova_sub("w", T0, 1000.0, 1.0, 3.0)
    M.negociar(c, s, "BTC", 2.0, 100.0, T0, 0.001)             # compra 2 a 100
    M.negociar(c, s, "BTC", 2.0, 110.0, T0 + 1, 0.001)         # mais 2 a 110: médio 105
    assert s["pos"]["BTC"] == [4.0, 105.0]
    r = M.negociar(c, s, "BTC", -1.0, 115.0, T0 + 2, 0.001)    # vende 1 a 115: realiza 10
    assert abs(r - (10 - 0.115)) < 1e-9 and s["pos"]["BTC"] == [3.0, 105.0]
    M.negociar(c, s, "BTC", -5.0, 100.0, T0 + 3, 0.001)        # vira: fecha 3 (−15) e abre 2 vendido a 100
    assert s["pos"]["BTC"] == [-2.0, 100.0] and s["desde"]["BTC"] == T0 + 3
    taxas = (200 + 220 + 115 + 500) * 0.001
    assert abs(s["colateral"] - (1000 + 10 - 15 - taxas)) < 1e-9
    assert abs(c["taxas"] - taxas) < 1e-9 and c["ordens"] == 4
    M.negociar(c, s, "BTC", 2.0, 100.0, T0 + 4, 0.0)
    assert s["pos"] == {} and s["desde"] == {}


def test_aplicar_copia_na_proporcao_da_conta_e_respeita_o_teto():
    p = PrecoFixo({"BTC": 100.0})
    c, s = conta(), M.nova_sub("w", T0, 1000.0, 1.0, 3.0)
    # o trader tem 10 mil e pôs 5 mil em BTC (50 %): a subconta de 1.000 põe 500
    ev = {"t": T0, "exec": T0 + MINUTO, "moeda": "BTC", "pos": 50.0, "px": 100.0}
    assert M.aplicar(c, s, ev, 10_000.0, p, AMB, 0.01) is None
    assert abs(s["pos"]["BTC"][0] * 100 - 500) < 1e-6
    # ele sobe para 10× a conta: a cópia para no teto de 3× o patrimônio
    ev = {"t": T0 + 2, "exec": T0 + 2 * MINUTO, "moeda": "BTC", "pos": 1000.0, "px": 100.0}
    assert M.aplicar(c, s, ev, 10_000.0, p, AMB, 0.01) is None
    assert M.exposicao(s, p, T0 + HORA) <= 3.0 * M.patrimonio(s, p, T0 + HORA) + 1e-6
    # ele zera: a cópia zera
    ev = {"t": T0 + 3, "exec": T0 + 3 * MINUTO, "moeda": "BTC", "pos": 0.0, "px": 100.0}
    assert M.aplicar(c, s, ev, 10_000.0, p, AMB, 0.01) is None and s["pos"] == {}
    assert s["colateral"] < 1000                                # pagou taxa e escorregamento


def test_nao_corre_atras_do_preco_que_fugiu():
    c, s = conta(), M.nova_sub("w", T0, 1000.0, 1.0, 3.0)
    ev = {"t": T0, "exec": T0 + MINUTO, "moeda": "BTC", "pos": 50.0, "px": 100.0}
    assert M.aplicar(c, s, ev, 10_000.0, PrecoFixo({"BTC": 103.0}), AMB, 0.02) == "preço fugiu"   # compra 3 % mais cara
    assert s["pos"] == {}
    assert M.aplicar(c, s, ev, 10_000.0, PrecoFixo({"BTC": 97.0}), AMB, 0.02) is None             # mais barato: entra
    # para SAIR não tem tolerância: sai no preço que estiver
    ev = {"t": T0 + 2, "exec": T0 + 2 * MINUTO, "moeda": "BTC", "pos": 0.0, "px": 100.0}
    assert M.aplicar(c, s, ev, 10_000.0, PrecoFixo({"BTC": 80.0}), AMB, 0.02) is None and s["pos"] == {}


def test_trava_espera_o_trader_sair():
    p = PrecoFixo({"BTC": 100.0})
    c, s = conta(), M.nova_sub("w", T0, 1000.0, 1.0, 3.0)
    s["travas"]["BTC"] = 1                                      # a cópia saiu antes dele (corte, ganho ou tempo)
    ev = {"t": T0, "exec": T0 + MINUTO, "moeda": "BTC", "pos": 60.0, "px": 100.0}
    assert M.aplicar(c, s, ev, 10_000.0, p, AMB, 0.01) == "saiu antes do trader"
    assert M.aplicar(c, s, {**ev, "pos": 0.0}, 10_000.0, p, AMB, 0.01) is None and "BTC" not in s["travas"]
    assert M.aplicar(c, s, ev, 10_000.0, p, AMB, 0.01) is None and s["pos"]["BTC"][0] > 0


def test_eventos_juntam_por_minuto_e_ignoram_spot_e_terceiros():
    fs = [fill(T0, "BTC", "B", 100, 1, 0), fill(T0 + 5_000, "BTC", "B", 101, 1, 1), fill(T0 + 3 * MINUTO, "BTC", "A", 105, 2, 2),
          fill(T0, "@107", "B", 1, 1, 0), fill(T0, "xyz:GOLD", "B", 1, 1, 0)]
    evs = M.eventos(fs, 60_000)
    assert [(e["moeda"], e["pos"], e["exec"]) for e in evs] == [("BTC", 2.0, T0 + 65_000), ("BTC", 0.0, T0 + 4 * MINUTO)]


def test_posicao_que_some_da_foto_vira_zerou():
    fs = [fill(T0, "BTC", "B", 100, 1, 0)]
    fotos = [{"t": T0 + HORA, "a": "w", "v": 1000, "ntl": 0, "pos": []}]
    evs = M.eventos(fs, 60_000, fotos)
    assert evs[-1]["pos"] == 0.0 and evs[-1]["t"] == T0 + HORA


def test_operacoes_e_ficha_so_enxergam_o_que_ja_tinha_fechado():
    fs = ida_e_volta(T0, "BTC", 100, 110, 1.0) + ida_e_volta(T0 + 5 * HORA, "ETH", 50, 45, 2.0, lado="A")
    ops = operacoes(fs)
    assert [(o[0], round(o[2], 6)) for o in ops] == [(T0 + HORA, 10.0), (T0 + 6 * HORA, 10.0)]
    tr = Traders({"w": fs}, {"w": fotos_de("w", T0 - HORA, T0 + 10 * HORA)}, CFG["universo"])
    assert tr.ficha("w", T0 + 2 * HORA, 30)["n"] == 1           # a segunda ainda não tinha fechado
    assert tr.ficha("w", T0 + 7 * HORA, 30)["n"] == 2
    assert tr.ficha("w", T0 - 2 * HORA, 30) is None             # antes de tudo: não existe


def test_virada_de_lado_fecha_uma_operacao_e_abre_outra():
    fs = [fill(T0, "BTC", "B", 100, 1, 0), fill(T0 + HORA, "BTC", "A", 110, 3, 1, pnl=10.0, taxa=0.3),
          fill(T0 + 2 * HORA, "BTC", "B", 100, 2, -2, pnl=20.0, taxa=0.2)]
    ops = operacoes(fs)
    assert len(ops) == 2
    assert abs(ops[0][2] - (10 - 0.1)) < 1e-9 and abs(ops[1][2] - (20 - 0.2 - 0.2)) < 1e-9


def test_escolher_filtra_e_ordena():
    fim = T0 + 30 * 24 * HORA
    bom, ruim, sumido = historico(fim, ganho=2.0, perda=1.0), historico(fim, ganho=1.0, perda=3.0), historico(fim - 20 * 24 * HORA)
    fills = {"bom": bom, "ruim": ruim, "sumido": sumido}
    fotos = {w: fotos_de(w, T0, fim) for w in fills}
    tr = Traders(fills, fotos, CFG["universo"])
    genes = {"janela_dias": 30, "min_operacoes": 10, "min_fator_lucro": 1.2, "duracao_min": 30, "max_carteiras": 5, "criterio": "fator_lucro"}
    assert [w for w, _ in escolher(genes, fim, tr, fills)] == ["bom"]
    assert escolher({**genes, "duracao_min": 120}, fim, tr, fills) == []       # ele segura 60 min: curto demais para este DNA
    assert escolher(genes, fim, tr, fills, fora={"bom": 1}) == []
    assert tr.ficha("sumido", fim, 30) is None                                  # parado há 20 dias


def test_sem_foto_com_saldo_vale_o_saldo_de_referencia():
    fim = T0 + 30 * 24 * HORA
    fills = {"w": historico(fim)}
    zeradas = {"w": fotos_de("w", T0, fim, valor=0.0, ntl=0.0)}
    genes = {"janela_dias": 30, "min_operacoes": 10, "min_fator_lucro": 1.2, "duracao_min": 30, "max_carteiras": 5, "criterio": "fator_lucro"}
    assert escolher(genes, fim, Traders(fills, zeradas, CFG["universo"]), fills) == []                 # sem saldo conhecido: fora
    tr = Traders(fills, zeradas, CFG["universo"], {"w": 20_000.0})
    assert tr.ficha("w", fim, 30)["conta"] == 20_000.0 and [w for w, _ in escolher(genes, fim, tr, fills)] == ["w"]
    assert tr.saldos["w"].em(fim) == 20_000.0
    mista = {"w": fotos_de("w", T0, fim - 5 * HORA, valor=7_000.0) + fotos_de("w", fim - 4 * HORA, fim, valor=0.0)}
    assert Traders(fills, mista, CFG["universo"], {"w": 20_000.0}).ficha("w", fim, 30)["conta"] == 7_000.0   # a última foto COM saldo
