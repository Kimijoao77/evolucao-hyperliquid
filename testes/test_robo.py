"""Um robô vivendo num mercadinho de mentira: revisão, cópia com atraso, parada, freio e abate."""
from evolucao import DIA, HORA, MINUTO
from evolucao import robo as R
from evolucao.predador import Predator
from evolucao.traders import Traders
from testes.base import CFG, T0, PrecoFixo, degraus, fill, fotos_de, historico

AMB = CFG["ambiente"]
LIM = CFG["limites"]
GENES = {"janela_dias": 30, "min_operacoes": 10, "min_fator_lucro": 1.2, "duracao_min": 30, "max_carteiras": 4,
         "criterio": "fator_lucro", "alvo": 1.0, "revisao_dias": 7, "parada": 0.10, "freio": 0.15, "corte": 0,
         "ganho": 0, "tempo_max_h": 0, "desvio_max": 0.01}
AGORA = T0 + 30 * DIA


def mundo(novos: dict, precos: dict, ntl=10_000.0):
    """Traders com histórico bom em 'HIST' até AGORA e, depois, os fills de `novos` (em moedas com preço em `precos`)."""
    fills = {w: historico(AGORA, moeda="HIST") + fs for w, fs in novos.items()}
    fotos = {w: fotos_de(w, T0, AGORA + 10 * DIA, ntl=ntl, abertas=("BTC", "SOL", "ETH")) for w in novos}
    tr = Traders(fills, fotos, CFG["universo"])
    return R.Mundo(PrecoFixo({"HIST": 100.0, **precos}), tr, fills, fotos, novos, LIM, Predator(LIM))


def test_copia_entra_com_atraso_na_proporcao_e_so_depois_de_nascer():
    antes = [fill(AGORA - HORA, "ETH", "B", 50.0, 10.0, 0.0)]                    # posição aberta ANTES do robô nascer
    depois = [fill(AGORA + HORA, "BTC", "B", 100.0, 20.0, 0.0)]                  # 2.000 de 10.000 = 20 % da conta
    m = mundo({"a": antes + depois}, {"BTC": 100.0, "ETH": 50.0})
    c = R.nova_conta(1000.0, AGORA)
    R.avancar(c, GENES, AMB, m, AGORA + HORA)                                    # a ordem dele saiu agora: ainda não copiou
    assert list(c["subs"]) == ["a"] and c["subs"]["a"]["pos"] == {} and c["ordens"] == 0
    R.avancar(c, GENES, AMB, m, AGORA + HORA + 5 * MINUTO)
    sub = c["subs"]["a"]
    assert "ETH" not in sub["pos"]                                               # o que já estava aberto não é copiado
    # um trader só: fatia de 50 % (limite por trader) = 500; 20 % disso = 100 em BTC
    assert abs(sub["capital"] - 500) < 1e-6 and abs(sub["pos"]["BTC"][0] * 100 - 100) < 0.5
    assert abs(c["caixa"] - 500) < 1e-6 and c["ordens"] == 1
    assert c["pat"] < 1000 and c["pat"] > 999.8                                  # só o custo da ordem


def test_parada_larga_o_trader_e_nao_volta_na_mesma_geracao():
    fs = [fill(AGORA + HORA, "BTC", "B", 100.0, 300.0, 0.0)]                     # 3× a conta dele em BTC
    preco = degraus([(0, 100.0), (AGORA + 3 * HORA, 96.0)])                      # cai 4 %: −12 % na subconta
    m = mundo({"a": fs}, {"BTC": preco}, ntl=30_000.0)
    genes = {**GENES, "alvo": 3.0, "revisao_dias": 1, "freio": 0.25}
    c = R.nova_conta(1000.0, AGORA)
    R.avancar(c, genes, AMB, m, AGORA + 2 * HORA)
    assert c["subs"]["a"]["pos"]["BTC"][0] > 0
    R.avancar(c, genes, AMB, m, AGORA + 4 * HORA)
    assert c["subs"] == {} and "a" in c["bloqueadas"] and c["paradas"] == 1
    assert 930 < c["caixa"] < 945 and c["vivo"]                                  # perdeu ~12 % dos 500
    R.avancar(c, genes, AMB, m, AGORA + 3 * DIA)                                 # as revisões seguintes não trazem ele de volta
    assert c["subs"] == {}
    R.virar_conta(c, m, AGORA + 3 * DIA)                                         # geração nova: o bloqueio acaba
    assert c["bloqueadas"] == {} and c["queda"] == 0 and c["base"] == c["pat"]


