"""Família 5: robôs de pools concentradas (DLMM da Meteora, Solana).

O robô escolhe pools, a largura e a posição da faixa e quanto tempo fica. A régua é a regra fixa do laboratório de
pools do radar (faixa estreita: até −10 % abaixo do preço, 3 pools de preço calmo com a maior taxa, até 24 h).
Tudo simulação, com US$ 1.000 de mentira por robô.
"""
from __future__ import annotations

from ..precos.vida import medir as medir_vida
from . import mercado as M
from . import vida as V
from .dna import DNAPool, nome

REGRA_RADAR = {"criterio": "taxa_24h", "balanco_max": 0.02, "tvl_min": 10_000.0, "posicao": "abaixo", "r": 0.05, "n_pools": 3,
               "prazo_h": 24, "espera_acima_h": 3}


class FamiliaPools:
    id = "pools"
    titulo = "Pools concentradas"
    dna = DNAPool
    explica = ("Cada robô põe dinheiro em pools de liquidez concentrada da Meteora (Solana) e ganha a taxa de quem troca "
               "enquanto o preço fica na faixa. A evolução escolhe as pools, a faixa e o tempo. A régua é a regra fixa do radar.")

    def __init__(self, cfg: dict, buscar=None, gecko=None):
        self.limites = cfg["limites"]
        self.capital = cfg["ambiente"]["capital"]
        self.buscar, self.gecko = buscar or M.meteora, gecko
        self.pp = V.Pools({}, [])
        self._regua: dict[int, dict] = {}

    def preparar(self, api, agora: int, desde: int, log: list[str]) -> bool:
        if api is not None:
            try:
                M.atualizar(agora, desde, log, self.buscar, self.gecko)
            except Exception as e:  # noqa: BLE001
                log.append(f"pools: a leitura falhou ({str(e)[:80]}); fica com o que já estava guardado")
        self.usar(M.todas(), M.rodadas())
        return bool(self.pp.rodadas)

    def usar(self, pools: dict, rodadas: list) -> None:
        self.pp, self._regua = V.Pools(pools, rodadas), {}

    @staticmethod
    def contas(capital: float, t: int) -> dict:
        return {"t0": t}

    @staticmethod
    def virar_robo(r: dict, mundo, t: int) -> None:
        return None

    def viver(self, r: dict, ate: int, estresse: bool) -> dict:
        v = V.viver(r["dna"], self.pp, r["t0"], ate, self.capital, self.limites["queda_abate"], estresse)
        v["situacao"] = None if v["morte"] else ("operando" if v["em"] else "no caixa")
        return v

    @staticmethod
    def medir(v: dict, de: int, ate: int) -> dict:
        return medir_vida(v, de, ate)

    @staticmethod
    def nome(r: dict) -> str:
        return nome(r["dna"])

    def detalhe(self, r: dict, v: dict) -> dict:
        return {"em": v.get("em", [])}

    def regua(self, de: int, ate: int) -> tuple[str, float | None]:
        if de not in self._regua:
            fim = self.pp.rodadas[-1][0] if self.pp.rodadas else de
            self._regua[de] = V.viver(REGRA_RADAR, self.pp, de, fim, self.capital, 1.0)
        from ..familia import valor_em
        return "Regra fixa do radar", round(valor_em(self._regua[de], ate) / self.capital - 1, 5)
