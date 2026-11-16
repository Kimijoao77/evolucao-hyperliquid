#!/usr/bin/env bash
# Traz o estado da rodada anterior (ramo "estado") para a pasta dados/. Na primeira vez o ramo ainda não existe.
set -eu
mkdir -p dados
if git fetch -q --depth 1 origin estado 2>/dev/null; then
  git archive FETCH_HEAD | tar -x -C dados
  echo "estado anterior: $(git rev-parse --short FETCH_HEAD), $(find dados -type f | wc -l) arquivos"
else
  echo "primeira rodada: ainda não existe estado"
fi