def test_freio_do_robo_fecha_tudo_descansa_e_volta():
    fa = [fill(AGORA + HORA, "BTC", "B", 100.0, 300.0, 0.0)]
    fb = [fill(AGORA + HORA, "SOL", "B", 10.0, 3000.0, 0.0)]
    cai = lambda p: degraus([(0, p), (AGORA + 3 * HORA, p * 0.95)])  # noqa: E731   −5 % → −15 % em cada subconta
    m = mundo({"a": fa, "b": fb}, {"BTC": cai(100.0), "SOL": cai(10.0)}, ntl=30_000.0)
    genes = {**GENES, "alvo": 3.0, "parada": 0.25, "freio": 0.10}
    c = R.nova_conta(1000.0, AGORA)
    R.avancar(c, genes, AMB, m, AGORA + 4 * HORA)
    assert c["subs"] == {} and c["freios"] == 1 and c["descanso_ate"] > 0 and c["vivo"]
    assert 835 < c["pat"] < 850 and abs(c["pat"] - c["caixa"]) < 1e-9
    R.avancar(c, genes, AMB, m, AGORA + 2 * DIA)
    assert c["subs"] == {}                                                       # ainda descansando
    R.avancar(c, genes, AMB, m, AGORA + 4 * DIA)
    assert c["descanso_ate"] == 0 and set(c["subs"]) == {"a", "b"}               # voltou a copiar


def test_predador_abate_quem_passa_do_limite_duro():
    fa = [fill(AGORA + HORA, "BTC", "B", 100.0, 300.0, 0.0)]
    fb = [fill(AGORA + HORA, "SOL", "B", 10.0, 3000.0, 0.0)]
    desaba = lambda p: degraus([(0, p), (AGORA + 3 * HORA, p * 0.85)])  # noqa: E731  −15 % de uma vez: −45 % nas subcontas
    m = mundo({"a": fa, "b": fb}, {"BTC": desaba(100.0), "SOL": desaba(10.0)}, ntl=30_000.0)
    c = R.nova_conta(1000.0, AGORA)
    R.avancar(c, {**GENES, "alvo": 3.0, "parada": 0.25, "freio": 0.25}, AMB, m, AGORA + DIA)
    assert not c["vivo"] and "abatido" in c["morte"] and c["subs"] == {}
    assert c["t"] == AGORA + DIA and c["pat"] == c["caixa"] < 700


def test_corte_ganho_e_tempo_saem_antes_do_trader():
    fs = [fill(AGORA + HORA, "BTC", "B", 100.0, 100.0, 0.0)]
    sobe = degraus([(0, 100.0), (AGORA + 3 * HORA, 106.0)])
    for genes, quando in (({**GENES, "ganho": 0.05}, AGORA + 4 * HORA), ({**GENES, "tempo_max_h": 6}, AGORA + 8 * HORA)):
        m = mundo({"a": fs}, {"BTC": sobe})
        c = R.nova_conta(1000.0, AGORA)
        R.avancar(c, genes, AMB, m, AGORA + 2 * HORA)
        assert c["subs"]["a"]["pos"]
        R.avancar(c, genes, AMB, m, quando)
        assert c["subs"]["a"]["pos"] == {} and c["subs"]["a"]["travas"] == {"BTC": 1} and c["ordens"] == 2
    m = mundo({"a": fs}, {"BTC": degraus([(0, 100.0), (AGORA + 3 * HORA, 96.0)])})
    c = R.nova_conta(1000.0, AGORA)
    R.avancar(c, {**GENES, "corte": 0.03}, AMB, m, AGORA + 4 * HORA)
    assert c["subs"]["a"]["pos"] == {} and c["pat"] < 1000


def test_exposicao_nunca_passa_do_limite_na_entrada():
    fs = [fill(AGORA + HORA, "BTC", "B", 100.0, 5000.0, 0.0)]                    # o trader a 50× (!)
    m = mundo({"a": fs}, {"BTC": 100.0}, ntl=500_000.0)
    c = R.nova_conta(1000.0, AGORA)
    R.avancar(c, {**GENES, "alvo": 3.0}, AMB, m, AGORA + 2 * HORA)
    assert R.exposicao(c, m.precos, AGORA + 2 * HORA) <= LIM["exposicao_max"] * c["pat"]
    assert c["expo_max"] <= LIM["exposicao_max"]


def test_dinheiro_nao_aparece_nem_some():
    """Com o preço parado, o patrimônio só cai pelo custo das ordens (taxa + escorregamento)."""
    fs = [fill(AGORA + HORA, "BTC", "B", 100.0, 50.0, 0.0), fill(AGORA + 2 * HORA, "BTC", "A", 100.0, 50.0, 50.0)]
    m = mundo({"a": fs}, {"BTC": 100.0})
    c = R.nova_conta(1000.0, AGORA)
    R.avancar(c, GENES, AMB, m, AGORA + 3 * HORA)
    movimentado = 2 * 250.0                                                      # entrou com 250 e saiu
    custo = movimentado * (AMB["taxa"] + AMB["escorrega"])
    assert c["ordens"] == 2 and abs((1000 - c["pat"]) - custo) < 0.01
    assert abs(sum(R.resultado_por_trader(c, m, AGORA + 3 * HORA).values()) - (c["pat"] - 1000)) < 1e-6


def test_trader_que_sai_do_universo_e_fechado():
    fs = [fill(AGORA + HORA, "BTC", "B", 100.0, 50.0, 0.0)]
    m = mundo({"a": fs}, {"BTC": 100.0})
    c = R.nova_conta(1000.0, AGORA)
    R.avancar(c, GENES, AMB, m, AGORA + 2 * HORA)
    m.ativas.discard("a")
    R.avancar(c, GENES, AMB, m, AGORA + 3 * HORA)
    assert c["subs"] == {} and abs(c["caixa"] - c["pat"]) < 1e-9
