"""A população: espécies com vagas garantidas, o grupo de controle e a virada de geração.

Dois grupos vivem lado a lado, com as mesmas regras e o mesmo dinheiro de mentira:
- EVOLUÍDOS: 10 vagas por espécie. Os confirmados têm filhos (cruzamento + mutação).
- SORTEIO: 3 por espécie, com DNA sorteado, que nunca se reproduz. É o controle: se os evoluídos não ganharem do
  sorteio ao longo das gerações, a evolução não está acrescentando nada.

Na virada de cada geração, em cada espécie:
1. Aprovado é quem ficou na metade de cima da espécie, com nota positiva, operando de verdade (mínimo de ordens) e
   acima da mediana do sorteio. Aprovado uma vez = selecionado. Aprovado em duas gerações SEGUIDAS = confirmado.
2. Saem os abatidos pelo Predador, os que ficaram 3 gerações sem operar e os de pior aptidão, até completar 30 % das
   vagas. Aprovado nunca sai.
3. As vagas abertas são preenchidas:
   - com 2 ou mais confirmados na espécie: filhos (um bloco de genes de cada lado + mutação). De vez em quando a mãe
     vem de outra espécie (migração);
   - com 1 confirmado: mutantes dele;
   - sem confirmado: imigrantes (DNA sorteado). Ninguém vira pai por ser "o menos ruim".
   Havendo 2 vagas ou mais, uma é sempre de imigrante (sangue novo).
4. O DNA fica congelado a vida inteira do robô. Filho é outro robô, com história própria.
"""
from __future__ import annotations

import math
import random
from statistics import median

from . import robo as R
from .dna import ESPECIES, BotDNA
from .predador import Predator


