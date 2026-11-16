import random

from evolucao.dna import BLOCOS, ESPECIES, GENES, BotDNA, faixa
from testes.base import CFG

LIM = CFG["limites"]


def test_sorteio_fica_dentro_das_faixas_da_especie():
    rng = random.Random(1)
    for esp in ESPECIES:
        for _ in range(300):
            d = BotDNA.sortear(esp, rng, LIM)
            assert d.valido(LIM), (esp, d.genes)
            assert d.genes["alvo"] <= LIM["exposicao_max"]


def test_limite_duro_vale_mais_que_o_gene():
    rng = random.Random(2)
    aperto = {**LIM, "exposicao_max": 1.2}
    for _ in range(200):
        d = BotDNA.sortear("diversificada", rng, aperto)
        assert d.genes["alvo"] <= 1.2
        d.mutar(rng, 1.0, 0.5, aperto)
        assert d.genes["alvo"] <= 1.2


def test_filho_herda_blocos_inteiros_dos_dois_pais():
    rng = random.Random(3)
    for _ in range(200):
        pai, mae = BotDNA.sortear("curta", rng, LIM), BotDNA.sortear("curta", rng, LIM)
        f = BotDNA.cruzar(pai, mae, rng, LIM)
        origem = set()
        for b in BLOCOS:
            nomes = [n for n, g in GENES.items() if g["bloco"] == b]
            do_pai = all(f.genes[n] == pai.genes[n] for n in nomes)
            da_mae = all(f.genes[n] == mae.genes[n] for n in nomes)
            assert do_pai or da_mae, b
            origem.add("pai" if do_pai and not da_mae else "mae" if da_mae and not do_pai else "tanto faz")
        assert f.valido(LIM)
        assert origem != {"pai"} and origem != {"mae"}


def test_mae_de_outra_especie_e_encaixada_na_especie_do_pai():
    rng = random.Random(4)
    for _ in range(200):
        f = BotDNA.cruzar(BotDNA.sortear("cautelosa", rng, LIM), BotDNA.sortear("diversificada", rng, LIM), rng, LIM)
        assert f.especie == "cautelosa" and f.valido(LIM)
        assert f.genes["alvo"] <= faixa("alvo", "cautelosa")[1]


def test_mutacao_sempre_muda_algo_e_continua_valida():
    rng = random.Random(5)
    for esp in ESPECIES:
        for _ in range(200):
            d = BotDNA.sortear(esp, rng, LIM)
            antes = d.copia()
            mudou = d.mutar(rng, 0.25, 0.15, LIM)
            assert mudou and d.valido(LIM)
            assert d.distancia(antes) > 0
            assert all(d.genes[n] == antes.genes[n] for n in GENES if n not in mudou)


def test_distancia():
    rng = random.Random(6)
    a, b = BotDNA.sortear("exigente", rng, LIM), BotDNA.sortear("exigente", rng, LIM)
    assert a.distancia(a) == 0
    assert 0 < a.distancia(b) <= 1
    assert abs(a.distancia(b) - b.distancia(a)) < 1e-12
