"""O Predador: quem decide quem morre e quanto vale o resultado de cada robô. Tem duas funções separadas.

1. LIMITES DUROS (abate). Regras de segurança que ficam fora do DNA. Quebrou uma, o robô é abatido na hora e não
   deixa descendentes. Nenhum lucro compensa:
   - a conta caiu `queda_abate` (30 %) desde o maior valor que já teve;
   - a conta zerou.
   (A exposição máxima de 3× nem chega a ser violada: a ordem que passaria do teto é cortada antes de sair.)

2. FRAGILIDADE (nota). No fim de cada geração, cada robô recebe uma nota:

       nota = min(r, r_estresse) − 0,5 × queda − 0,5 × max(0, r − r_sem_melhor)

   r              retorno da geração, já com taxas e escorregamento
   r_estresse     o retorno da conta gêmea, com atraso de 3 min e escorregamento 3× maior
   queda          a maior queda desde um pico dentro da geração
   r_sem_melhor   o retorno tirando o trader que mais rendeu (lucro que vem de um trader só vale metade)

   Um robô que não operou fica com nota 0: melhor que perder, mas sem direito a filhos.

   A aptidão junta as últimas gerações (até 4) e pesa mais a PIOR:

       aptidão = 0,6 × pior nota + 0,4 × média das notas

   Assim um robô que brilhou num período só não passa na frente de um que se saiu razoável em todos.
"""
from __future__ import annotations


class Predator:
    def __init__(self, limites: dict, pesos: dict | None = None):
        self.limites = limites
        p = pesos or {}
        self.peso_queda = p.get("queda", 0.5)
        self.peso_concentracao = p.get("concentracao", 0.5)
        self.memoria = p.get("geracoes_na_aptidao", 4)
        self.peso_pior = p.get("pior", 0.6)

    # ---------- 1. limites duros
    def abate(self, conta: dict) -> str | None:
        if conta["pat"] <= 0:
            return "abatido: a conta zerou"
        if conta["pat"] <= (1 - self.limites["queda_abate"]) * conta["pico_abs"]:
            return f"abatido: caiu {round(100 * self.limites['queda_abate'])} % desde o pico"
        return None

    # ---------- 2. fragilidade
    def nota(self, r: float, r_estresse: float, queda: float, r_sem_melhor: float, ordens: int) -> float:
        if ordens == 0:
            return 0.0
        return (min(r, r_estresse) - self.peso_queda * queda
                - self.peso_concentracao * max(0.0, r - r_sem_melhor))

    def aptidao(self, notas: list[float]) -> float:
        ns = notas[-self.memoria:]
        if not ns:
            return 0.0
        return self.peso_pior * min(ns) + (1 - self.peso_pior) * sum(ns) / len(ns)
