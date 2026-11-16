#!/usr/bin/env bash
# Guarda o resultado da rodada no GitHub.
# - A memória das gerações (memoria/) vai para a main: um commit por geração fechada.
# - O estado (pasta dados/) vai para o ramo "estado" como UM commit sem pai, por cima do anterior. Assim o
#   repositório não acumula o histórico de milhares de rodadas e continua pequeno com o passar dos anos.
set -eu
git config user.name "evolucao-bot"
git config user.email "evolucao-bot@users.noreply.github.com"

git add memoria
if ! git diff --cached --quiet; then
  git commit -q -m "Memória: geração fechada em $(date -u +'%Y-%m-%d %H:%M') UTC"
  for i in 1 2 3 4 5; do git push -q origin HEAD:main && break; sleep 5; git pull -q --rebase origin main; done
fi

raiz=$(pwd)
export GIT_INDEX_FILE="${RUNNER_TEMP:-/tmp}/indice-estado"
rm -f "$GIT_INDEX_FILE"
(cd dados && git --git-dir="$raiz/.git" --work-tree=. add -A .)
arvore=$(git --git-dir="$raiz/.git" write-tree)
unset GIT_INDEX_FILE
commit=$(git commit-tree "$arvore" -m "Estado: $(date -u +'%Y-%m-%d %H:%M') UTC")
git push -q -f origin "$commit:refs/heads/estado"
echo "estado guardado: $commit"
