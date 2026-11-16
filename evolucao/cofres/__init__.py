"""Família 3: robôs de cofres (vaults) da Hyperliquid.

O robô não opera: escolhe em quais cofres depositar, quanto pôr em cada um e quando sair. A evolução escolhe o filtro
(janela, critério, queda máxima, idade e tamanho do cofre), a divisão (quantos cofres, quanto no HLP, de quanto em
quanto tempo revê) e a parada. Tudo simulação, com US$ 1.000 de mentira por robô.
"""
from __future__ import annotations

import requests

from ..precos.vida import medir as medir_vida
from . import mercado as M
from . import vida as V
from .dna import DNACofre, nome


class FamiliaCofres:
    id = "cofres"
    titulo = "Cofres"
    dna = DNACofre
    explica = ("Cada robô escolhe em quais cofres da Hyperliquid depositar, quanto pôr em cada um e quando sair. "
               "A evolução escolhe o filtro, a divisão e a parada. A régua é deixar tudo no HLP.")

    def __init__(self, cfg: dict, baixar_lista=None):
        self.limites = cfg["limites"]
        self.capital = cfg["ambiente"]["capital"]
        self.baixar_lista = baixar_lista or (lambda: requests.get(M.LISTA, timeout=120).json())
        self.cf = V.Cofres({})
        self.grade: list[int] = []

    # ---------- dados
    def preparar(self, api, agora: int, desde: int, log: list[str], manter: set[str] | None = None) -> bool:
        if api is not None:
            try:
                M.atualizar(api, self.baixar_lista, agora, manter or set(), log)
            except Exception as e:  # noqa: BLE001
                log.append(f"cofres: a leitura falhou ({str(e)[:80]}); fica com o que já estava guardado")
        self.usar(M.todos(), M.rodadas())
        return bool(self.grade)

    def usar(self, cofres: dict, grade: list[int]) -> None:
        self.cf, self.grade = V.Cofres(cofres), list(grade)

    # ---------- população
    @staticmethod
    def contas(capital: float, t: int) -> dict:
        return {"t0": t}

    @staticmethod
    def virar_robo(r: dict, mundo, t: int) -> None:
        return None

    # ---------- vida e medidas
    def viver(self, r: dict, ate: int, estresse: bool) -> dict:
        v = V.viver(r["dna"], self.cf, self.grade, r["t0"], ate, self.capital, self.limites["queda_abate"], estresse)
        v["situacao"] = None if v["morte"] else ("operando" if v["em"] else "no caixa")
        return v

    @staticmethod
    def medir(v: dict, de: int, ate: int) -> dict:
        return medir_vida(v, de, ate)

    @staticmethod
    def nome(r: dict) -> str:
        return nome(r["dna"])

    def detalhe(self, r: dict, v: dict) -> dict:
        return {"em": [self.cf.c[e].get("nome") or e[:8] for e in v.get("em", [])]}

    def regua(self, de: int, ate: int) -> tuple[str, float | None]:
        a, b = self.cf.idx(M.HLP, de), self.cf.idx(M.HLP, ate)
        return "Só o HLP", (round(b / a - 1, 5) if a and b else None)
