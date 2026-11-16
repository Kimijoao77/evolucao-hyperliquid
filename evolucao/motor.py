"""O motor: leva a população inteira de onde parou até agora, vira a geração quando chega a hora e grava tudo.

Só anda para a frente. A primeira geração começa no instante da primeira rodada, com todo mundo zerado, e o
resultado de um robô é só o que acontece depois que ele nasceu. O passado entra de um jeito só: na ficha de cada
TRADER (o que ele já tinha feito até o instante em que o robô escolhe).

Ciclo de uma rodada (a cada 2 horas, no GitHub Actions):
    coleta (coletor.py) → este motor → dados/estado.json + dados/evolucao.json (o app lê)
Na virada de geração também grava memoria/geracao-NNNN.json: DNA, parentesco, medidas e motivo de saída de cada
robô. Nada é ressuscitado sozinho; a memória serve para estudar e para comparar.
"""
from __future__ import annotations

import bisect
import random
from statistics import median

from . import DIA, HORA, MINUTO
from . import dados as D
from . import robo as R
from .coletor import curto
from .dna import ESPECIES, GENES, BotDNA
from .mercado import PrecosVivos
from .populacao import Population, atualizar_linhagem, linhagem_para_app
from .predador import Predator
from .traders import Traders

VERSAO = 1
MAX_EVENTOS = 80


def _med(xs: list[float]) -> float | None:
    return round(median(xs), 5) if xs else None


