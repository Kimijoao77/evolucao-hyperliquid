"""Família 4: robôs de moedas novas (vender moeda recém-listada na Hyperliquid).

O robô vende cada moeda que estreia, com as regras do DNA (quando entrar, quando sair, quanto pôr). A régua é a regra
fixa do laboratório de moedas novas do radar: vende 24 h depois da estreia, 10 % por moeda, sai se subir 30 % ou em
14 dias. Tudo simulação, com US$ 1.000 de mentira por robô.
"""
from __future__ import annotations

from .. import DIA
from ..precos.vida import medir as medir_vida
from . import mercado as M
from . import vida as V
from .dna import DNAListagem, nome

REGRA_RADAR = {"espera_h": 24, "teto_estreia": 0, "parada": 0.30, "alvo": 0, "prazo_dias": 14, "parte": 0.10, "alav": 1.0,
               "max_abertas": 10}


class FamiliaListagens:
    id = "listagens"
    titulo = "Moedas novas"
    dna = DNAListagem
    explica = ("Cada robô vende (aposta na queda) as moedas que estreiam na Hyperliquid, com as próprias regras de quando "
               "entrar, quando sair e quanto pôr. A régua é a regra fixa do radar.")

    def __init__(self, cfg: dict):
        self.limites = cfg["limites"]
        self.capital = cfg["ambiente"]["capital"]
        self.moedas: dict[str, dict] = {}
        self._regua: dict[tuple, dict] = {}

    def preparar(self, api, agora: int, desde: int, log: list[str]) -> bool:
        if api is not None:
            try:
                M.atualizar(api, agora, desde, log)
            except Exception as e:  # noqa: BLE001
                log.append(f"moedas novas: a leitura falhou ({str(e)[:80]}); fica com o que já estava guardado")
        self.usar(M.todas())
        return True

    def usar(self, moedas: dict) -> None:
        self.moedas, self._regua = moedas, {}

    @staticmethod
    def contas(capital: float, t: int) -> dict:
        return {"t0": t}

    @staticmethod
    def virar_robo(r: dict, mundo, t: int) -> None:
        return None

    def viver(self, r: dict, ate: int, estresse: bool) -> dict:
        v = V.viver(r["dna"], self.moedas, r["t0"], ate, self.capital, self.limites["queda_abate"], estresse)
        v["situacao"] = None if v["morte"] else ("operando" if v["em"] else "esperando moeda")
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
        chave = (de, max(ate, de + 30 * DIA) // DIA)
        if chave not in self._regua:
            self._regua[chave] = V.viver(REGRA_RADAR, self.moedas, de, max(ate, de + DIA), self.capital, 1.0)
        v = self._regua[chave]
        from ..familia import valor_em
        return "Regra fixa do radar", round(valor_em(v, ate) / self.capital - 1, 5)
