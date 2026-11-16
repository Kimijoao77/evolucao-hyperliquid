"""O motor inteiro num mercadinho de mentira: começa, só anda para a frente, vira a geração e guarda a memória."""
import copy
import json
import math
import random

from evolucao import DIA, HORA, MINUTO
from evolucao import dados as D
from evolucao.dna import ESPECIES
from evolucao.motor import EvolutionEngine
from testes.base import CFG, T0, PrecoFixo, fill, fotos_de, historico

INICIO = T0 + 40 * DIA
MOEDAS = ("BTC", "ETH", "SOL", "HYPE")


def preco(moeda):
    base = {"BTC": 100.0, "ETH": 50.0, "SOL": 10.0, "HYPE": 20.0}[moeda]
    fase = MOEDAS.index(moeda)
    return lambda t: base * (1 + 0.04 * math.sin((t - INICIO) / (9 * HORA) + fase) + 0.03 * math.sin((t - INICIO) / (31 * HORA) + 2 * fase))


PRECOS = {m: preco(m) for m in MOEDAS}


def montar(tmp_path, n=12, dias=8, semente=1):
    """n traders: histórico bom antes de INICIO e operações de verdade (nas moedas com preço) por `dias` depois."""
    rng = random.Random(semente)
    cart = {}
    for i in range(n):
        w = f"0x{i:040x}"
        fs = historico(INICIO, moeda="HIST", n=45, ganho=1.5 + i % 3, perda=1.0, dur=(20 + 40 * (i % 4)) * MINUTO)
        t = INICIO + rng.randrange(1, 6) * HORA
        while t < INICIO + dias * DIA:
            m, lado = rng.choice(MOEDAS), rng.choice("BA")
            qtd = rng.uniform(0.2, 1.5) * 10_000 / PRECOS[m](t)
            dur = rng.randrange(1, 20) * HORA
            s = 1 if lado == "B" else -1
            fs.append(fill(t + i * 1000, m, lado, PRECOS[m](t), qtd, 0.0))
            fs.append(fill(t + dur + i * 1000, m, "A" if lado == "B" else "B", PRECOS[m](t + dur), qtd, s * qtd))
            t += dur + rng.randrange(1, 8) * HORA
        D.anexar_fills(w, fs)
        for ft in fotos_de(w, INICIO - 30 * DIA, INICIO + dias * DIA, abertas=MOEDAS, cada=6 * HORA):
            D.anexar_foto(ft)
        cart[w] = {"situacao": "ativa", "apelido": f"trader{i}", "origem": "ranking"}
    D.gravar_json(tmp_path / "universo.json", {"carteiras": cart, "fila": []})


def rodar(tmp_path, agora, cfg=CFG):
    m = EvolutionEngine(cfg, agora=agora, precos=PrecoFixo({"HIST": 100.0, **PRECOS}), raiz=tmp_path)
    return m.rodar(), m


def curto(dias=2):
    return {**CFG, "geracao": {**CFG["geracao"], "dias": dias}}


def test_espera_o_universo_encher(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path))
    montar(tmp_path, n=3)
    uni = D.ler_json(tmp_path / "universo.json", {})
    uni["fila"] = [{"a": "0xfila", "apelido": "", "origem": "ranking"}]
    D.gravar_json(tmp_path / "universo.json", uni)
    s, _ = rodar(tmp_path, INICIO + HORA)
    assert s["fase"] == "montando" and s["falta"] == CFG["universo"]["minimo_para_comecar"] - 3
    assert not (tmp_path / "estado.json").exists()
    uni["fila"] = []                                                         # a fila acabou: começa com o que tem
    D.gravar_json(tmp_path / "universo.json", uni)
    s, _ = rodar(tmp_path, INICIO + 3 * HORA)
    assert s["fase"] == "rodando" and s["geracao"]["n"] == 1


def test_so_anda_para_a_frente(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path))
    montar(tmp_path)
    s, _ = rodar(tmp_path, INICIO + 3 * MINUTO)                              # a primeira rodada: nasce todo mundo, zerado
    assert s["inicio"] == INICIO and len(s["robos"]) == len(ESPECIES) * 13
    assert all(r["r"] == 0 and r["ordens"] == 0 and r["total"] == 0 for r in s["robos"])
    est = D.ler_json(tmp_path / "estado.json", {})
    assert all(sub["inicio"] >= INICIO for r in est["robos"] for sub in r["n"]["subs"].values())
    s, _ = rodar(tmp_path, INICIO + DIA)
    assert s["resumo"]["operando"] > 20 and any(r["ordens"] > 0 for r in s["robos"])
    assert all(p[0] > INICIO for p in s["curva"])
    assert s["universo"]["mais_copiados"][0]["trader"].startswith("trader")


