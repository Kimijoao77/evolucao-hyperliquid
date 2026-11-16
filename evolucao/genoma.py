"""O DNA genérico de qualquer família de robôs: genes com faixa, agrupados em blocos, e espécies que apertam faixas.

Cada família (copy trading, robôs de preço, cofres...) é uma subclasse que diz quais são os seus GENES, BLOCOS e
ESPECIES. As regras de sortear, cruzar, mutar e comparar são as mesmas para todas.

Uma espécie pode dizer quais genes USA (`genes`). Os outros continuam no DNA (servem num cruzamento com outra espécie)
mas não contam na mutação nem na distância: mudar um gene que o robô nem usa não explora nada.
"""
from __future__ import annotations

import math
import random

CHANCE_DESLIGADO = 0.4          # no sorteio, chance de um gene que pode ser desligado nascer desligado


class Genoma:
    GENES: dict[str, dict] = {}
    BLOCOS: tuple[str, ...] = ()
    ESPECIES: dict[str, dict] = {}

    def __init__(self, especie: str, genes: dict | None = None):
        self.especie = especie
        self.genes = genes if genes is not None else {}

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.especie!r}, {self.genes!r})"

    def __eq__(self, outro) -> bool:
        return type(self) is type(outro) and self.especie == outro.especie and self.genes == outro.genes

    # ---------- faixas
    @classmethod
    def teto(cls, gene: str, b: float, limites: dict | None) -> float:
        """Para a família apertar uma faixa com um limite duro do config (por padrão, nada)."""
        return b

    @classmethod
    def faixa(cls, gene: str, especie: str, limites: dict | None = None) -> tuple:
        a, b = cls.ESPECIES[especie].get("faixas", {}).get(gene, cls.GENES[gene]["faixa"])
        return a, cls.teto(gene, b, limites)

    @classmethod
    def ativos(cls, especie: str) -> list[str]:
        usa = cls.ESPECIES[especie].get("genes")
        return [n for n in cls.GENES if not usa or n in usa]

    @classmethod
    def _arredondar(cls, gene: str, x: float):
        if cls.GENES[gene]["tipo"] == "int":
            return int(round(x))
        return float(f"{x:.3g}")

    @classmethod
    def _posicao(cls, gene: str, valor, especie: str) -> float:
        """Onde o valor cai na faixa, de 0 a 1 (em escala log quando o gene pede)."""
        a, b = cls.faixa(gene, especie)
        if cls.GENES[gene].get("log"):
            return (math.log(valor) - math.log(a)) / (math.log(b) - math.log(a))
        return (valor - a) / (b - a) if b > a else 0.0

    @classmethod
    def _da_posicao(cls, gene: str, u: float, especie: str, limites: dict | None):
        a, b = cls.faixa(gene, especie, limites)
        u = min(1.0, max(0.0, u))
        if cls.GENES[gene].get("log"):
            x = math.exp(math.log(a) + u * (math.log(b) - math.log(a)))
        else:
            x = a + u * (b - a)
        return min(b, max(a, cls._arredondar(gene, x)))

    @classmethod
    def _opcoes(cls, gene: str, especie: str) -> tuple:
        return cls.ESPECIES[especie].get("opcoes", {}).get(gene, cls.GENES[gene]["opcoes"])

    # ---------- criação
    @classmethod
    def sortear(cls, especie: str, rng: random.Random, limites: dict | None = None):
        genes = {}
        for nome, g in cls.GENES.items():
            if g["tipo"] == "opcao":
                genes[nome] = rng.choice(cls._opcoes(nome, especie))
            elif g.get("desliga") and rng.random() < CHANCE_DESLIGADO:
                genes[nome] = 0
            else:
                genes[nome] = cls._da_posicao(nome, rng.random(), especie, limites)
        return cls(especie, genes)

    @classmethod
    def cruzar(cls, pai, mae, rng: random.Random, limites: dict | None = None):
        """O filho herda cada BLOCO inteiro de um dos pais (o filtro de um, a gestão de risco do outro...).
        Pelo menos um bloco vem de cada um. A espécie é a do pai; o que vier da mãe é encaixado nas faixas dela."""
        while True:
            de = {b: rng.random() < 0.5 for b in cls.BLOCOS}
            if len(set(de.values())) == 2:
                break
        genes = {n: (pai if de[g["bloco"]] else mae).genes[n] for n, g in cls.GENES.items()}
        filho = cls(pai.especie, genes)
        filho.encaixar(limites)
        return filho

    def mutar(self, rng: random.Random, chance: float, forca: float, limites: dict | None = None) -> list[str]:
        """Cada gene que a espécie usa tem `chance` de mudar: um passo de tamanho `forca` (fração da faixa) para um
        lado. Devolve o que mudou. Se nada mudar, um gene é forçado: filho idêntico não explora nada."""
        mudou = []
        nomes = self.ativos(self.especie)
        for nome in nomes:
            if rng.random() < chance and self._mutar_gene(nome, rng, forca, limites):
                mudou.append(nome)
        for _ in range(50):
            if mudou:
                break
            nome = rng.choice(nomes)
            if self._mutar_gene(nome, rng, forca, limites):
                mudou.append(nome)
        return mudou

    def _mutar_gene(self, nome: str, rng: random.Random, forca: float, limites: dict | None) -> bool:
        g, antes = self.GENES[nome], self.genes[nome]
        if g["tipo"] == "opcao":
            outras = [o for o in self._opcoes(nome, self.especie) if o != antes]
            if not outras:
                return False
            self.genes[nome] = rng.choice(outras)
            return True
        if g.get("desliga") and rng.random() < 0.15:      # liga ou desliga
            self.genes[nome] = self._da_posicao(nome, rng.random(), self.especie, limites) if antes == 0 else 0
            return True
        if antes == 0:
            return False
        u = self._posicao(nome, antes, self.especie) + rng.gauss(0.0, forca)
        self.genes[nome] = self._da_posicao(nome, u, self.especie, limites)
        if self.genes[nome] == antes and g["tipo"] == "int":   # passo pequeno demais para um inteiro: anda 1
            a, b = self.faixa(nome, self.especie, limites)
            self.genes[nome] = min(b, max(a, antes + rng.choice((-1, 1))))
        return self.genes[nome] != antes

    def encaixar(self, limites: dict | None = None) -> None:
        """Traz cada gene para dentro das faixas e das opções da espécie e dos limites duros."""
        for nome, g in self.GENES.items():
            v = self.genes[nome]
            if g["tipo"] == "opcao":
                ops = self._opcoes(nome, self.especie)
                if v not in ops:
                    self.genes[nome] = ops[0]
                continue
            if g.get("desliga") and v == 0:
                continue
            a, b = self.faixa(nome, self.especie, limites)
            self.genes[nome] = self._arredondar(nome, min(b, max(a, v)))

    # ---------- comparação
    def distancia(self, outro) -> float:
        """De 0 (idênticos) a 1: a média das diferenças gene a gene (só os genes que a espécie usa), cada uma na
        escala da faixa inteira do gene."""
        nomes = self.ativos(self.especie)
        soma = 0.0
        for nome in nomes:
            g = self.GENES[nome]
            a, b = self.genes[nome], outro.genes[nome]
            if g["tipo"] == "opcao":
                soma += 0.0 if a == b else 1.0
            elif a == 0 or b == 0:
                soma += 0.0 if a == b else 1.0
            else:
                lo, hi = g["faixa"]
                if g.get("log"):
                    soma += abs(math.log(a) - math.log(b)) / (math.log(hi) - math.log(lo))
                else:
                    soma += abs(a - b) / (hi - lo)
        return soma / max(1, len(nomes))

    def blocos_u(self) -> list[list[float]]:
        """O DNA em números de 0 a 1, um grupo por bloco (na ordem de BLOCOS): onde cada gene cai na faixa INTEIRA
        dele (não na da espécie), para o app desenhar o robô. Gene desligado = -1. Como o filho herda blocos inteiros,
        cada bloco vira uma parte do corpo do robô no app: dá para ver de quem ele herdou o quê."""
        out = []
        for b in self.BLOCOS:
            us = []
            for nome, g in self.GENES.items():
                if g["bloco"] != b:
                    continue
                v = self.genes.get(nome)
                if g["tipo"] == "opcao":
                    ops = g["opcoes"]
                    us.append(round(ops.index(v) / max(1, len(ops) - 1), 3) if v in ops else 0.0)
                elif g.get("desliga") and v == 0:
                    us.append(-1)
                else:
                    lo, hi = g["faixa"]
                    try:
                        u = ((math.log(v) - math.log(lo)) / (math.log(hi) - math.log(lo)) if g.get("log")
                             else (v - lo) / (hi - lo))
                    except (ValueError, ZeroDivisionError, TypeError):
                        u = 0.0
                    us.append(round(min(1.0, max(0.0, u)), 3))
            out.append(us)
        return out

    def copia(self):
        return type(self)(self.especie, dict(self.genes))

    def valido(self, limites: dict | None = None) -> bool:
        for nome, g in self.GENES.items():
            v = self.genes.get(nome)
            if g["tipo"] == "opcao":
                if v not in self._opcoes(nome, self.especie):
                    return False
                continue
            if g.get("desliga") and v == 0:
                continue
            a, b = self.faixa(nome, self.especie, limites)
            if v is None or not (a - 1e-9 <= v <= b + 1e-9):
                return False
        return True