class Population:
    def __init__(self, robos: list[dict], proximo: int, cfg: dict):
        self.robos, self.proximo, self.cfg = robos, proximo, cfg
        self.limites = cfg["limites"]
        self.capital = cfg["ambiente"]["capital"]

    # ---------- nascimento
    def _novo(self, dna: BotDNA, grupo: str, g: int, t: int, origem: str, pais=(), mudou=()) -> dict:
        self.proximo += 1
        r = {"id": f"{ESPECIES[dna.especie]['letra']}{self.proximo}", "especie": dna.especie, "grupo": grupo,
             "dna": dna.genes, "nasc": g, "origem": origem, "pais": list(pais), "mudou": list(mudou),
             "n": R.nova_conta(self.capital, t), "e": R.nova_conta(self.capital, t), "hist": [],
             "estado": "sorteio" if grupo == "sorteio" else "nova", "ociosas": 0}
        self.robos.append(r)
        return r

    @classmethod
    def inicial(cls, cfg: dict, rng: random.Random, t: int) -> "Population":
        pop = cls([], 0, cfg)
        ger = cfg["geracao"]
        for esp in ESPECIES:
            for _ in range(ger["vagas_por_especie"]):
                pop._novo(BotDNA.sortear(esp, rng, pop.limites), "evoluido", 1, t, "fundador")
            for _ in range(ger["sorteio_por_especie"]):
                pop._novo(BotDNA.sortear(esp, rng, pop.limites), "sorteio", 1, t, "sorteio")
        return pop

    def do_grupo(self, especie: str, grupo: str) -> list[dict]:
        return [r for r in self.robos if r["especie"] == especie and r["grupo"] == grupo]

    # ---------- medidas da geração
    def medir(self, mundo: R.Mundo, predador: Predator, t: int) -> dict[str, dict]:
        out = {}
        for r in self.robos:
            n, e = r["n"], r["e"]
            ret = n["pat"] / n["base"] - 1 if n["base"] > 0 else -1.0
            ret_e = e["pat"] / e["base"] - 1 if e["base"] > 0 else -1.0
            res = R.resultado_por_trader(n, mundo, t)
            melhor = max(res.values(), default=0.0)
            sm = (sum(res.values()) - max(0.0, melhor)) / n["base"] if n["base"] > 0 else -1.0
            morte = n["morte"] or (f"no estresse, {e['morte']}" if e["morte"] else None)
            out[r["id"]] = {"r": round(ret, 5), "re": round(ret_e, 5), "queda": round(n["queda"], 5),
                            "sm": round(sm, 5), "ordens": n["ordens"], "traders": len(res),
                            "freios": n["freios"], "paradas": n["paradas"], "expo_max": round(n["expo_max"], 2),
                            "nota": round(predador.nota(ret, ret_e, n["queda"], sm, n["ordens"]), 5),
                            "morte": morte}
        return out

    # ---------- virada de geração
    def virar(self, g: int, medidas: dict, predador: Predator, rng: random.Random, t: int, mundo: R.Mundo) -> dict:
        """Fecha a geração `g`: julga, tira os que saem e põe os que nascem (que começam na geração g + 1)."""
        ger, mut = self.cfg["geracao"], self.cfg["mutacao"]
        notas_sorteio = [medidas[r["id"]]["nota"] for r in self.robos if r["grupo"] == "sorteio"]
        corte_sorteio = median(notas_sorteio) if notas_sorteio else 0.0
        saiu, nasceu = [], []

        # 1. julgamento: aprovado, selecionado, confirmado
        for esp in ESPECIES:
            grupo = sorted(self.do_grupo(esp, "evoluido"), key=lambda r: (-medidas[r["id"]]["nota"], r["id"]))
            metade = math.ceil(len(grupo) / 2)
            for i, r in enumerate(grupo):
                m = medidas[r["id"]]
                ok = (i < metade and not m["morte"] and m["nota"] > 0 and m["ordens"] >= ger["min_ordens"]
                      and m["nota"] > corte_sorteio)
                antes = bool(r["hist"] and r["hist"][-1]["ok"])
                r["hist"].append({"g": g, **{k: m[k] for k in ("r", "re", "queda", "sm", "ordens", "nota")}, "ok": ok})
                r["estado"] = "confirmada" if ok and antes else "selecionada" if ok else "em prova"
                r["ociosas"] = r["ociosas"] + 1 if m["ordens"] == 0 else 0
                r["aptidao"] = round(predador.aptidao([h["nota"] for h in r["hist"]]), 5)
            for r in self.do_grupo(esp, "sorteio"):
                m = medidas[r["id"]]
                r["hist"].append({"g": g, **{k: m[k] for k in ("r", "re", "queda", "sm", "ordens", "nota")}, "ok": False})
                r["aptidao"] = round(predador.aptidao([h["nota"] for h in r["hist"]]), 5)

        confirmados = {esp: [r for r in self.do_grupo(esp, "evoluido") if r["estado"] == "confirmada"]
                       for esp in ESPECIES}

        for esp in ESPECIES:
            # 2. quem sai
            grupo = self.do_grupo(esp, "evoluido")
            sai: dict[str, str] = {}
            for r in grupo:
                if medidas[r["id"]]["morte"]:
                    sai[r["id"]] = medidas[r["id"]]["morte"]
                elif r["ociosas"] >= ger["ociosas_max"]:
                    sai[r["id"]] = f"ficou {r['ociosas']} gerações sem operar"
            trocar = math.ceil(ger["troca"] * ger["vagas_por_especie"])
            fila = sorted((r for r in grupo if r["id"] not in sai and not r["hist"][-1]["ok"]),
                          key=lambda r: (r["aptidao"], r["id"]))
            while len(sai) < trocar and fila:
                sai[fila.pop(0)["id"]] = "ficou entre as de pior aptidão da espécie"
            # 3. quem nasce
            vagas = ger["vagas_por_especie"] - (len(grupo) - len(sai))
            pais = [r for r in confirmados[esp] if r["id"] not in sai]
            de_fora = [r for e2, lista in confirmados.items() if e2 != esp for r in lista]
            vivos = [BotDNA(esp, r["dna"]) for r in grupo if r["id"] not in sai]
            for k in range(vagas):
                if (k == 0 and vagas >= 2) or not pais:
                    dna, origem, quem, mudou = BotDNA.sortear(esp, rng, self.limites), "imigrante", [], []
                elif len(pais) == 1:
                    dna, origem, quem = BotDNA(esp, dict(pais[0]["dna"])), "mutante", [pais[0]["id"]]
                    mudou = dna.mutar(rng, mut["chance"], mut["forca"], self.limites)
                else:
                    pai = self._torneio(pais, rng)
                    if de_fora and rng.random() < mut["migracao"]:
                        mae = self._torneio(de_fora, rng)
                    else:
                        mae = self._torneio([r for r in pais if r is not pai], rng)
                    dna = BotDNA.cruzar(BotDNA(esp, pai["dna"]), BotDNA(mae["especie"], mae["dna"]), rng, self.limites)
                    mudou = dna.mutar(rng, mut["chance"], mut["forca"], self.limites)
                    origem, quem = "filho", [pai["id"], mae["id"]]
                for _ in range(5):                                     # gêmeo de alguém que já existe não explora nada
                    if all(dna.distancia(v) >= 0.02 for v in vivos):
                        break
                    mudou = sorted(set(mudou) | set(dna.mutar(rng, 1.0, mut["forca"], self.limites)))
                vivos.append(dna)
                novo = self._novo(dna, "evoluido", g + 1, t, origem, quem, mudou)
                nasceu.append({"id": novo["id"], "especie": esp, "origem": origem, "pais": quem, "mudou": mudou})
            # o controle troca no mesmo ritmo: saem os abatidos e os mais velhos, entram sorteados novos
            controle = sorted(self.do_grupo(esp, "sorteio"), key=lambda r: (r["nasc"], int(r["id"][1:])))
            sai_c = {r["id"]: medidas[r["id"]]["morte"] for r in controle if medidas[r["id"]]["morte"]}
            trocar_c = math.ceil(ger["troca"] * ger["sorteio_por_especie"])
            for r in controle:
                if len(sai_c) >= trocar_c:
                    break
                sai_c.setdefault(r["id"], "o sorteio renovou (era o mais velho)")
            for _ in range(ger["sorteio_por_especie"] - (len(controle) - len(sai_c))):
                novo = self._novo(BotDNA.sortear(esp, rng, self.limites), "sorteio", g + 1, t, "sorteio")
                nasceu.append({"id": novo["id"], "especie": esp, "origem": "sorteio", "pais": [], "mudou": []})
            sai.update(sai_c)
            for r in [r for r in self.robos if r["id"] in sai]:
                saiu.append({"id": r["id"], "especie": esp, "grupo": r["grupo"], "motivo": sai[r["id"]],
                             "viveu": g - r["nasc"] + 1, "aptidao": r.get("aptidao", 0.0)})
            self.robos = [r for r in self.robos if r["id"] not in sai]

        # 4. quem ficou continua com a mesma conta; só as medidas da geração recomeçam
        for r in self.robos:
            if r["nasc"] <= g:
                R.virar_conta(r["n"], mundo, t)
                R.virar_conta(r["e"], mundo, t)
        return {"saiu": saiu, "nasceu": nasceu, "corte_sorteio": round(corte_sorteio, 5)}

    @staticmethod
    def _torneio(lista: list[dict], rng: random.Random) -> dict:
        """Sorteia dois e fica com o de maior aptidão."""
        a, b = rng.choice(lista), rng.choice(lista)
        return a if (a.get("aptidao", 0), a["id"]) >= (b.get("aptidao", 0), b["id"]) else b
