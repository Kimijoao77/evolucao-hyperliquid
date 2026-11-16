import json
import math
import random

from evolucao import DIA, HORA
from evolucao import dados as D
from evolucao.familia import MotorRecalculo
from evolucao.precos import FamiliaPrecos
from evolucao.precos import vida as V
from evolucao.precos.dna import ESPECIES, MOEDAS, DNAPreco, nome, regra

from .base import CFG, T0

CUSTO = {"maker": 0.00015, "taker": 0.00045, "slip": 0.0002}


def passeio(n, t0, p0=100.0, vol=0.01, deriva=0.0, semente=1):
    """Velas de 1 h de um passeio aleatório."""
    rng, p, out = random.Random(semente), p0, []
    for i in range(n):
        o = p
        p = o * math.exp(deriva + rng.gauss(0, vol))
        out.append({"t": t0 + i * HORA, "o": o, "h": max(o, p) * (1 + abs(rng.gauss(0, vol / 3))),
                    "l": min(o, p) * (1 - abs(rng.gauss(0, vol / 3))), "c": p})
    return out


def reta(n, t0, p0=100.0, passo=0.0):
    """Preço andando em linha reta (passo por hora, em fração)."""
    out, p = [], p0
    for i in range(n):
        o, p = p, p * (1 + passo)
        out.append({"t": t0 + i * HORA, "o": o, "h": max(o, p), "l": min(o, p), "c": p})
    return out


def test_dna_respeita_especie_e_limite():
    rng = random.Random(3)
    for esp in ESPECIES:
        for _ in range(30):
            d = DNAPreco.sortear(esp, rng, CFG["limites"])
            assert d.valido(CFG["limites"])
            mud = d.mutar(rng, 0.3, 0.15, CFG["limites"])
            assert mud and all(m in ESPECIES[esp]["genes"] for m in mud)
            assert d.genes["moeda"] in MOEDAS and 1.0 <= d.genes["alav"] <= 3.0
            assert regra(esp, d.genes)["tipo"] == esp
            assert nome(esp, d.genes).startswith(d.genes["moeda"] + ":")


def test_cruzar_entre_especies_fica_na_especie_do_pai():
    rng = random.Random(5)
    pai, mae = DNAPreco.sortear("grade", rng), DNAPreco.sortear("tendencia", rng)
    for _ in range(20):
        f = DNAPreco.cruzar(pai, mae, rng, CFG["limites"])
        assert f.especie == "grade" and f.valido(CFG["limites"])


def test_vida_e_igual_refeita_e_so_anda_para_a_frente():
    vs = passeio(24 * 60, T0)
    t0 = T0 + 30 * DIA
    rg = {"tipo": "grade", "faixa": 0.1, "niveis": 10, "alav": 1.0}
    a = V.viver(rg, 0, vs, None, t0, T0 + 50 * DIA, 1000.0, CUSTO, 0.3)
    b = V.viver(rg, 0, vs, None, t0, T0 + 60 * DIA, 1000.0, CUSTO, 0.3)
    assert a["pts"][0] == t0 + HORA                             # nada antes do nascimento
    n = len(a["pts"])
    assert b["pts"][:n] == a["pts"] and b["eq"][:n] == a["eq"]  # a conta refeita mais tarde dá o mesmo passado


def test_freio_fecha_descansa_e_recomeca():
    vs = reta(24 * 20, T0, passo=-0.004)                        # cai sem parar
    rg = {"tipo": "dca", "passo": 0.02, "alvo": 0.02, "media_h": 0, "alav": 1.0}
    v = V.viver(rg, 0.10, vs, None, T0, T0 + 20 * DIA, 1000.0, CUSTO, 0.3, descanso_h=72)
    assert v["freios"], "o freio de 10 % tinha de disparar"
    t = v["freios"][0]
    i = v["pts"].index(t)
    assert len(set(v["eq"][i:i + 72])) == 1                      # 3 dias parado, com o mesmo dinheiro
    assert v["morte"] is None or "abatido" in v["morte"]


