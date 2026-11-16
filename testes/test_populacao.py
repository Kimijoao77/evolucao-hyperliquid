import random

from evolucao import robo as R
from evolucao.dna import ESPECIES, BotDNA
from evolucao.populacao import Population
from evolucao.predador import Predator
from evolucao.traders import Traders
from testes.base import CFG, T0, PrecoFixo

PRED = Predator(CFG["limites"], CFG["nota"])
VAGAS, SORTEIO = CFG["geracao"]["vagas_por_especie"], CFG["geracao"]["sorteio_por_especie"]


def mundo():
    return R.Mundo(PrecoFixo({}), Traders({}, {}), {}, {}, [], CFG["limites"], PRED)


def medidas(pop, nota_de):
    """Medidas inventadas: nota_de(robô) → nota (o resto acompanha)."""
    out = {}
    for r in pop.robos:
        n = nota_de(r)
        out[r["id"]] = {"r": n, "re": n, "queda": 0.0, "sm": n, "ordens": 50 if n != 0 else 0, "traders": 3,
                        "freios": 0, "paradas": 0, "expo_max": 1.0, "nota": n, "morte": None}
    return out


def numero(r):
    return int(r["id"][1:])


def test_populacao_inicial():
    pop = Population.inicial(CFG, random.Random(1), T0)
    assert len(pop.robos) == len(ESPECIES) * (VAGAS + SORTEIO)
    assert len({r["id"] for r in pop.robos}) == len(pop.robos)
    for esp in ESPECIES:
        assert len(pop.do_grupo(esp, "evoluido")) == VAGAS and len(pop.do_grupo(esp, "sorteio")) == SORTEIO
    assert all(BotDNA(r["especie"], r["dna"]).valido(CFG["limites"]) for r in pop.robos)
    assert all(r["n"]["caixa"] == 1000 and r["e"]["caixa"] == 1000 for r in pop.robos)


def test_sem_confirmado_ninguem_vira_pai():
    pop = Population.inicial(CFG, random.Random(2), T0)
    rel = pop.virar(1, medidas(pop, lambda r: 0.01 * (numero(r) % 7 - 3)), PRED, random.Random(9), T0, mundo())
    novos = [n for n in rel["nasceu"] if n["origem"] != "sorteio"]
    assert novos and all(n["origem"] == "imigrante" and n["pais"] == [] for n in novos)
    assert not any(r["estado"] == "confirmada" for r in pop.robos)
    assert any(r["estado"] == "selecionada" for r in pop.robos)
    for esp in ESPECIES:                                                     # as vagas continuam as mesmas
        assert len(pop.do_grupo(esp, "evoluido")) == VAGAS and len(pop.do_grupo(esp, "sorteio")) == SORTEIO


def test_duas_geracoes_boas_seguidas_confirmam_e_geram_filhos():
    pop = Population.inicial(CFG, random.Random(3), T0)
    boa = lambda r: 0.05 + 0.001 * (numero(r) % 5) if numero(r) % 2 == 0 else -0.02  # noqa: E731
    pop.virar(1, medidas(pop, boa), PRED, random.Random(1), T0, mundo())
    assert not any(r["estado"] == "confirmada" for r in pop.robos)
    rel = pop.virar(2, medidas(pop, boa), PRED, random.Random(2), T0, mundo())
    conf = {r["id"] for r in pop.robos if r["estado"] == "confirmada"}
    assert conf
    filhos = [n for n in rel["nasceu"] if n["origem"] in ("filho", "mutante")]
    assert filhos
    antes = {r["id"] for r in pop.robos} | {s["id"] for s in rel["saiu"]}
    for f in filhos:
        assert f["pais"] and f["mudou"]
        assert all(p in antes for p in f["pais"])
    por_id = {r["id"]: r for r in pop.robos}
    for f in filhos:                                                         # pai da mesma espécie é sempre um confirmado
        assert f["pais"][0] in conf and por_id[f["pais"][0]]["especie"] == f["especie"]
        assert por_id[f["id"]]["nasc"] == 3 and por_id[f["id"]]["hist"] == []
        assert BotDNA(f["especie"], por_id[f["id"]]["dna"]).valido(CFG["limites"])
    for esp in ESPECIES:                                                     # sempre sobra uma vaga para sangue novo
        assert any(n["origem"] == "imigrante" for n in rel["nasceu"] if n["especie"] == esp)


def test_aprovado_nunca_sai_e_abatido_sempre_sai():
    pop = Population.inicial(CFG, random.Random(4), T0)
    m = medidas(pop, lambda r: 0.03 if numero(r) % 3 == 0 else -0.01)
    vitima = pop.do_grupo("curta", "evoluido")[0]
    m[vitima["id"]].update(nota=0.5, r=0.5, morte="abatido: caiu 30 % desde o pico")   # nem nota alta salva
    aprovados = set()
    for esp in ESPECIES:
        grupo = sorted(pop.do_grupo(esp, "evoluido"), key=lambda r: (-m[r["id"]]["nota"], r["id"]))
        aprovados |= {r["id"] for r in grupo[:VAGAS // 2] if m[r["id"]]["nota"] > 0 and not m[r["id"]]["morte"]}
    rel = pop.virar(1, m, PRED, random.Random(5), T0, mundo())
    saiu = {s["id"]: s["motivo"] for s in rel["saiu"]}
    assert "abatido" in saiu[vitima["id"]]
    assert aprovados and not (aprovados & set(saiu))
    assert all(r["estado"] == "selecionada" for r in pop.robos if r["id"] in aprovados)


def test_parado_nao_e_aprovado_e_sai_na_terceira_geracao():
    pop = Population.inicial(CFG, random.Random(5), T0)
    parado = pop.do_grupo("exigente", "evoluido")[0]["id"]
    nota = lambda r: 0.0 if r["id"] == parado else -0.01 - 0.001 * (numero(r) % 9)  # noqa: E731
    for g in (1, 2):
        rel = pop.virar(g, medidas(pop, nota), PRED, random.Random(g), T0, mundo())
        vivo = next(r for r in pop.robos if r["id"] == parado)
        assert vivo["estado"] == "em prova" and vivo["ociosas"] == g           # melhor nota da espécie e mesmo assim não aprova
    rel = pop.virar(3, medidas(pop, nota), PRED, random.Random(3), T0, mundo())
    assert "sem operar" in {s["id"]: s["motivo"] for s in rel["saiu"]}[parado]


def test_quem_fica_abaixo_do_sorteio_nao_e_aprovado():
    pop = Population.inicial(CFG, random.Random(6), T0)
    nota = lambda r: 0.10 if r["grupo"] == "sorteio" else 0.02  # noqa: E731   todo mundo no azul, mas o sorteio foi melhor
    pop.virar(1, medidas(pop, nota), PRED, random.Random(1), T0, mundo())
    assert not any(r["estado"] in ("selecionada", "confirmada") for r in pop.robos)


def test_o_controle_troca_no_mesmo_ritmo():
    pop = Population.inicial(CFG, random.Random(7), T0)
    velhos = {r["id"] for r in pop.robos if r["grupo"] == "sorteio"}
    rel = pop.virar(1, medidas(pop, lambda r: -0.01), PRED, random.Random(1), T0, mundo())
    agora = {r["id"] for r in pop.robos if r["grupo"] == "sorteio"}
    assert len(agora) == len(velhos) and len(velhos - agora) == len(ESPECIES)   # 1 por espécie (30 % de 3, para cima)
    assert all(not n["pais"] for n in rel["nasceu"] if n["origem"] == "sorteio")
