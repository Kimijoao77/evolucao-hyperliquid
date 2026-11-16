from evolucao.predador import Predator
from testes.base import CFG

P = Predator(CFG["limites"], CFG["nota"])


def test_limites_duros():
    assert P.abate({"pat": 800.0, "pico_abs": 1000.0}) is None
    assert "30 %" in P.abate({"pat": 700.0, "pico_abs": 1000.0})
    assert "zerou" in P.abate({"pat": 0.0, "pico_abs": 1000.0})
    assert P.abate({"pat": 1400.0, "pico_abs": 2000.0})                    # 30 % desde o pico, mesmo acima do capital


def test_nota_pune_estresse_queda_e_um_trader_so():
    assert P.nota(0.10, 0.10, 0.0, 0.10, 50) == 0.10
    assert abs(P.nota(0.10, 0.04, 0.0, 0.10, 50) - 0.04) < 1e-12           # frágil: vale o resultado no estresse
    assert abs(P.nota(0.10, 0.10, 0.08, 0.10, 50) - 0.06) < 1e-12          # metade da queda sai da nota
    assert abs(P.nota(0.10, 0.10, 0.0, 0.0, 50) - 0.05) < 1e-12            # tudo veio de um trader: vale metade
    assert P.nota(0.0, 0.0, 0.0, 0.0, 0) == 0.0                            # não operou: zero, sem prêmio nem castigo
    assert P.nota(-0.05, -0.08, 0.06, -0.05, 20) < -0.08


def test_aptidao_pesa_mais_a_pior_geracao():
    assert P.aptidao([]) == 0.0
    firme, sortudo = P.aptidao([0.03, 0.03, 0.03]), P.aptidao([0.15, -0.03, -0.03])
    assert firme > sortudo                                                 # a média é a mesma (0,03)
    assert abs(P.aptidao([9, 9, 0.02, 0.02, 0.02, 0.02]) - 0.02) < 1e-12   # só as últimas 4
