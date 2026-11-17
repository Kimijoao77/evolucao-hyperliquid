import json

from conferir import conferir


def gravar(pasta, nome, obj):
    p = pasta / nome
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def montar(pasta, gerado=1000, n=3, robos=52, carteiras=120, fase="rodando", linhagem=52):
    gravar(pasta, "evolucao.json", {"gerado": gerado, "fase": fase, "geracao": {"n": n}})
    gravar(pasta, "estado.json", {"robos": [{}] * robos, "linhagem": {str(i): {} for i in range(linhagem)}})
    gravar(pasta, "universo.json", {"carteiras": {str(i): {} for i in range(carteiras)}})
    gravar(pasta, "precos.json", {"resumo": {}})
    gravar(pasta, "precos/estado.json", {"robos": [{}] * 52})


def test_rodada_normal_passa(tmp_path):
    montar(tmp_path / "anterior")
    montar(tmp_path / "dados", gerado=2000, n=3, linhagem=60)
    assert conferir(tmp_path / "dados", tmp_path / "anterior") == []


def test_primeira_rodada_sem_anterior_passa(tmp_path):
    montar(tmp_path / "dados")
    assert conferir(tmp_path / "dados", tmp_path / "anterior") == []


def test_arquivo_cortado_e_recusado(tmp_path):
    montar(tmp_path / "anterior")
    montar(tmp_path / "dados", gerado=2000)
    (tmp_path / "dados" / "estado.json").write_text('{"robos": [', encoding="utf-8")
    assert any("não abre" in p for p in conferir(tmp_path / "dados", tmp_path / "anterior"))


def test_populacao_sumindo_e_recusada(tmp_path):
    montar(tmp_path / "anterior")
    montar(tmp_path / "dados", gerado=2000, robos=10)
    assert any("população caiu" in p for p in conferir(tmp_path / "dados", tmp_path / "anterior"))


def test_geracao_voltando_e_recusada(tmp_path):
    montar(tmp_path / "anterior", n=5)
    montar(tmp_path / "dados", gerado=2000, n=1)
    assert any("geração voltou" in p for p in conferir(tmp_path / "dados", tmp_path / "anterior"))


def test_universo_esvaziando_e_recusado(tmp_path):
    montar(tmp_path / "anterior")
    montar(tmp_path / "dados", gerado=2000, carteiras=10)
    assert any("universo" in p for p in conferir(tmp_path / "dados", tmp_path / "anterior"))


def test_familia_sumindo_e_recusada(tmp_path):
    montar(tmp_path / "anterior")
    montar(tmp_path / "dados", gerado=2000)
    (tmp_path / "dados" / "precos" / "estado.json").write_text('{"robos": []}', encoding="utf-8")
    assert any("precos" in p for p in conferir(tmp_path / "dados", tmp_path / "anterior"))
