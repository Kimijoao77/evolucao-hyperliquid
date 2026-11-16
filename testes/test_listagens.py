import random

from evolucao import DIA, HORA
from evolucao.familia import MotorRecalculo
from evolucao.listagens import REGRA_RADAR, FamiliaListagens
from evolucao.listagens import vida as V
from evolucao.listagens.dna import ESPECIES, DNAListagem, nome

from .base import CFG, T0


def moeda(estreia, precos, fora=False, fund=0.0):
    """Uma moeda nova com velas de 1 h: precos = fechamento de cada hora desde a estreia."""
    vs, ant = [], precos[0]
    for i, c in enumerate(precos):
        vs.append({"t": estreia + i * HORA, "o": ant, "h": max(ant, c) * 1.001, "l": min(ant, c) * 0.999, "c": c})
        ant = c
    return {"estreia": estreia, "alav_max": 3, "fora": fora, "velas": vs,
            "funding": {estreia + (i + 1) * HORA: fund for i in range(len(precos))}}


def genes(**k):
    g = dict(REGRA_RADAR)
    g.update(k)
    return g


def test_dna_e_nome():
    rng = random.Random(4)
    for esp in ESPECIES:
        for _ in range(20):
            d = DNAListagem.sortear(esp, rng, CFG["limites"])
            assert d.valido(CFG["limites"]) and nome(d.genes).startswith("vende")


def test_vende_e_ganha_na_queda_com_funding():
    cai = moeda(T0, [100 * (1 - 0.002 * i) for i in range(24 * 20)], fund=0.0001)
    v = V.viver(genes(), {"CAI": cai}, T0, T0 + 20 * DIA, 1000.0, 0.3)
    assert len(v["ops"]) == 2                                    # entrou 24 h depois e saiu nos 14 dias
    assert v["ops"][0] == T0 + 24 * HORA and v["eq"][-1] > 1000
    sem_fund = V.viver(genes(), {"CAI": moeda(T0, [100 * (1 - 0.002 * i) for i in range(24 * 20)])}, T0, T0 + 20 * DIA, 1000.0, 0.3)
    assert v["eq"][-1] > sem_fund["eq"][-1]                      # vendido recebe o funding positivo


def test_parada_alvo_e_teto():
    sobe = moeda(T0, [100 * (1 + 0.004 * i) for i in range(24 * 10)])
    v = V.viver(genes(parada=0.2), {"SOBE": sobe}, T0, T0 + 10 * DIA, 1000.0, 0.3)
    assert len(v["ops"]) == 2 and v["eq"][-1] < 1000 and v["eq"][-1] > 1000 * (1 - 0.1 * 0.25)
    cai = moeda(T0, [100 * (1 - 0.004 * i) for i in range(24 * 10)])
    a = V.viver(genes(alvo=0.2, prazo_dias=30), {"CAI": cai}, T0, T0 + 10 * DIA, 1000.0, 0.3)
    assert len(a["ops"]) == 2 and a["eq"][-1] > 1000              # saiu no alvo de −20 %
    # teto: subiu mais de 1,5× desde a estreia antes da hora de vender → não vende
    pula = moeda(T0, [100 * (1 + 0.03 * i) for i in range(24 * 3)])
    t = V.viver(genes(teto_estreia=1.5), {"P": pula}, T0, T0 + 3 * DIA, 1000.0, 0.3)
    assert not t["ops"]


def test_so_moedas_depois_do_nascimento_e_vagas():
    ms = {f"M{i}": moeda(T0 + i * HORA, [100.0] * (24 * 5)) for i in range(5)}
    v = V.viver(genes(max_abertas=3), ms, T0 + 2 * HORA, T0 + 5 * DIA, 1000.0, 0.3)
    entradas = [t for t in v["ops"] if t <= T0 + 30 * HORA]
    assert len(entradas) == 3                                    # todas 5 estreiam depois do nascimento (24 h de espera), só 3 vagas


def test_liquida_e_perde_a_margem():
    salto = moeda(T0, [100.0] * 30 + [400.0] * 10)
    v = V.viver(genes(alav=3.0, parada=0.8), {"S": salto}, T0, T0 + 2 * DIA, 1000.0, 0.3)
    assert abs(v["eq"][-1] - 900.0) < 1e-6                       # 10 % de margem perdida inteira


def test_motor_das_moedas_novas(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path / "dados"))
    rng = random.Random(9)
    ms = {}
    for i in range(12):
        e = T0 + i * 2 * DIA
        p, ps = 100.0, []
        for _ in range(24 * 46):
            p *= 1 + rng.gauss(-0.001, 0.02)
            ps.append(p)
        ms[f"N{i}"] = moeda(e, ps)
    fam = FamiliaListagens(CFG)
    fam.preparar = lambda api, agora, desde, log: (fam.usar({k: dict(m, velas=[v for v in m["velas"] if v["t"] + HORA <= agora]) for k, m in ms.items()}), True)[1]
    s1 = MotorRecalculo(CFG, fam, T0 + HORA, raiz=tmp_path).rodar()
    assert s1["resumo"]["robos"] == len(ESPECIES) * 13
    s2 = MotorRecalculo(CFG, fam, T0 + 15 * DIA, raiz=tmp_path).rodar()
    assert s2["geracao"]["n"] == 2 and s2["resumo"]["regua_nome"] == "Regra fixa do radar" and s2["resumo"]["regua"] is not None
    assert any(r["ordens"] for r in s2["robos"])