def test_abate_com_30_por_cento_de_queda():
    vs = reta(24 * 30, T0, passo=-0.004)
    rg = {"tipo": "dca", "passo": 0.02, "alvo": 0.02, "media_h": 0, "alav": 3.0}
    v = V.viver(rg, 0, vs, None, T0, T0 + 30 * DIA, 1000.0, CUSTO, 0.3)
    assert v["morte"] and v["morreu_em"]
    j = v["pts"].index(v["morreu_em"])
    assert len(set(v["eq"][j:])) == 1                           # morto não opera mais


def test_tendencia_ganha_na_alta_e_estresse_rende_menos():
    antes = reta(800, T0, passo=0.0)
    vs = antes + reta(24 * 20, T0 + 800 * HORA, p0=100.0, passo=0.002)
    t0 = T0 + 800 * HORA
    rg = {"tipo": "tendencia", "modo": "medias", "a": 12, "b": 48, "alav": 1.0}
    n = V.viver(rg, 0, vs, None, t0, t0 + 20 * DIA, 1000.0, CUSTO, 0.3)
    e = V.viver(rg, 0, vs, None, t0, t0 + 20 * DIA, 1000.0, {"maker": 0.00045, "taker": 0.00045, "slip": 0.0006}, 0.3)
    mn, me = V.medir(n, t0, t0 + 20 * DIA), V.medir(e, t0, t0 + 20 * DIA)
    assert mn["r"] > 0.1 and me["r"] < mn["r"] and mn["ordens"] >= 1


def test_medir_retorno_queda_e_melhor_dia():
    v = {"pts": [T0 + (i + 1) * HORA for i in range(48)], "eq": [1000.0] * 24 + [1100.0] * 12 + [1050.0] * 12,
         "ops": [T0 + 5 * HORA, T0 + 30 * HORA], "capital": 1000.0}
    m = V.medir(v, T0, T0 + 48 * HORA)
    assert abs(m["r"] - 0.05) < 1e-9
    assert abs(m["queda"] - (1 - 1050 / 1100)) < 1e-9
    assert abs(m["sm"] - (0.05 - 0.05)) < 1e-9                 # o melhor dia (+5 %) sai da conta
    assert m["ordens"] == 2


def test_motor_roda_vira_geracao_e_grava(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path / "dados"))
    velas = {m: passeio(24 * 80, T0, p0=10 + i, vol=0.012, semente=i) for i, m in enumerate(MOEDAS)}
    fam = FamiliaPrecos(CFG)
    fam.preparar = lambda api, agora, desde, log: (fam.usar(velas), True)[1]
    inicio = T0 + 35 * DIA
    m1 = MotorRecalculo(CFG, fam, inicio + 3 * HORA, raiz=tmp_path)
    s1 = m1.rodar()
    assert s1["resumo"]["robos"] == len(ESPECIES) * 13 and s1["geracao"]["n"] == 1
    assert {r["especie"] for r in s1["robos"]} == set(ESPECIES)
    # 15 dias depois: a geração 1 fechou, a memória foi gravada e nasceram robôs novos
    m2 = MotorRecalculo(CFG, fam, inicio + 15 * DIA, raiz=tmp_path)
    s2 = m2.rodar()
    assert s2["geracao"]["n"] == 2 and len(s2["historia"]) == 1
    mem = json.loads((tmp_path / "memoria" / "precos" / "geracao-0001.json").read_text(encoding="utf-8"))
    assert mem["resumo"]["nasceu"] == mem["resumo"]["saiu"] and len(mem["robos"]) == len(ESPECIES) * 13
    assert s2["resumo"]["regua_nome"] == "Segurar BTC" and s2["resumo"]["regua"] is not None
    assert s2["curva"] and len(s2["curva"][0]) == 4
    est = D.ler_json(tmp_path / "dados" / "precos" / "estado.json", {})
    novos = [r for r in est["robos"] if r["nasc"] == 2]
    assert novos and all(r["t0"] == est["inicio"] + 14 * DIA for r in novos)
