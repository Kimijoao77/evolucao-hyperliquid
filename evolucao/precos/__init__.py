"""Família 2: robôs de preço (tendência, reversão, grade e DCA) nas moedas mais negociadas da Hyperliquid.

O robô decide sozinho, olhando só o preço (velas de 1 hora) e o funding. A evolução escolhe a moeda, os parâmetros do
sinal e o risco. Tudo simulação, com US$ 1.000 de mentira por robô.
"""
from __future__ import annotations

import bisect

from .. import HORA
from . import mercado as M
from . import vida as V
from .dna import MOEDAS, DNAPreco, nome, regra


class FamiliaPrecos:
    id = "precos"
    titulo = "Robôs de preço"
    dna = DNAPreco
    explica = ("Cada robô opera uma moeda sozinho, só com o preço: tendência, reversão, grade ou DCA. "
               "A evolução escolhe a moeda, o sinal e o risco. A régua é segurar BTC no mesmo período.")

    def __init__(self, cfg: dict):
        fc = (cfg.get("familias") or {}).get(self.id, {})
        self.limites = cfg["limites"]
        self.capital = cfg["ambiente"]["capital"]
        self.descanso_h = int(fc.get("descanso_h", 72))
        c = fc.get("custos", {})
        self.custo = {"maker": c.get("maker", 0.00015), "taker": c.get("taker", 0.00045), "slip": c.get("slip", 0.0002)}
        e = fc.get("estresse", {})
        self.custo_e = {"maker": self.custo["taker"] if e.get("maker_vira_taker", True) else self.custo["maker"],
                        "taker": self.custo["taker"], "slip": self.custo["slip"] * e.get("slip_x", 3)}
        self.velas: dict[str, list[dict]] = {}
        self.funding: dict[str, dict] = {}
        self.ts: dict[str, list[int]] = {}

    # ---------- dados
    def preparar(self, api, agora: int, desde: int, log: list[str]) -> bool:
        if api is not None:
            self.velas = M.atualizar(api, MOEDAS, agora, desde, log)
        else:
            self.velas = {m: M.ler_velas(m) for m in MOEDAS}
        self.funding = {m: M.ler_funding(m) for m in MOEDAS}
        self.ts = {m: [v["t"] for v in vs] for m, vs in self.velas.items()}
        return any(self.velas.values())

    def usar(self, velas: dict, funding: dict | None = None) -> None:
        """Para os testes: dados prontos, sem API."""
        self.velas, self.funding = velas, funding or {}
        self.ts = {m: [v["t"] for v in vs] for m, vs in velas.items()}

    # ---------- população
    @staticmethod
    def contas(capital: float, t: int) -> dict:
        return {"t0": t}

    @staticmethod
    def virar_robo(r: dict, mundo, t: int) -> None:
        return None

    # ---------- vida e medidas
    def viver(self, r: dict, ate: int, estresse: bool) -> dict:
        g = r["dna"]
        return V.viver(regra(r["especie"], g), g.get("freio") or 0, self.velas.get(g["moeda"], []),
                       self.funding.get(g["moeda"]) or None, r["t0"], ate, self.capital,
                       self.custo_e if estresse else self.custo, self.limites["queda_abate"], self.descanso_h)

    @staticmethod
    def medir(v: dict, de: int, ate: int) -> dict:
        return V.medir(v, de, ate)

    @staticmethod
    def nome(r: dict) -> str:
        return nome(r["especie"], r["dna"])

    def regua(self, de: int, ate: int) -> tuple[str, float | None]:
        """Segurar BTC (1×, sem custo) de `de` até `ate`."""
        vs, ts = self.velas.get("BTC") or [], self.ts.get("BTC") or []
        i, j = bisect.bisect_left(ts, de), bisect.bisect_right(ts, ate - HORA) - 1
        if not vs or i >= len(vs) or j < i:
            return "Segurar BTC", None
        return "Segurar BTC", round(vs[j]["c"] / vs[i]["o"] - 1, 5)