def test_rodar_aos_poucos_da_o_mesmo_que_rodar_de_uma_vez(tmp_path, monkeypatch):
    fim = INICIO + 5 * DIA + 3 * MINUTO
    a, b = tmp_path / "a", tmp_path / "b"
    finais = []
    for pasta, passos in ((a, [INICIO + 3 * MINUTO, fim]),
                          (b, [INICIO + 3 * MINUTO] + list(range(INICIO + 2 * HORA + 3 * MINUTO, fim, 2 * HORA)) + [fim])):
        monkeypatch.setenv("EVOLUCAO_DADOS", str(pasta))
        montar(pasta)
        for agora in passos:
            s, _ = rodar(pasta, agora, curto())
        finais.append(s)
    x, y = finais
    assert x["geracao"]["n"] == y["geracao"]["n"] == 3
    assert [r["id"] for r in x["robos"]] == [r["id"] for r in y["robos"]]
    for r1, r2 in zip(x["robos"], y["robos"]):
        assert r1["dna"] == r2["dna"] and r1["ordens"] == r2["ordens"]
        assert abs(r1["r"] - r2["r"]) < 1e-9 and abs(r1["re"] - r2["re"]) < 1e-9
    assert json.loads((a / "memoria" / "geracao-0002.json").read_text()) == json.loads((b / "memoria" / "geracao-0002.json").read_text())


def test_virada_de_geracao_guarda_a_memoria_e_mantem_as_vagas(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path))
    montar(tmp_path)
    rodar(tmp_path, INICIO + 3 * MINUTO, curto())
    s, m = rodar(tmp_path, INICIO + 2 * DIA + HORA, curto())
    assert s["geracao"]["n"] == 2 and s["geracao"]["inicio"] == INICIO + 2 * DIA
    mem = json.loads((tmp_path / "memoria" / "geracao-0001.json").read_text(encoding="utf-8"))
    assert mem["geracao"] == 1 and len(mem["robos"]) == len(ESPECIES) * 13
    saiu = {x["id"] for x in mem["saiu"]}
    assert saiu and all((r["id"] in saiu) == ("saiu" in r) for r in mem["robos"])
    assert all(set(r["medidas"]) >= {"r", "re", "queda", "sm", "ordens", "nota"} and r["dna"] for r in mem["robos"])
    assert len(mem["nasceu"]) == len(mem["saiu"])                            # cada vaga aberta foi preenchida
    vivos = {r["id"] for r in s["robos"]}
    assert not (vivos & saiu) and {n["id"] for n in mem["nasceu"]} <= vivos
    for esp in ESPECIES:
        assert sum(1 for r in s["robos"] if r["especie"] == esp and r["grupo"] == "evoluido") == 10
    novos = [r for r in s["robos"] if r["nasc"] == 2]
    assert novos and all(r["hist"] == [] and r["total"] == r["r"] for r in novos)   # filho começa do zero
    velho = next(r for r in s["robos"] if r["nasc"] == 1)
    assert len(velho["hist"]) == 1 and velho["hist"][0]["g"] == 1
    assert s["historia"][0]["g"] == 1 and s["eventos"][0]["tipo"] == "geracao"
    est = D.ler_json(tmp_path / "estado.json", {})
    for r in est["robos"]:                                                    # o DNA de quem ficou não mudou
        antes = next((x for x in mem["robos"] if x["id"] == r["id"]), None)
        assert antes is None or antes["dna"] == r["dna"]


def test_limites_duros_valem_para_todos_o_tempo_todo(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path))
    montar(tmp_path)
    lim = CFG["limites"]
    for agora in [INICIO + 3 * MINUTO] + list(range(INICIO + 6 * HORA, INICIO + 6 * DIA, 6 * HORA)):
        rodar(tmp_path, agora, curto())
        for r in D.ler_json(tmp_path / "estado.json", {})["robos"]:
            assert r["dna"]["alvo"] <= lim["exposicao_max"]
            for c in (r["n"], r["e"]):
                assert c["expo_max"] <= lim["exposicao_max"] * 1.35           # entra no máximo a 3×; o preço pode esticar um pouco
                assert c["caixa"] >= -1e-6
                if c["vivo"]:
                    assert c["pat"] > (1 - lim["queda_abate"]) * c["pico_abs"]
                    for sub in c["subs"].values():
                        assert sub["capital"] <= lim["peso_max_por_carteira"] * 1000 * (c["pico_abs"] / 1000) + 1e-6
