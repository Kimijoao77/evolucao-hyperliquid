#!/usr/bin/env bash
# Cópias de segurança do estado (a pasta dados/ inteira), nas Releases do GitHub: ficam fora do git, então o
# repositório não cresce, e sobrevivem a uma rodada com defeito ou a um ramo "estado" estragado.
# - copias-diarias: a primeira rodada de cada dia guarda uma; as com mais de 30 dias são apagadas.
# - copias-geracoes: uma a cada geração fechada (de qualquer família), para sempre.
# Para voltar a uma delas: Actions → "Restaurar uma cópia" (restaurar.yml).
set -eu
repo="$GITHUB_REPOSITORY"
tmp="${RUNNER_TEMP:-/tmp}"
dia=$(date -u +%F)
arq="$tmp/estado-$dia.tgz"

garantir() {
  gh release view "$1" --repo "$repo" >/dev/null 2>&1 ||
    gh release create "$1" --repo "$repo" --title "$2" --notes "$3" --latest=false >/dev/null
}
nomes() { gh release view "$1" --repo "$repo" --json assets --jq '.assets[].name'; }
compactar() { [ -f "$arq" ] || tar -czf "$arq" -C dados .; }

garantir copias-diarias "Cópias diárias do estado" \
  "Uma cópia por dia do ramo estado (a pasta dados/ inteira), guardadas por 30 dias. Para voltar a uma delas: Actions → Restaurar uma cópia."
if ! nomes copias-diarias | grep -qx "estado-$dia.tgz"; then
  compactar
  gh release upload copias-diarias "$arq" --repo "$repo"
  echo "cópia do dia guardada: estado-$dia.tgz ($(du -h "$arq" | cut -f1))"
fi
limite=$(date -u -d '30 days ago' +%F)
for a in $(nomes copias-diarias); do
  d=${a#estado-}; d=${d%.tgz}
  if [[ "$d" < "$limite" ]]; then
    gh release delete-asset copias-diarias "$a" --repo "$repo" -y && echo "cópia diária antiga apagada: $a"
  fi
done

if [ -s "$tmp/geracao-fechada" ]; then
  garantir copias-geracoes "Cópias das gerações" \
    "Uma cópia do estado inteiro a cada geração fechada, guardadas para sempre. Para voltar a uma delas: Actions → Restaurar uma cópia."
  compactar
  nome="estado-$(date -u +%F-%H%M)-$(tr '\n' ' ' <"$tmp/geracao-fechada" | xargs | tr ' /' '_-').tgz"
  cp "$arq" "$tmp/$nome"
  gh release upload copias-geracoes "$tmp/$nome" --repo "$repo"
  echo "cópia da geração guardada: $nome"
fi
