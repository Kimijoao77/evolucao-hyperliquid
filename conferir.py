"""Confere a pasta dados/ antes de ela ir para o ramo "estado" (que é regravado a cada rodada, sem histórico).

Uma rodada com defeito (bug, API respondendo lixo, arquivo cortado) não pode apagar meses de evolução. Por isso, antes
de guardar, este script compara o estado novo com o da rodada anterior (copiado por buscar.sh para anterior/) e
recusa se algo parece quebrado. Recusou: o ramo "estado" fica como estava, a corrente de rodadas continua e a próxima
tenta de novo a partir do estado bom. Além disso, as cópias diárias e de cada geração (copias.sh) ficam nas Releases.

Uso: python conferir.py [dados] [anterior]. Sai com 1 (e explica) se recusar. FORCAR=1 pula a conferência (para uma
mudança feita de propósito, por exemplo trocar o tamanho da população).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FAMILIAS = ("precos", "cofres", "listagens", "pools")


def ler(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def conferir(dados: Path, anterior: Path) -> list[str]:
    """Os problemas encontrados (lista vazia = pode guardar)."""
    probs: list[str] = []
    # 1. todo .json da pasta precisa abrir
    for p in sorted(dados.rglob("*.json")):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            probs.append(f"{p.relative_to(dados)} não abre: {e}")
    if probs:
        return probs

    novo, velho = ler(dados / "evolucao.json"), ler(anterior / "evolucao.json")
    if novo is None:
        return ["evolucao.json sumiu"] if velho is not None else []
    if not novo.get("gerado") or not novo.get("fase"):
        probs.append("evolucao.json sem 'gerado' ou sem 'fase'")
    if velho:
        if (novo.get("gerado") or 0) < (velho.get("gerado") or 0):
            probs.append("o resumo novo é mais velho que o anterior")
        if velho.get("fase") == "rodando":
            if novo.get("fase") != "rodando":
                probs.append(f"a evolução estava rodando e agora está em '{novo.get('fase')}'")
            gn, gv = (novo.get("geracao") or {}).get("n", 0), (velho.get("geracao") or {}).get("n", 0)
            if gn < gv:
                probs.append(f"a geração voltou de {gv} para {gn}")

    # 2. a população: não pode sumir de uma rodada para a outra
    en, ev = ler(dados / "estado.json"), ler(anterior / "estado.json")
    if ev and ev.get("robos"):
        if not en or not en.get("robos"):
            probs.append("estado.json sem robôs (antes tinha)")
        elif len(en["robos"]) < 0.8 * len(ev["robos"]):
            probs.append(f"a população caiu de {len(ev['robos'])} para {len(en['robos'])} robôs numa rodada")
        if en and len(en.get("linhagem") or {}) < len(ev.get("linhagem") or {}):
            probs.append("a árvore da família (linhagem) encolheu")

    # 3. o universo de traders não pode esvaziar de repente
    un, uv = ler(dados / "universo.json"), ler(anterior / "universo.json")
    if uv and (uv.get("carteiras") or {}):
        nv, nn = len(uv["carteiras"]), len((un or {}).get("carteiras") or {})
        if nn < 0.5 * nv:
            probs.append(f"o universo de traders caiu de {nv} para {nn} carteiras")

    # 4. as outras famílias: quem existia continua existindo
    for f in FAMILIAS:
        if (anterior / f"{f}.json").exists() and not (dados / f"{f}.json").exists():
            probs.append(f"{f}.json sumiu")
        ev_f, en_f = ler(anterior / f / "estado.json"), ler(dados / f / "estado.json")
        if ev_f and ev_f.get("robos"):
            if not (en_f and en_f.get("robos")):
                probs.append(f"a população de {f} sumiu")
            elif len(en_f["robos"]) < 0.8 * len(ev_f["robos"]):
                probs.append(f"a população de {f} caiu de {len(ev_f['robos'])} para {len(en_f['robos'])} robôs numa rodada")
    return probs


def main() -> int:
    dados = Path(sys.argv[1] if len(sys.argv) > 1 else "dados")
    anterior = Path(sys.argv[2] if len(sys.argv) > 2 else "anterior")
    probs = conferir(dados, anterior)
    if not probs:
        print("conferência: ok, pode guardar")
        return 0
    print("conferência: NÃO vou guardar esta rodada (o estado anterior continua no ramo 'estado'):")
    print("\n".join(f"- {p}" for p in probs))
    if os.environ.get("FORCAR") == "1":
        print("FORCAR=1: guardando mesmo assim")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
