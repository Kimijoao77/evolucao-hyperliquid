import os

from evolucao import DIA, HORA
from evolucao import coletor as K
from evolucao import dados as D
from testes.base import CFG, T0

AGORA = T0 + 100 * DIA


class API:
    """A Hyperliquid de mentira: cada carteira tem uma lista de fills (no formato da API) e um saldo."""

    def __init__(self, fills, saldos, ranking=()):
        self.fills, self.saldos, self.ranking, self.pedidos = fills, saldos, list(ranking), []

    def leaderboard(self):
        return self.ranking

    def estado(self, a):
        return {"marginSummary": {"accountValue": str(self.saldos.get(a, 0)), "totalNtlPos": "0"}, "assetPositions": []}

    def fills_desde(self, a, inicio, fim=None, maximo=10000):
        self.pedidos.append((a, inicio))
        return [f for f in self.fills.get(a, []) if f["time"] >= inicio]


def bruto(t, n, moeda="BTC"):
    return {"time": t, "coin": moeda, "side": "B", "px": "100", "sz": "1", "startPosition": "0", "closedPnl": "0", "fee": "0.01", "tid": n}


def linha(a, conta=50_000, roi=0.2, vlm=1_000_000, total=5_000, nome=""):
    return {"ethAddress": a, "accountValue": str(conta), "displayName": nome,
            "windowPerformances": [["month", {"pnl": "1", "roi": str(roi), "vlm": str(vlm)}], ["allTime", {"pnl": str(total), "roi": "1", "vlm": "1"}]]}


def cfg(**k):
    return {**CFG, "universo": {**CFG["universo"], **k}}


def test_fila_radar_na_frente_e_prefiltro(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path))
    ranking = [linha("0xA1"), linha("0xpequena", conta=500), linha("0xruim", roi=-0.1), linha("0xaposta", roi=9.0),
               linha("0xprejuizo", total=-1), linha("0xparada", vlm=10)]
    api = API({a: [bruto(AGORA - 5 * DIA + i * HORA, i) for i in range(20)] for a in ("0xa1", "0xdoradar")},
              {"0xa1": 50_000, "0xdoradar": 20_000}, ranking)
    r = K.coletar(cfg(), api, AGORA, ler_radar=lambda: {"carteiras": [{"carteira": "0xDoRadar", "apelido": "Zé"}]})
    uni = D.ler_json(tmp_path / "universo.json", {})
    assert {a for a, c in uni["carteiras"].items() if c["situacao"] == "ativa"} == {"0xa1", "0xdoradar"}
    assert uni["carteiras"]["0xdoradar"]["origem"] == "radar" and uni["carteiras"]["0xdoradar"]["apelido"] == "Zé"
    assert api.pedidos[0][0] == "0xdoradar"                                 # a do radar entra primeiro
    assert len(D.ler_fills("0xa1")) == 20 and len(D.ler_fotos()["0xa1"]) == 1
    assert r["entraram"] == 2 and r["fila"] == 0


def test_rapida_demais_e_sem_operacao_sao_recusadas(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path))
    api = API({"0xhft": [bruto(AGORA - DIA + i * 60_000, i) for i in range(1200)]}, {}, [linha("0xhft"), linha("0xnada")])
    K.coletar(cfg(), api, AGORA, ler_radar=lambda: {})
    c = D.ler_json(tmp_path / "universo.json", {})["carteiras"]
    assert c["0xhft"]["situacao"] == "recusada" and "rápida demais" in c["0xhft"]["motivo"]
    assert c["0xnada"]["situacao"] == "recusada"
    assert D.ler_fills("0xhft") == []                                       # recusada não ocupa espaço


