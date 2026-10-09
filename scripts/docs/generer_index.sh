#!/usr/bin/env bash
# Génère les README d'index de docs/ à partir de l'arborescence réelle.
# Intention : un index écrit à la main dérive des fichiers (DOC-009). Ce script
# ne réécrit que les README portant le marqueur ci-dessous ; un README rédigé
# à la main (sans marqueur) n'est jamais écrasé.
set -eu

racine="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$racine/docs"

marqueur='<!-- index genere par scripts/docs/generer_index.sh : ne pas editer -->'

titre_de() {
  local t
  t="$(grep -m1 '^# ' "$1" 2>/dev/null | sed 's/^# //')" || true
  if [[ -z "$t" ]]; then t="$(basename "$1")"; fi
  printf '%s' "$t"
}

ecrire_index() {
  local dir="$1" rd="$1/README.md" nom
  if [[ -e "$rd" ]] && ! grep -qF "$marqueur" "$rd"; then
    echo "conserve (rédigé à la main) : docs/${rd#./}"
    return
  fi
  nom="$(basename "$dir")"
  if [[ "$dir" == "." ]]; then nom="Documentation du backend Zylo Office"; fi
  {
    echo "# ${nom}"
    echo
    echo "$marqueur"
    echo
    if [[ "$dir" == "." ]]; then
      echo "Index de la documentation du backend Zylo Office. Généré à partir de l'arborescence réelle : ne pas éditer à la main. Pour ajouter un document, créer le fichier dans le bon dossier et relancer \`scripts/docs/generer_index.sh\`."
      echo
      echo "Règles de l'arborescence : un fichier, un sujet ; les rapports de livraison et les documents historiques vont dans \`archive/\` ; les décisions d'architecture dans \`architecture/decisions/\` ; les questions ouvertes dans \`questions/<catégorie>/\`."
      echo
    fi
    echo "## Contenu"
    echo
    local f
    while IFS= read -r f; do
      echo "- [$(titre_de "$f")]($(basename "$f"))"
    done < <(find "$dir" -mindepth 1 -maxdepth 1 -type f -name '*.md' ! -name 'README.md' | sort)
    local s
    while IFS= read -r s; do
      echo "- [$(basename "$s")/]($(basename "$s")/README.md)"
    done < <(find "$dir" -mindepth 1 -maxdepth 1 -type d | sort)
  } > "$rd"
  echo "écrit : docs/${rd#./}"
}

# Dossiers de bas en haut : chaque index référence les README des sous-dossiers.
while IFS= read -r d; do
  ecrire_index "$d"
done < <(find . -type d | sort -r)
