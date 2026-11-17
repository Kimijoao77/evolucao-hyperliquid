#!/usr/bin/env bash
# Traz o estado da rodada anterior (ramo "estado") para a pasta dados/. Na primeira vez o ramo ainda não existe.
# Também guarda em anterior/ os arquivos principais de como estava, para conferir.py comparar antes de guardar.
set -eu
mkdir -p dados anterior
if git fetch -q --depth 1 origin estado 2>/dev/null; then
  git archive FETCH_HEAD | tar -x -C dados
  echo "estado anterior: $(git rev-parse --short FETCH_HEAD), $(find dados -type f | wc -l) arquivos"
  cp dados/*.json anterior/ 2>/dev/null || true
  for f in precos cofres listagens pools; do
    if [ -f "dados/$f/estado.json" ]; then mkdir -p "anterior/$f" && cp "dados/$f/estado.json" "anterior/$f/"; fi
  done
else
  echo "primeira rodada: ainda não existe estado"
fi