def test_coleta_so_o_que_e_novo_e_aposenta_quem_parou_ou_quebrou(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path))
    fills = {a: [bruto(AGORA - 2 * DIA, 1)] for a in ("0xviva", "0xparou", "0xquebrou")}
    api = API(fills, {"0xviva": 9000, "0xparou": 9000, "0xquebrou": 9000}, [linha(a) for a in fills])
    K.coletar(cfg(), api, AGORA, ler_radar=lambda: {})
    depois = AGORA + 31 * DIA
    api.fills["0xviva"].append(bruto(depois - HORA, 2))
    api.fills["0xquebrou"].append({**bruto(depois - HORA, 3), "liquidation": {"method": "market"}})   # foi liquidada
    api.saldos["0xquebrou"] = 40
    api.pedidos.clear()
    api.ranking = []
    K.coletar(cfg(), api, depois, ler_radar=lambda: {})
    c = D.ler_json(tmp_path / "universo.json", {})["carteiras"]
    assert c["0xviva"]["situacao"] == "ativa" and len(D.ler_fills("0xviva")) == 2
    assert c["0xparou"]["situacao"] == "parada" and c["0xquebrou"]["situacao"] == "quebrou"
    assert all(inicio == AGORA - 2 * DIA + 1 for _, inicio in api.pedidos)   # pede só depois do último fill guardado
    api.pedidos.clear()
    K.coletar(cfg(), api, depois + 2 * HORA, ler_radar=lambda: {})
    assert [a for a, _ in api.pedidos] == ["0xviva"]                         # as aposentadas não são mais coletadas


def test_limite_de_vagas_e_faxina(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path))
    nomes = [f"0x{i:02d}" for i in range(8)]
    api = API({a: [bruto(AGORA - 150 * DIA, 1), bruto(AGORA - DIA, 2)] for a in nomes}, {a: 9000 for a in nomes}, [linha(a) for a in nomes])
    r = K.coletar(cfg(max_carteiras=3, dias_de_historico=200), api, AGORA, ler_radar=lambda: {})
    assert r["ativas"] == 3 and r["fila"] > 0
    meses = sorted(p.stem for p in (tmp_path / "fills").glob("*/*.jsonl"))
    assert len(set(meses)) == 1                                              # o mês de 150 dias atrás foi apagado


def test_saldo_zerado_sem_liquidacao_nao_e_quebra(tmp_path, monkeypatch):
    """Muita carteira tira o dinheiro da conta de perpétuos quando não tem posição: continua ativa, com o saldo do ranking."""
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path))
    api = API({"0xvazia": [bruto(AGORA - 2 * DIA, 1)]}, {"0xvazia": 0}, [linha("0xvazia", conta=80_000)])
    K.coletar(cfg(), api, AGORA, ler_radar=lambda: {})
    K.coletar(cfg(), api, AGORA + 2 * HORA, ler_radar=lambda: {})
    c = D.ler_json(tmp_path / "universo.json", {})["carteiras"]["0xvazia"]
    assert c["situacao"] == "ativa" and c["conta"] == 0 and c["conta_ref"] == 80_000


def test_quem_saiu_so_por_saldo_zero_volta_e_ganha_saldo_de_referencia(tmp_path, monkeypatch):
    monkeypatch.setenv("EVOLUCAO_DADOS", str(tmp_path))
    D.gravar_json(tmp_path / "universo.json", {"fila": [], "fila_em": AGORA, "carteiras": {
        "0xvolta": {"situacao": "quebrou", "origem": "ranking", "apelido": "", "em": AGORA, "ultimo_t": AGORA - DIA, "motivo": "a conta caiu para US$ 0"},
        "0xfoi": {"situacao": "quebrou", "origem": "ranking", "apelido": "", "em": AGORA, "ultimo_t": AGORA - DIA, "liquidada_em": AGORA - DIA}}})
    api = API({}, {"0xvolta": 0}, [linha("0xVolta", conta=25_000)])
    K.coletar(cfg(), api, AGORA + 2 * HORA, ler_radar=lambda: {})
    c = D.ler_json(tmp_path / "universo.json", {})["carteiras"]
    assert c["0xvolta"]["situacao"] == "ativa" and c["0xvolta"]["conta_ref"] == 25_000 and "motivo" not in c["0xvolta"]
    assert c["0xfoi"]["situacao"] == "quebrou"                               # a liquidada de verdade continua fora
