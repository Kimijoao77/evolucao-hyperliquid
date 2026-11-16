import random

from evolucao import DIA, HORA
from evolucao.cofres import FamiliaCofres
from evolucao.cofres import mercado as M
from evolucao.cofres import vida as V
from evolucao.cofres.dna import ESPECIES, DNACofre, nome
from evolucao.familia import MotorRecalculo

from .base import CFG, T0

HLP = M.HLP


def cofre(nome_, taxa_dia, t_ini, t_fim, passo=6 * HORA, tvl=1_000_000, queda_em=None, queda=0.0, com=0.1, hlp=False):
    """Um cofre de mentira: o índice cresce `taxa_dia` por dia; em `queda_em` cai `queda` de uma vez."""
    pts, x, t = [], 1.0, t_ini
    while t <= t_fim:
        if queda_em and t - passo < queda_em <= t:
            x *= 1 - queda
        pts.append([t, round(x, 8)])
        x *= (1 + taxa_dia) ** (passo / DIA)
        t += passo
    fichas = [[tt, tvl, True, False] for tt in range(t_ini, t_fim + 1, passo)]
    return {"nome": nome_, "criado": t_ini, "comissao": 0.0 if hlp else com, "hlp": hlp, "filho": False, "pts": pts, "fichas": fichas}


def mundo(fim):
    ini = T0 - 400 * DIA
    cs = {HLP: cofre("HLP", 0.001, ini, fim, hlp=True),
          "0xbom": cofre("Bom", 0.003, ini, fim),
          "0xmedio": cofre("Médio", 0.0015, ini, fim),
          "0xruim": cofre("Ruim", -0.001, ini, fim),
          "0xpequeno": cofre("Pequeno", 0.004, ini, fim, tvl=50_000),
          "0xcai": cofre("Cai", 0.003, ini, fim, queda_em=T0 + 10 * DIA, queda=0.5)}
    return cs, list(range(T0, fim + 1, 6 * HORA))


def genes(**k):
    g = {"janela_dias": 90, "criterio": "retorno", "max_queda": 0.3, "min_idade_dias": 60, "min_tvl": 100_000.0,
         "n_cofres": 2, "peso_hlp": 0, "revisao_dias": 14, "parada": 0}
    g.update(k)
    return g


def test_dna_e_nome():
    rng = random.Random(2)
    for esp in ESPECIES:
        for _ in range(20):
            d = DNACofre.sortear(esp, rng, CFG["limites"])
            assert d.valido(CFG["limites"])
            assert "dias" in nome(d.genes)
    assert all(DNACofre.sortear("agressiva", rng).genes["criterio"] == "retorno" for _ in range(10))


def test_escolhe_os_melhores_que_passam_no_filtro():
    cs, _ = mundo(T0 + 30 * DIA)
    cf = V.Cofres(cs)
    assert V.escolher(genes(), cf, T0) == ["0xcai", "0xbom"]        # o pequeno não tem dinheiro; o ruim perde
    assert V.escolher(genes(n_cofres=1, criterio="constancia"), cf, T0)[0] in ("0xbom", "0xcai")
    # depois da queda de 50 %, o "Cai" sai do filtro de queda máxima
    assert "0xcai" not in V.escolher(genes(), cf, T0 + 20 * DIA)


def test_vida_comissao_parada_e_estresse():
    cs, grade = mundo(T0 + 40 * DIA)
    cf = V.Cofres(cs)
    # tudo no "Cai" (o melhor até a queda): a queda de 50 % faz o Predador abater
    tudo = V.viver(genes(n_cofres=1, criterio="eficiencia"), cf, grade, T0, T0 + 40 * DIA, 1000.0, 0.3)
    assert tudo["morte"] and tudo["morreu_em"] >= T0 + 10 * DIA and len(set(tudo["eq"][tudo["pts"].index(tudo["morreu_em"]):])) == 1
    # no "Bom" a comissão de 10 % sai do lucro
    bom = V.viver(genes(n_cofres=1, max_queda=0.3, min_tvl=100_000.0), V.Cofres({k: v for k, v in cs.items() if k != "0xcai"}), grade, T0, T0 + 40 * DIA, 1000.0, 0.3)
    bruto = cf.idx("0xbom", T0 + 40 * DIA) / cf.idx("0xbom", T0) - 1
    assert abs(bom["eq"][-1] / 1000 - 1 - 0.9 * bruto) < 1e-6
    # a parada de 20 % tira do "Cai" depois da queda; sem parada ele fica até a revisão
    com_parada = V.viver(genes(parada=0.2, revisao_dias=60), cf, grade, T0, T0 + 40 * DIA, 1000.0, 0.3)
    sem_parada = V.viver(genes(parada=0, revisao_dias=60), cf, grade, T0, T0 + 40 * DIA, 1000.0, 0.3)
    assert "0xcai" not in com_parada["em"] and "0xcai" in sem_parada["em"]
    e = V.viver(genes(), cf, grade, T0, T0 + 40 * DIA, 1000.0, 0.3, estresse=True)
    n = V.viver(genes(), cf, grade, T0, T0 + 40 * DIA, 1000.0, 0.3)
    assert e["ops"][0] >= n["ops"][0] + DIA                         # no estresse o depósito sai 1 dia depois
    # refazer mais tarde não muda o passado
    n2 = V.viver(genes(), cf, grade, T0, T0 + 30 * DIA, 1000.0, 0.3)
    assert n["eq"][:len(n2["eq"])] == n2["eq"]


def test_hlp_e_a_regua():
    cs, grade = mundo(T0 + 20 * DIA)
    so_hlp = V.viver(genes(peso_hlp=1.0, n_cofres=1, max_queda=0.05, min_tvl=1e9), cf := V.Cofres(cs), grade, T0, T0 + 20 * DIA, 1000.0, 0.3)
    assert so_hlp["em"] == [HLP]
    assert abs(so_hlp["eq"][-1] / 1000 - cf.idx(HLP, T0 + 20 * DIA) / cf.idx(HLP, T0)) < 1e-6   # sem comissão


def test_andou_usa_a_serie_mais_fina():
    av = [[T0 + i * HORA, 100.0] for i in range(25)]
    pnl = [[T0 + i * HORA, float(i)] for i in range(25)]
    port = [["day", {"accountValueHistory": av, "pnlHistory": pnl}]]
    t, r = M.andou(port, T0 + 10 * HORA)
    assert t == T0 + 24 * HORA and abs(r - (1.01 ** 14)) < 1e-9


def test_motor_dos_cofres(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path / "dados"))
    cs, grade = mundo(T0 + 30 * DIA)
    fam = FamiliaCofres(CFG)
    fam.preparar = lambda api, agora, desde, log: (fam.usar(cs, [g for g in grade if g <= agora]), True)[1]
    s1 = MotorRecalculo(CFG, fam, T0 + HORA, raiz=tmp_path).rodar()
    assert s1["resumo"]["robos"] == len(ESPECIES) * 13
    s2 = MotorRecalculo(CFG, fam, T0 + 16 * DIA, raiz=tmp_path).rodar()
    assert s2["geracao"]["n"] == 2 and s2["resumo"]["regua_nome"] == "Só o HLP"
    assert any(r["em"] for r in s2["robos"])