class EvolutionEngine:
    def __init__(self, cfg: dict, api=None, agora: int | None = None, precos=None, raiz=None, ler_radar=None):
        self.cfg, self.api = cfg, api
        self.agora = agora or D.agora_ms()
        self.ate = (self.agora // MINUTO - 3) * MINUTO                # só velas já fechadas
        self.precos = precos
        self.raiz = raiz or D.RAIZ
        self.ler_radar = ler_radar
        self.amb = dict(cfg["ambiente"])
        self.amb_e = {**self.amb, **cfg["estresse"]}
        self.predador = Predator(cfg["limites"], cfg.get("nota"))
        self.log: list[str] = []

    # ---------------------------------------------------------------- rodada
    def rodar(self) -> dict:
        cfg = self.cfg
        uni = D.ler_json(D.pasta() / "universo.json", {"carteiras": {}, "fila": []})
        cart = uni.get("carteiras", {})
        ativas = sorted(a for a, c in cart.items() if c["situacao"] == "ativa")
        arq = D.pasta() / "estado.json"
        est = D.ler_json(arq, {})
        if est and est.get("versao") != VERSAO:
            raise RuntimeError(f"estado na versão {est.get('versao')}, o código espera {VERSAO}: migre antes de rodar")
        if not est:
            falta = cfg["universo"]["minimo_para_comecar"] - len(ativas)
            if falta > 0 and uni.get("fila"):
                saida = {"gerado": self.agora, "gerado_txt": D.texto_de(self.agora), "fase": "montando",
                         "universo": self._universo(uni, {}), "falta": falta}
                D.gravar_json(D.pasta() / "evolucao.json", saida)
                self.log.append(f"montando o universo: {len(ativas)} carteiras ativas, faltam {falta} para começar")
                return saida
            inicio = self.ate // HORA * HORA
            pop = Population.inicial(cfg, random.Random(f"{cfg['semente']}-fundadores"), inicio)
            est = {"versao": VERSAO, "inicio": inicio, "ate": inicio, "proximo": pop.proximo, "robos": pop.robos,
                   "geracao": {"n": 1, "inicio": inicio, "fim": inicio + cfg["geracao"]["dias"] * DIA},
                   "curva": [], "historia": [], "eventos": []}
            self._evento(est, inicio, "inicio", f"A evolução começou: {len(pop.robos)} robôs fundadores, todos com US$ {self.amb['capital']:.0f} de mentira.")
        pop = Population(est["robos"], est["proximo"], cfg)
        atualizar_linhagem(est.setdefault("linhagem", {}), pop.robos, BotDNA)

        fills = {w: D.ler_fills(w) for w in ativas}
        fotos = D.ler_fotos()
        traders = Traders(fills, fotos, cfg["universo"], {w: cart[w].get("conta_ref") for w in ativas})
        precos = self.precos or PrecosVivos(self.api, self.agora, self.ate)
        mundo = R.Mundo(precos, traders, fills, fotos, ativas, cfg["limites"], self.predador)
        self.mundo = mundo
        estatico = self._estatico()

        ultimo = est["ate"]
        marcos = list(range((ultimo // HORA + 1) * HORA, self.ate, HORA)) + [self.ate]
        for marco in marcos:
            if marco <= ultimo:
                continue
            for r in pop.robos:
                for chave, amb in (("n", self.amb), ("e", self.amb_e)):
                    conta = r[chave]
                    vivo = conta["vivo"]
                    R.avancar(conta, r["dna"], amb, mundo, marco)
                    if vivo and not conta["vivo"] and chave == "n":
                        self._evento(est, conta.get("morreu_em", marco), "abate", f"{r['id']} ({ESPECIES[r['especie']]['nome']}) foi {conta['morte']}.")
            ger = est["geracao"]
            est["curva"].append([marco, _med(self._retornos(pop, "evoluido")), _med(self._retornos(pop, "sorteio")),
                                 self._retorno_estatico(estatico, ger["inicio"], marco)])
            if marco >= ger["fim"]:
                self._virar(est, pop, mundo, marco, estatico)
        est["ate"] = self.ate
        atualizar_linhagem(est["linhagem"], pop.robos, BotDNA)
        est["robos"], est["proximo"] = pop.robos, pop.proximo
        est["eventos"] = est["eventos"][-MAX_EVENTOS:]
        D.gravar_json(arq, est)
        saida = self._saida(est, pop, mundo, uni, estatico)
        D.gravar_json(D.pasta() / "evolucao.json", saida)
        g = est["geracao"]
        self.log.append(f"geração {g['n']}: {len(pop.robos)} robôs, evoluídos {self._pct(saida['resumo']['evoluidos'])}, "
                        f"sorteio {self._pct(saida['resumo']['sorteio'])}, {saida['resumo']['operando']} operando; "
                        f"sem preço: {len(getattr(precos, 'falhas', {}))}")
        return saida

    @staticmethod
    def _pct(x) -> str:
        return "sem dado" if x is None else f"{100 * x:+.2f} %"

    def _evento(self, est: dict, t: int, tipo: str, texto: str) -> None:
        est["eventos"].append({"t": t, "tipo": tipo, "texto": texto})

    @staticmethod
    def _retornos(pop: Population, grupo: str) -> list[float]:
        return [r["n"]["pat"] / r["n"]["base"] - 1 for r in pop.robos if r["grupo"] == grupo and r["n"]["base"] > 0]

    # ---------------------------------------------------------------- comparação com o robô estático do radar
    def _estatico(self) -> list | None:
        """A curva do "Copy trading" do radar (o robô de regras fixas), para comparar no mesmo período."""
        if not self.ler_radar:
            return None
        try:
            v = self.ler_radar("copia_fiel.json")["variantes"]["seletiva"]
            return v["curva"]
        except Exception as e:  # noqa: BLE001
            self.log.append(f"não li a cópia do radar: {str(e)[:100]}")
            return None

    @staticmethod
    def _retorno_estatico(curva: list | None, de: int, ate: int) -> float | None:
        if not curva:
            return None
        ts = [p[0] for p in curva]
        i, j = bisect.bisect_right(ts, de) - 1, bisect.bisect_right(ts, ate) - 1
        if i < 0 or j < 0 or ate - ts[j] > 6 * HORA or ts[i] > de:
            return None
        return round((1 + curva[j][1]) / (1 + curva[i][1]) - 1, 5)

    # ---------------------------------------------------------------- virada de geração
    def _virar(self, est: dict, pop: Population, mundo: R.Mundo, t: int, estatico) -> None:
        ger = est["geracao"]
        g = ger["n"]
        medidas = pop.medir(mundo, self.predador, t)
        antes = [{"id": r["id"], "especie": r["especie"], "grupo": r["grupo"], "dna": dict(r["dna"]),
                  "nasc": r["nasc"], "origem": r["origem"], "pais": r["pais"], "mudou": r.get("mudou", []),
                  "medidas": medidas[r["id"]], "copiava": sorted(r["n"]["subs"])} for r in pop.robos]
        rel = pop.virar(g, medidas, self.predador, random.Random(f"{self.cfg['semente']}-geracao-{g}"), t, mundo)
        atualizar_linhagem(est["linhagem"], pop.robos, BotDNA, rel["saiu"], g)
        estados = {r["id"]: r for r in pop.robos}
        saiu = {s["id"]: s["motivo"] for s in rel["saiu"]}
        for a in antes:
            r = estados.get(a["id"])
            a["estado"] = r["estado"] if r else "saiu"
            a["aptidao"] = r.get("aptidao") if r else next(s["aptidao"] for s in rel["saiu"] if s["id"] == a["id"])
            if a["id"] in saiu:
                a["saiu"] = saiu[a["id"]]
        evo = [m for a in antes if a["grupo"] == "evoluido" for m in [a["medidas"]]]
        sor = [m for a in antes if a["grupo"] == "sorteio" for m in [a["medidas"]]]
        resumo = {"g": g, "inicio": ger["inicio"], "fim": t,
                  "evoluidos": _med([m["r"] for m in evo]), "sorteio": _med([m["r"] for m in sor]),
                  "nota_evoluidos": _med([m["nota"] for m in evo]), "nota_sorteio": _med([m["nota"] for m in sor]),
                  "melhor": max((m["r"] for m in evo), default=None),
                  "estatico": self._retorno_estatico(estatico, ger["inicio"], t),
                  "abatidos": sum(1 for a in antes if a["medidas"]["morte"]),
                  "saiu": len(rel["saiu"]), "nasceu": len(rel["nasceu"]),
                  "filhos": sum(1 for n in rel["nasceu"] if n["origem"] in ("filho", "mutante")),
                  "selecionados": sum(1 for r in pop.robos if r["estado"] == "selecionada"),
                  "confirmados": sum(1 for r in pop.robos if r["estado"] == "confirmada")}
        est["historia"].append(resumo)
        D.gravar_json(self.raiz / "memoria" / f"geracao-{g:04d}.json",
                      {"geracao": g, "inicio": ger["inicio"], "fim": t, "inicio_txt": D.texto_de(ger["inicio"]),
                       "fim_txt": D.texto_de(t), "ambiente": self.amb, "estresse": self.cfg["estresse"],
                       "limites": self.cfg["limites"], "resumo": resumo, "corte_sorteio": rel["corte_sorteio"],
                       "robos": antes, "nasceu": rel["nasceu"], "saiu": rel["saiu"]}, compacto=False)
        self._evento(est, t, "geracao", f"Geração {g} fechou: saíram {resumo['saiu']} robôs ({resumo['abatidos']} abatidos), "
                     f"nasceram {resumo['nasceu']} ({resumo['filhos']} filhos de confirmados). "
                     f"{resumo['confirmados']} confirmados, {resumo['selecionados']} selecionados.")
        est["geracao"] = {"n": g + 1, "inicio": t, "fim": t + self.cfg["geracao"]["dias"] * DIA}
        est["curva"] = []
        self.log.append(f"virou a geração {g}: saíram {resumo['saiu']}, nasceram {resumo['nasceu']}, confirmados {resumo['confirmados']}")

    # ---------------------------------------------------------------- o que o app lê
    def _universo(self, uni: dict, copiados: dict[str, int]) -> dict:
        cart = uni.get("carteiras", {})
        cont: dict[str, int] = {}
        for c in cart.values():
            cont[c["situacao"]] = cont.get(c["situacao"], 0) + 1
        mais = sorted(copiados.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
        return {"ativas": cont.get("ativa", 0), "paradas": cont.get("parada", 0), "quebraram": cont.get("quebrou", 0),
                "recusadas": cont.get("recusada", 0), "fila": len(uni.get("fila", [])),
                "coleta": uni.get("ultima", {}),
                "mais_copiados": [{"trader": cart.get(w, {}).get("apelido") or curto(w), "robos": n} for w, n in mais]}

    def _saida(self, est: dict, pop: Population, mundo: R.Mundo, uni: dict, estatico) -> dict:
        cfg, ger, t = self.cfg, est["geracao"], self.ate
        medidas = pop.medir(mundo, self.predador, t)
        cart = uni.get("carteiras", {})
        nome = lambda w: cart.get(w, {}).get("apelido") or curto(w)  # noqa: E731
        copiados: dict[str, int] = {}
        robos = []
        for r in pop.robos:
            n, m = r["n"], medidas[r["id"]]
            if r["grupo"] == "evoluido":
                for w in n["subs"]:
                    copiados[w] = copiados.get(w, 0) + 1
            situacao = ("abatido" if m["morte"] else "descansando" if n["descanso_ate"] else
                        "operando" if n["subs"] else "sem trader")
            robos.append({"id": r["id"], "especie": r["especie"], "grupo": r["grupo"], "estado": r["estado"],
                          "situacao": situacao, "nasc": r["nasc"], "origem": r["origem"], "pais": r["pais"],
                          "dna": r["dna"], "u": BotDNA(r["especie"], r["dna"]).blocos_u(),
                          **{k: m[k] for k in ("r", "re", "queda", "sm", "ordens", "nota", "morte")},
                          "total": round(n["pat"] / cfg["ambiente"]["capital"] - 1, 5),
                          "aptidao": r.get("aptidao"), "copia": [nome(w) for w in sorted(n["subs"])],
                          "caixa": round(n["caixa"] / n["pat"], 3) if n["pat"] > 0 else 1.0,
                          "hist": [{"g": h["g"], "r": h["r"], "nota": h["nota"], "ok": h["ok"]} for h in r["hist"][-6:]]})
        robos.sort(key=lambda x: (-x["nota"], x["id"]))
        especies = []
        for esp, e in ESPECIES.items():
            evo = [r for r in pop.robos if r["especie"] == esp and r["grupo"] == "evoluido"]
            sor = [r for r in pop.robos if r["especie"] == esp and r["grupo"] == "sorteio"]
            dnas = [BotDNA(esp, r["dna"]) for r in evo]
            dist = [a.distancia(b) for i, a in enumerate(dnas) for b in dnas[i + 1:]]
            conj = [set(r["n"]["subs"]) for r in evo if r["n"]["subs"]]
            igual = [len(a & b) / len(a | b) for i, a in enumerate(conj) for b in conj[i + 1:]]
            especies.append({"id": esp, "nome": e["nome"], "descricao": e["descricao"], "robos": len(evo),
                             "evoluidos": _med([medidas[r["id"]]["r"] for r in evo]),
                             "sorteio": _med([medidas[r["id"]]["r"] for r in sor]),
                             "melhor": max((medidas[r["id"]]["r"] for r in evo), default=None),
                             "operando": sum(1 for r in evo if r["n"]["subs"]),
                             "confirmados": sum(1 for r in evo if r["estado"] == "confirmada"),
                             "selecionados": sum(1 for r in evo if r["estado"] == "selecionada"),
                             "diversidade_dna": round(sum(dist) / len(dist), 3) if dist else None,
                             "mesmos_traders": round(sum(igual) / len(igual), 3) if igual else None})
        evo = [x for x in robos if x["grupo"] == "evoluido"]
        return {
            "gerado": self.agora, "gerado_txt": D.texto_de(self.agora), "fase": "rodando", "versao": VERSAO,
            "inicio": est["inicio"], "ate": t,
            "geracao": {"n": ger["n"], "inicio": ger["inicio"], "fim": ger["fim"], "dias": cfg["geracao"]["dias"],
                        "andou": round(min(1.0, (t - ger["inicio"]) / (ger["fim"] - ger["inicio"])), 4)},
            "resumo": {"robos": len(robos), "evoluidos": _med([x["r"] for x in evo]),
                       "sorteio": _med([x["r"] for x in robos if x["grupo"] == "sorteio"]),
                       "estatico": self._retorno_estatico(estatico, ger["inicio"], t),
                       "melhor": max((x["r"] for x in evo), default=None),
                       "operando": sum(1 for x in evo if x["situacao"] == "operando"),
                       "sem_trader": sum(1 for x in evo if x["situacao"] == "sem trader"),
                       "descansando": sum(1 for x in evo if x["situacao"] == "descansando"),
                       "abatidos": sum(1 for x in evo if x["situacao"] == "abatido"),
                       "confirmados": sum(1 for x in evo if x["estado"] == "confirmada"),
                       "selecionados": sum(1 for x in evo if x["estado"] == "selecionada")},
            "especies": especies, "robos": robos, "curva": est["curva"][-400:], "historia": est["historia"][-60:],
            "blocos": list(BotDNA.BLOCOS), "linhagem": linhagem_para_app(est["linhagem"], ger["n"]),
            "eventos": est["eventos"][-30:][::-1], "universo": self._universo(uni, copiados),
            "ambiente": self.amb, "estresse": cfg["estresse"], "limites": cfg["limites"],
            "regras": {"min_ordens": cfg["geracao"]["min_ordens"], "troca": cfg["geracao"]["troca"],
                       "genes": {k: {"bloco": g["bloco"]} for k, g in GENES.items()}},
            "sem_preco": getattr(mundo.precos, "falhas", {}),
        }
