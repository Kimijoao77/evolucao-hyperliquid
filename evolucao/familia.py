"""O motor das famílias que recalculam a conta inteira desde o nascimento (robôs de preço; depois cofres, pools e
moedas novas). As regras de evolução são as mesmas do copy trading: espécies com vagas garantidas, grupo de sorteio,
Predador, aprovação em duas gerações seguidas, filhos só de confirmados (populacao.py e predador.py).

O que muda é a conta: aqui um robô não guarda carteira entre uma rodada e outra. A cada rodada a família refaz a vida
de cada robô desde o nascimento (as velas fechadas não mudam, então o passado dá sempre o mesmo resultado) e as
medidas de cada geração saem dessa curva.

Uma família diz:
    id, titulo, dna                  quem é e qual é o DNA
    preparar(api, agora, desde)      busca os dados de mercado que faltam (devolve False se não deu para rodar)
    viver(robo, ate, estresse)       a vida do robô: {"pts", "eq", "ops", "morte", "morreu_em", "descanso_ate", ...}
    medir(vida, de, ate)             {"r", "queda", "sm", "ordens"} na geração
    nome(robo)                       o robô numa linha, para o app
    regua(de, ate)                   (nome, retorno) da régua de fora no mesmo período (por exemplo, segurar BTC)
"""
from __future__ import annotations

import bisect
import random
from statistics import median

from . import DIA, HORA
from . import dados as D
from .populacao import Population
from .predador import Predator

VERSAO = 1
MAX_EVENTOS = 80
PONTOS_CURVA = 240


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(median(xs), 5) if xs else None


