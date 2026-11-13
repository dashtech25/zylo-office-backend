#!/usr/bin/env bash
# Vérifie que les liens relatifs des fichiers Markdown pointent vers un fichier existant.
# Intention : une doc qui renvoie vers un fichier déplacé trompe le lecteur et l'agent.
# Ignorés : http(s), mailto, ancres seules, et docs/archive/ (contenu historique figé,
# dont les liens d'origine ne sont pas réécrits, voir docs/archive/README.md).
# Code de sortie : 0 si aucun lien cassé, 1 sinon.
set -u

racine="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$racine"

mapfile -t fichiers < <(find . -name '*.md' \
  -not -path './docs/archive/*' -not -path './.git/*' \
  -not -path './node_modules/*' -not -path './.venv/*' -not -path './worktrees/*' | sort)

total=0
casses=0
for f in "${fichiers[@]}"; do
  dir="$(dirname "$f")"
  while IFS= read -r lien; do
    cible="${lien%%#*}"
    cible="${cible%%\?*}"
    [[ -z "$cible" ]] && continue
    [[ "$cible" =~ ^(https?|mailto|tel): ]] && continue
    total=$((total + 1))
    if [[ "$cible" == /* ]]; then
      chemin=".$cible"
    else
      chemin="$dir/$cible"
    fi
    if [[ ! -e "$chemin" ]]; then
      echo "LIEN CASSE : $f -> $lien"
      casses=$((casses + 1))
    fi
  done < <(grep -oP '\]\(\K[^)\s]+' "$f" || true)
done

echo "Fichiers Markdown : ${#fichiers[@]} ; liens internes vérifiés : $total ; liens cassés : $casses"
[[ $casses -eq 0 ]]
