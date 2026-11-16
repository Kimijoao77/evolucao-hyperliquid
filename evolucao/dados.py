"""Onde os dados ficam. Tudo em texto, na pasta `dados/` (no GitHub ela é o ramo `estado`, regravado a cada rodada
sem acumular histórico: o repositório não cresce com os anos).

dados/universo.json              as carteiras acompanhadas: quando entraram, de onde vieram, situação, até onde coletamos
dados/fills/<carteira>/AAAA-MM.jsonl   cada execução (fill), uma por linha, só os campos que a simulação usa
dados/contas/AAAA-MM.jsonl       fotos do saldo e das posições a cada coleta
dados/estado.json                a população inteira (DNA, contas de mentira, geração em curso)
dados/evolucao.json              o resumo que o app lê
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def pasta() -> Path:
    return Path(os.environ.get("EVOLUCAO_DADOS", RAIZ / "dados"))


def agora_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def mes_de(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m")


def texto_de(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def ler_json(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def gravar_json(caminho: Path, obj, compacto: bool = True) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    if compacto:
        txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    else:
        txt = json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True)
    tmp.write_text(txt, encoding="utf-8")
    tmp.replace(caminho)


# ---------------------------------------------------------------- fills
def compactar(f: dict) -> dict:
    """Um fill da Hyperliquid com nomes curtos e só o que a simulação usa."""
    c = {"t": int(f["time"]), "c": f["coin"], "s": f["side"], "p": float(f["px"]), "z": float(f["sz"]),
         "sp": float(f.get("startPosition") or 0), "pnl": float(f.get("closedPnl") or 0),
         "f": float(f.get("fee") or 0), "id": f.get("tid")}
    if f.get("liquidation"):
        c["liq"] = 1
    return c


def anexar_fills(carteira: str, fills: list[dict]) -> int:
    """Grava os fills novos (já compactados) no arquivo do mês. Devolve quantos gravou."""
    por_mes: dict[str, list[dict]] = {}
    for f in fills:
        por_mes.setdefault(mes_de(f["t"]), []).append(f)
    n = 0
    for mes, lista in por_mes.items():
        arq = pasta() / "fills" / carteira.lower() / f"{mes}.jsonl"
        arq.parent.mkdir(parents=True, exist_ok=True)
        ja = set()
        if arq.exists():
            for linha in arq.read_text(encoding="utf-8").splitlines():
                try:
                    ja.add(json.loads(linha).get("id"))
                except json.JSONDecodeError:
                    pass
        novos = [f for f in lista if f.get("id") is None or f.get("id") not in ja]
        if novos:
            with arq.open("a", encoding="utf-8") as h:
                for f in novos:
                    h.write(json.dumps(f, separators=(",", ":")) + "\n")
            n += len(novos)
    return n


def ler_fills(carteira: str) -> list[dict]:
    p = pasta() / "fills" / carteira.lower()
    out = []
    if p.exists():
        for arq in sorted(p.glob("*.jsonl")):
            for linha in arq.read_text(encoding="utf-8").splitlines():
                if linha.strip():
                    out.append(json.loads(linha))
    out.sort(key=lambda f: (f["t"], f.get("id") or 0))
    return out


# ---------------------------------------------------------------- fotos da conta
def anexar_foto(foto: dict) -> None:
    arq = pasta() / "contas" / f"{mes_de(foto['t'])}.jsonl"
    arq.parent.mkdir(parents=True, exist_ok=True)
    with arq.open("a", encoding="utf-8") as h:
        h.write(json.dumps(foto, separators=(",", ":")) + "\n")


def ler_fotos() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    p = pasta() / "contas"
    if p.exists():
        for arq in sorted(p.glob("*.jsonl")):
            for linha in arq.read_text(encoding="utf-8").splitlines():
                if linha.strip():
                    f = json.loads(linha)
                    out.setdefault(f["a"], []).append(f)
    return out


# ---------------------------------------------------------------- faxina
def podar(agora: int, dias: int) -> int:
    """Apaga os arquivos de meses inteiros mais velhos que `dias` (as fichas dos traders olham no máximo 60 dias)."""
    corte = mes_de(agora - dias * 86_400_000)
    n = 0
    for arq in list((pasta() / "fills").glob("*/*.jsonl")) + list((pasta() / "contas").glob("*.jsonl")):
        if arq.stem < corte:
            arq.unlink()
            n += 1
    for p in (pasta() / "fills").glob("*"):
        if p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    return n