class MotorRecalculo:
    def __init__(self, cfg: dict, familia, agora: int, api=None, raiz=None):
        self.fam, self.api, self.agora = familia, api, agora
        fc = (cfg.get("familias") or {}).get(familia.id, {})
        self.cfg = {**cfg, "geracao": {**cfg["geracao"], **fc.get("geracao", {})}}
        self.capital = cfg["ambiente"]["capital"]
        self.ate = agora // HORA * HORA                       # só horas fechadas
        self.raiz = raiz or D.RAIZ
        self.predador = Predator(cfg["limites"], cfg.get("nota"))
        self.log: list[str] = []

    # ---------------------------------------------------------------- arquivos
    def _arq_estado(self):
        return D.pasta() / self.fam.id / "estado.json"

    def _arq_saida(self):
        return D.pasta() / f"{self.fam.id}.json"

    # ---------------------------------------------------------------- rodada
    def rodar(self) -> dict:
        cfg, fam = self.cfg, self.fam
        est = D.ler_json(self._arq_estado(), {})
        if est and est.get("versao") != VERSAO:
            raise RuntimeError(f"{fam.id}: estado na versão {est.get('versao')}, o código espera {VERSAO}")
        novo = not est
        inicio = est.get("inicio") or self.ate
        desde = min([r["t0"] for r in est.get("robos", [])] + [inicio])
        if not fam.preparar(self.api, self.agora, desde, self.log):    # (a família busca o que falta de mercado)
            self.log.append(f"{fam.id}: sem dados de mercado, a rodada ficou para depois")
            return D.ler_json(self._arq_saida(), {})
        if novo:
            pop = Population.inicial(cfg, random.Random(f"{cfg['semente']}-{fam.id}-fundadores"), inicio, fam)
            est = {"versao": VERSAO, "inicio": inicio, "proximo": pop.proximo, "robos": pop.robos,
                   "geracao": {"n": 1, "inicio": inicio, "fim": inicio + cfg["geracao"]["dias"] * DIA},
                   "historia": [], "eventos": []}
            self._evento(est, inicio, "inicio", f"{fam.titulo}: a evolução começou com {len(pop.robos)} robôs fundadores, "
                         f"todos com US$ {self.capital:.0f} de mentira.")
        pop = Population(est["robos"], est["proximo"], cfg, fam)

        while est["geracao"]["fim"] <= self.ate:                  # gerações que fecharam desde a última rodada
            self._virar(est, pop, est["geracao"]["fim"])
        vidas = self._vidas(pop, self.ate)
        self._abates(est, pop, vidas)
        est["robos"], est["proximo"] = pop.robos, pop.proximo
        est["eventos"] = est["eventos"][-MAX_EVENTOS:]
        D.gravar_json(self._arq_estado(), est)
        saida = self._saida(est, pop, vidas)
        D.gravar_json(self._arq_saida(), saida)
        r = saida["resumo"]
        self.log.append(f"{fam.id}: geração {est['geracao']['n']}, {len(pop.robos)} robôs, evoluídos {self._pct(r['evoluidos'])}, "
                        f"sorteio {self._pct(r['sorteio'])}, {r['regua_nome']} {self._pct(r['regua'])}")
        return saida

    @staticmethod
    def _pct(x) -> str:
        return "sem dado" if x is None else f"{100 * x:+.2f} %"

    def _evento(self, est: dict, t: int, tipo: str, texto: str) -> None:
        est["eventos"].append({"t": t, "tipo": tipo, "texto": texto})

    def _vidas(self, pop: Population, ate: int) -> dict:
        return {r["id"]: (self.fam.viver(r, ate, False), self.fam.viver(r, ate, True)) for r in pop.robos}

    def _medidas(self, pop: Population, vidas: dict, de: int, ate: int) -> dict:
        out = {}
        for r in pop.robos:
            vn, ve = vidas[r["id"]]
            ini = max(de, r["t0"])
            mn, me = self.fam.medir(vn, ini, ate), self.fam.medir(ve, ini, ate)
            morte = vn["morte"] or (f"no estresse, {ve['morte']}" if ve["morte"] else None)
            nota = self.predador.nota(mn["r"], me["r"], mn["queda"], mn["sm"], mn["ordens"])
            out[r["id"]] = {"r": round(mn["r"], 5), "re": round(me["r"], 5), "queda": round(mn["queda"], 5),
                            "sm": round(mn["sm"], 5), "ordens": mn["ordens"], "nota": round(nota, 5), "morte": morte,
                            "freios": sum(1 for t in vn["freios"] if de < t <= ate)}
        return out

    def _abates(self, est: dict, pop: Population, vidas: dict) -> None:
        for r in pop.robos:
            vn = vidas[r["id"]][0]
            if vn["morte"] and not r.get("morte"):
                r["morte"] = vn["morte"]
                esp = pop.especies[r["especie"]]["nome"]
                self._evento(est, vn["morreu_em"], "abate", f"{r['id']} ({esp}, {self.fam.nome(r)}) foi {vn['morte']}.")

    # ---------------------------------------------------------------- virada de geração
    def _virar(self, est: dict, pop: Population, t: int) -> None:
        ger, fam = est["geracao"], self.fam
        g = ger["n"]
        vidas = self._vidas(pop, t)
        self._abates(est, pop, vidas)
        medidas = self._medidas(pop, vidas, ger["inicio"], t)
        antes = [{"id": r["id"], "especie": r["especie"], "grupo": r["grupo"], "dna": dict(r["dna"]), "nome": fam.nome(r),
                  "nasc": r["nasc"], "t0": r["t0"], "origem": r["origem"], "pais": r["pais"], "mudou": r.get("mudou", []),
                  "medidas": medidas[r["id"]]} for r in pop.robos]
        rel = pop.virar(g, medidas, self.predador, random.Random(f"{self.cfg['semente']}-{fam.id}-geracao-{g}"), t)
        estados = {r["id"]: r for r in pop.robos}
        saiu = {s["id"]: s for s in rel["saiu"]}
        for a in antes:
            r = estados.get(a["id"])
            a["estado"] = r["estado"] if r else "saiu"
            a["aptidao"] = r.get("aptidao") if r else saiu[a["id"]]["aptidao"]
            if a["id"] in saiu:
                a["saiu"] = saiu[a["id"]]["motivo"]
        evo = [a["medidas"] for a in antes if a["grupo"] == "evoluido"]
        sor = [a["medidas"] for a in antes if a["grupo"] == "sorteio"]
        rn, rv = fam.regua(ger["inicio"], t)
        resumo = {"g": g, "inicio": ger["inicio"], "fim": t,
                  "evoluidos": _med([m["r"] for m in evo]), "sorteio": _med([m["r"] for m in sor]),
                  "nota_evoluidos": _med([m["nota"] for m in evo]), "nota_sorteio": _med([m["nota"] for m in sor]),
                  "melhor": max((m["r"] for m in evo), default=None), "regua": rv, "regua_nome": rn,
                  "abatidos": sum(1 for a in antes if a["medidas"]["morte"]),
                  "saiu": len(rel["saiu"]), "nasceu": len(rel["nasceu"]),
                  "filhos": sum(1 for n in rel["nasceu"] if n["origem"] in ("filho", "mutante")),
                  "selecionados": sum(1 for r in pop.robos if r["estado"] == "selecionada"),
                  "confirmados": sum(1 for r in pop.robos if r["estado"] == "confirmada")}
        est["historia"].append(resumo)
        D.gravar_json(self.raiz / "memoria" / fam.id / f"geracao-{g:04d}.json",
                      {"familia": fam.id, "geracao": g, "inicio": ger["inicio"], "fim": t, "inicio_txt": D.texto_de(ger["inicio"]),
                       "fim_txt": D.texto_de(t), "limites": self.cfg["limites"], "resumo": resumo,
                       "corte_sorteio": rel["corte_sorteio"], "robos": antes, "nasceu": rel["nasceu"], "saiu": rel["saiu"]},
                      compacto=False)
        self._evento(est, t, "geracao", f"{fam.titulo}: a geração {g} fechou. Saíram {resumo['saiu']} robôs ({resumo['abatidos']} abatidos), "
                     f"nasceram {resumo['nasceu']} ({resumo['filhos']} filhos de confirmados). "
                     f"{resumo['confirmados']} confirmados, {resumo['selecionados']} selecionados.")
        est["geracao"] = {"n": g + 1, "inicio": t, "fim": t + self.cfg["geracao"]["dias"] * DIA}
        self.log.append(f"{fam.id}: virou a geração {g}: saíram {resumo['saiu']}, nasceram {resumo['nasceu']}, confirmados {resumo['confirmados']}")

    # ---------------------------------------------------------------- o que o app lê
    def _curva(self, pop: Population, vidas: dict, de: int, ate: int) -> list:
        """[t, mediana dos evoluídos, mediana do sorteio, régua], do começo da geração até agora."""
        passo = max(HORA, -(-(ate - de) // PONTOS_CURVA) // HORA * HORA)
        out = []
        for t in list(range(de, ate, passo)) + [ate]:
            linha = [t]
            for grupo in ("evoluido", "sorteio"):
                rs = []
                for r in pop.robos:
                    if r["grupo"] != grupo or r["t0"] > de:
                        continue
                    v = vidas[r["id"]][0]
                    b = valor_em(v, de)
                    rs.append(valor_em(v, t) / b - 1 if b > 0 else None)
                linha.append(_med(rs))
            linha.append(self.fam.regua(de, t)[1])
            out.append(linha)
        return out

    def _saida(self, est: dict, pop: Population, vidas: dict) -> dict:
        cfg, ger, t, fam = self.cfg, est["geracao"], self.ate, self.fam
        medidas = self._medidas(pop, vidas, ger["inicio"], t)
        robos = []
        for r in pop.robos:
            vn, m = vidas[r["id"]][0], medidas[r["id"]]
            situacao = ("abatido" if vn["morte"] else vn.get("situacao") or ("descansando" if vn["descanso_ate"] and vn["descanso_ate"] > t
                        else "operando" if vn["pts"] else "esperando"))
            robos.append({"id": r["id"], "especie": r["especie"], "grupo": r["grupo"], "estado": r["estado"],
                          "situacao": situacao, "nasc": r["nasc"], "origem": r["origem"], "pais": r["pais"],
                          "nome": fam.nome(r), "dna": r["dna"],
                          **{k: m[k] for k in ("r", "re", "queda", "sm", "ordens", "nota", "morte", "freios")},
                          "total": round((vn["eq"][-1] if vn["eq"] else self.capital) / self.capital - 1, 5),
                          "aptidao": r.get("aptidao"), **(fam.detalhe(r, vn) if hasattr(fam, "detalhe") else {}),
                          "hist": [{"g": h["g"], "r": h["r"], "nota": h["nota"], "ok": h["ok"]} for h in r["hist"][-6:]]})
        robos.sort(key=lambda x: (-x["nota"], x["id"]))
        especies = []
        for esp, e in pop.especies.items():
            evo = [x for x in robos if x["especie"] == esp and x["grupo"] == "evoluido"]
            sor = [x for x in robos if x["especie"] == esp and x["grupo"] == "sorteio"]
            dnas = [fam.dna(esp, x["dna"]) for x in evo]
            dist = [a.distancia(b) for i, a in enumerate(dnas) for b in dnas[i + 1:]]
            especies.append({"id": esp, "nome": e["nome"], "descricao": e["descricao"], "robos": len(evo),
                             "evoluidos": _med([x["r"] for x in evo]), "sorteio": _med([x["r"] for x in sor]),
                             "melhor": max((x["r"] for x in evo), default=None),
                             "operando": sum(1 for x in evo if x["situacao"] == "operando"),
                             "confirmados": sum(1 for x in evo if x["estado"] == "confirmada"),
                             "selecionados": sum(1 for x in evo if x["estado"] == "selecionada"),
                             "diversidade_dna": round(sum(dist) / len(dist), 3) if dist else None})
        evo = [x for x in robos if x["grupo"] == "evoluido"]
        rn, rv = fam.regua(ger["inicio"], t)
        return {
            "familia": fam.id, "titulo": fam.titulo, "gerado": self.agora, "gerado_txt": D.texto_de(self.agora),
            "fase": "rodando", "versao": VERSAO, "inicio": est["inicio"], "ate": t,
            "geracao": {"n": ger["n"], "inicio": ger["inicio"], "fim": ger["fim"], "dias": cfg["geracao"]["dias"],
                        "andou": round(min(1.0, max(0.0, (t - ger["inicio"]) / (ger["fim"] - ger["inicio"]))), 4)},
            "resumo": {"robos": len(robos), "evoluidos": _med([x["r"] for x in evo]),
                       "sorteio": _med([x["r"] for x in robos if x["grupo"] == "sorteio"]),
                       "regua": rv, "regua_nome": rn, "melhor": max((x["r"] for x in evo), default=None),
                       "operando": sum(1 for x in evo if x["situacao"] == "operando"),
                       "descansando": sum(1 for x in evo if x["situacao"] == "descansando"),
                       "no_caixa": sum(1 for x in evo if x["situacao"] in ("no caixa", "esperando moeda")),
                       "abatidos": sum(1 for x in evo if x["situacao"] == "abatido"),
                       "confirmados": sum(1 for x in evo if x["estado"] == "confirmada"),
                       "selecionados": sum(1 for x in evo if x["estado"] == "selecionada")},
            "especies": especies, "robos": robos, "curva": self._curva(pop, vidas, ger["inicio"], t),
            "historia": est["historia"][-60:], "eventos": est["eventos"][-30:][::-1],
            "limites": cfg["limites"], "regras": {"min_ordens": cfg["geracao"]["min_ordens"], "troca": cfg["geracao"]["troca"],
                                                  "genes": {k: {"bloco": g["bloco"]} for k, g in fam.dna.GENES.items()}},
            "explica": fam.explica,
        }


def valor_em(v: dict, t: int) -> float:
    """O patrimônio de uma vida no instante t (o último ponto até t; antes do primeiro, o capital)."""
    j = bisect.bisect_right(v["pts"], t)
    return v["eq"][j - 1] if j else v["capital"]
