"""O DNA de um robô de copy trading: 14 genes em 4 blocos.

Cada gene tem uma faixa. Os limites de risco de verdade (exposição máxima, queda que mata) NÃO são genes: ficam no
config.json e nenhum robô consegue mexer neles. O DNA só escolhe dentro do que é permitido.

Bloco      Gene              O que decide
filtro     janela_dias       quantos dias do passado do trader o robô olha
filtro     min_operacoes     mínimo de operações fechadas na janela
filtro     min_fator_lucro   ganhos ÷ perdas mínimo na janela
filtro     duracao_min       tempo mediano mínimo que o trader segura a posição (minutos)
filtro     max_carteiras     quantos traders copia ao mesmo tempo
filtro     criterio          como ordena os aprovados (fator de lucro, retorno ou constância)
alocacao   alvo              exposição típica buscada em cada trader (1 = o saldo, sem alavancagem)
alocacao   revisao_dias      de quantos em quantos dias revê quem copia
risco      parada            queda desde o pico que faz largar um trader
risco      freio             queda do robô inteiro que faz parar tudo e descansar
risco      corte             perda numa posição que faz sair antes do trader (0 = desligado)
risco      ganho             lucro numa posição que faz sair antes do trader (0 = desligado)
risco      tempo_max_h       tempo máximo numa posição (0 = desligado)
execucao   desvio_max        quanto o preço pode ter fugido desde a ordem do trader para ainda entrar

Espécie: um jeito de ser. Cada espécie aperta a faixa de alguns genes e tem vagas garantidas na população, para um
vencedor recente não tomar conta de tudo.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

GENES: dict[str, dict] = {
    "janela_dias": {"bloco": "filtro", "tipo": "int", "faixa": (7, 60)},
    "min_operacoes": {"bloco": "filtro", "tipo": "int", "faixa": (5, 60)},
    "min_fator_lucro": {"bloco": "filtro", "tipo": "real", "faixa": (1.0, 3.0)},
    "duracao_min": {"bloco": "filtro", "tipo": "real", "faixa": (5.0, 240.0), "log": True},
    "max_carteiras": {"bloco": "filtro", "tipo": "int", "faixa": (1, 10)},
    "criterio": {"bloco": "filtro", "tipo": "opcao", "opcoes": ("fator_lucro", "retorno", "constancia")},
    "alvo": {"bloco": "alocacao", "tipo": "real", "faixa": (0.3, 3.0), "log": True},
    "revisao_dias": {"bloco": "alocacao", "tipo": "int", "faixa": (1, 7)},
    "parada": {"bloco": "risco", "tipo": "real", "faixa": (0.05, 0.25)},
    "freio": {"bloco": "risco", "tipo": "real", "faixa": (0.08, 0.25)},
    "corte": {"bloco": "risco", "tipo": "real", "faixa": (0.02, 0.30), "log": True, "desliga": True},
    "ganho": {"bloco": "risco", "tipo": "real", "faixa": (0.03, 1.0), "log": True, "desliga": True},
    "tempo_max_h": {"bloco": "risco", "tipo": "real", "faixa": (6.0, 240.0), "log": True, "desliga": True},
    "desvio_max": {"bloco": "execucao", "tipo": "real", "faixa": (0.001, 0.03), "log": True},
}
BLOCOS = ("filtro", "alocacao", "risco", "execucao")
CHANCE_DESLIGADO = 0.4          # no sorteio, chance de um gene que pode ser desligado nascer desligado

ESPECIES: dict[str, dict] = {
    "cautelosa": {"nome": "Cautelosa", "letra": "C", "descricao": "pouca exposição e paradas apertadas",
                  "faixas": {"alvo": (0.3, 1.0), "parada": (0.05, 0.12), "freio": (0.08, 0.12)}},
    "diversificada": {"nome": "Diversificada", "letra": "D", "descricao": "copia muitos traders ao mesmo tempo",
                      "faixas": {"max_carteiras": (6, 10), "alvo": (0.5, 2.0)}},
    "curta": {"nome": "Curta", "letra": "R", "descricao": "traders de operações rápidas, olhando o passado recente",
              "faixas": {"duracao_min": (5.0, 45.0), "janela_dias": (7, 21), "revisao_dias": (1, 2)}},
    "exigente": {"nome": "Exigente", "letra": "E", "descricao": "poucos traders, com filtro duro",
                 "faixas": {"max_carteiras": (1, 3), "min_fator_lucro": (1.8, 3.0), "min_operacoes": (25, 60)}},
}


def faixa(gene: str, especie: str, limites: dict | None = None) -> tuple:
    a, b = ESPECIES[especie]["faixas"].get(gene, GENES[gene]["faixa"])
    if gene == "alvo" and limites:                        # o limite duro vale mais que qualquer faixa
        b = min(b, limites["exposicao_max"])
    return a, b


def _arredondar(gene: str, x: float):
    g = GENES[gene]
    if g["tipo"] == "int":
        return int(round(x))
    return float(f"{x:.3g}")


def _posicao(gene: str, valor, especie: str) -> float:
    """Onde o valor cai na faixa, de 0 a 1 (em escala log quando o gene pede)."""
    a, b = faixa(gene, especie)
    if GENES[gene].get("log"):
        return (math.log(valor) - math.log(a)) / (math.log(b) - math.log(a))
    return (valor - a) / (b - a) if b > a else 0.0


def _da_posicao(gene: str, u: float, especie: str, limites: dict | None):
    a, b = faixa(gene, especie, limites)
    u = min(1.0, max(0.0, u))
    if GENES[gene].get("log"):
        x = math.exp(math.log(a) + u * (math.log(b) - math.log(a)))
    else:
        x = a + u * (b - a)
    return min(b, max(a, _arredondar(gene, x)))


@dataclass
class BotDNA:
    especie: str
    genes: dict = field(default_factory=dict)

    # ---------- criação
    @classmethod
    def sortear(cls, especie: str, rng: random.Random, limites: dict | None = None) -> "BotDNA":
        genes = {}
        for nome, g in GENES.items():
            if g["tipo"] == "opcao":
                genes[nome] = rng.choice(g["opcoes"])
            elif g.get("desliga") and rng.random() < CHANCE_DESLIGADO:
                genes[nome] = 0
            else:
                genes[nome] = _da_posicao(nome, rng.random(), especie, limites)
        return cls(especie, genes)

    @classmethod
    def cruzar(cls, pai: "BotDNA", mae: "BotDNA", rng: random.Random, limites: dict | None = None) -> "BotDNA":
        """O filho herda cada BLOCO inteiro de um dos pais (o filtro de um, a gestão de risco do outro...).
        Pelo menos um bloco vem de cada um. A espécie é a do pai; o que vier da mãe é encaixado nas faixas dela."""
        while True:
            de = {b: rng.random() < 0.5 for b in BLOCOS}
            if len(set(de.values())) == 2:
                break
        genes = {n: (pai if de[g["bloco"]] else mae).genes[n] for n, g in GENES.items()}
        filho = cls(pai.especie, genes)
        filho.encaixar(limites)
        return filho

    def mutar(self, rng: random.Random, chance: float, forca: float, limites: dict | None = None) -> list[str]:
        """Cada gene tem `chance` de mudar: um passo de tamanho `forca` (fração da faixa) para um lado. Devolve o
        que mudou. Se nada mudar, um gene é forçado: filho idêntico não explora nada."""
        mudou = []
        nomes = list(GENES)
        for nome in nomes:
            if rng.random() < chance and self._mutar_gene(nome, rng, forca, limites):
                mudou.append(nome)
        while not mudou:
            nome = rng.choice(nomes)
            if self._mutar_gene(nome, rng, forca, limites):
                mudou.append(nome)
        return mudou

    def _mutar_gene(self, nome: str, rng: random.Random, forca: float, limites: dict | None) -> bool:
        g, antes = GENES[nome], self.genes[nome]
        if g["tipo"] == "opcao":
            self.genes[nome] = rng.choice([o for o in g["opcoes"] if o != antes])
            return True
        if g.get("desliga") and rng.random() < 0.15:      # liga ou desliga
            self.genes[nome] = _da_posicao(nome, rng.random(), self.especie, limites) if antes == 0 else 0
            return True
        if antes == 0:
            return False
        u = _posicao(nome, antes, self.especie) + rng.gauss(0.0, forca)
        self.genes[nome] = _da_posicao(nome, u, self.especie, limites)
        if self.genes[nome] == antes and g["tipo"] == "int":   # passo pequeno demais para um inteiro: anda 1
            a, b = faixa(nome, self.especie, limites)
            self.genes[nome] = min(b, max(a, antes + rng.choice((-1, 1))))
        return self.genes[nome] != antes

    def encaixar(self, limites: dict | None = None) -> None:
        """Traz cada gene para dentro das faixas da espécie e dos limites duros."""
        for nome, g in GENES.items():
            v = self.genes[nome]
            if g["tipo"] == "opcao" or (g.get("desliga") and v == 0):
                continue
            a, b = faixa(nome, self.especie, limites)
            self.genes[nome] = _arredondar(nome, min(b, max(a, v)))

    # ---------- comparação
    def distancia(self, outro: "BotDNA") -> float:
        """De 0 (idênticos) a 1: a média das diferenças gene a gene, cada uma na escala da faixa inteira do gene."""
        soma = 0.0
        for nome, g in GENES.items():
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
        return soma / len(GENES)

    def copia(self) -> "BotDNA":
        return BotDNA(self.especie, dict(self.genes))

    def valido(self, limites: dict | None = None) -> bool:
        for nome, g in GENES.items():
            v = self.genes.get(nome)
            if g["tipo"] == "opcao":
                if v not in g["opcoes"]:
                    return False
                continue
            if g.get("desliga") and v == 0:
                continue
            a, b = faixa(nome, self.especie, limites)
            if v is None or not (a - 1e-9 <= v <= b + 1e-9):
                return False
        return True
