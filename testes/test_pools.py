import math
import random

from evolucao import DIA, HORA, MINUTO
from evolucao.familia import MotorRecalculo
from evolucao.pools import REGRA_RADAR, FamiliaPools
from evolucao.pools import vida as V
from evolucao.pools.dna import ESPECIES, DNAPool, nome

from .base import CFG, T0

RODADA = 2 * HORA


def pool(precos5m, taxa_1h=0.5, tvl=100_000, ini=T0 - DIA):
    """Uma pool de mentira: preço de 5 em 5 min desde `ini`, foto a cada 2 h com a taxa da última hora (%)."""
    m5 = [[ini + i * 5 * MINUTO, c] for i, c in enumerate(precos5m)]
    fim = m5[-1][0]
    fotos = []
    for t in range(T0, fim + 1, RODADA):
        j = min(len(m5) - 1, (t - ini) // (5 * MINUTO))
        fotos.append([t, m5[j][1], taxa_1h, taxa_1h * 24, tvl, tvl * 3, 1.0, 1.0])
    h1 = [[ini - (26 - k) * HORA, precos5m[0]] for k in range(26)]
    return {"nome": "P", "x": "x", "y": "USDC", "bin_step": 20, "desde": T0, "fotos": fotos, "h1": h1, "m5": m5}


def genes(**k):
    g = dict(REGRA_RADAR)
    g.update(k)
    return g


def rodadas(ps, ate):
    return [[t, list(ps)] for t in range(T0, ate + 1, RODADA)]


def test_dna_e_nome():
    rng = random.Random(6)
    for esp in ESPECIES:
        for _ in range(20):
            d = DNAPool.sortear(esp, rng, CFG["limites"])
            assert d.valido(CFG["limites"]) and "pool" in nome(d.genes)


def test_preco_parado_recebe_taxa_e_estresse_menos():
    n = 12 * 24 * 4
    ps = {"A": pool([1.0 + 0.0001 * math.sin(i) for i in range(n)])}
    pp = V.Pools(ps, rodadas(ps, T0 + 2 * DIA))
    v = V.viver(genes(n_pools=1), pp, T0, T0 + 2 * DIA, 1000.0, 0.3)
    e = V.viver(genes(n_pools=1), pp, T0, T0 + 2 * DIA, 1000.0, 0.3, estresse=True)
    assert v["ops"] and v["eq"][-1] > 1000 and e["eq"][-1] < v["eq"][-1]


def test_queda_sai_abaixo_da_faixa_e_perde():
    n = 12 * 24 * 3
    cai = [1.0] * (12 * 24 + 6) + [1.0 * (1 - 0.003 * i) for i in range(n - 12 * 24 - 6)]
    ps = {"A": pool(cai, taxa_1h=0.01)}
    pp = V.Pools(ps, rodadas(ps, T0 + 2 * DIA))
    v = V.viver(genes(n_pools=1, balanco_max=0, r=0.02, prazo_h=48), pp, T0, T0 + 2 * DIA, 1000.0, 0.3)
    assert len(v["ops"]) >= 2 and v["eq"][1] < 1000              # saiu abaixo da faixa com a moeda que caiu


def test_balanco_filtra_pool_agitada():
    n = 12 * 24 * 2
    rng = random.Random(1)
    agitada = [1.0]
    for _ in range(n - 1):
        agitada.append(agitada[-1] * math.exp(rng.gauss(0, 0.03)))
    ps = {"A": pool(agitada)}
    pp = V.Pools(ps, rodadas(ps, T0 + DIA))
    assert V.escolher(pp, genes(balanco_max=0.01), T0 + 22 * HORA, ["A"]) == []
    assert V.escolher(pp, genes(balanco_max=0), T0 + 22 * HORA, ["A"]) == ["A"]


def test_motor_das_pools(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path / "dados"))
    rng = random.Random(3)
    ps = {}
    for k in range(6):
        p, xs = 1.0, []
        for _ in range(12 * 24 * 18):
            p *= math.exp(rng.gauss(0, 0.002 * (k + 1)))
            xs.append(p)
        ps[f"P{k}"] = pool(xs, taxa_1h=0.2 + 0.1 * k, tvl=20_000 * (k + 1))
    fam = FamiliaPools(CFG)
    fam.preparar = lambda api, agora, desde, log: (fam.usar(ps, rodadas(ps, agora)), True)[1]
    s1 = MotorRecalculo(CFG, fam, T0 + HORA, raiz=tmp_path).rodar()
    assert s1["resumo"]["robos"] == len(ESPECIES) * 13
    s2 = MotorRecalculo(CFG, fam, T0 + 15 * DIA, raiz=tmp_path).rodar()
    assert s2["geracao"]["n"] == 2 and s2["resumo"]["regua"] is not None and any(r["ordens"] for r in s2["robos"])
