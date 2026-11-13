#!/usr/bin/env bash
# reset_compteur.sh <chemin_rapport>
# Remet le compteur de rapport à zéro, uniquement si le rapport est valide :
# fichier présent, écrit il y a 2 minutes au plus, avec les 8 sections numérotées.
set -u
LIAISON="$(cd "$(dirname "$0")" && pwd)"
JOURNAL="$LIAISON/journal.log"
RAPPORT="${1:-}"
maintenant=$(date +%s)
horodatage=$(date '+%F %H:%M:%S')

refuser() {
  echo "FAUX_RESET $horodatage epoch=$maintenant raison=$1 rapport=$RAPPORT" >> "$JOURNAL"
  echo "REFUS : $1" >&2
  exit 1
}

[ -n "$RAPPORT" ] || refuser "chemin de rapport absent"
[ -f "$RAPPORT" ] || refuser "rapport absent"

age=$(( maintenant - $(stat -c %Y "$RAPPORT") ))
[ "$age" -le 120 ] || refuser "rapport vieux de ${age} s (maximum 120 s)"

for n in 1 2 3 4 5 6 7 8; do
  nb=$(grep -cE "^#{1,6}[[:space:]]+$n([.):[:space:]-]|\$)" "$RAPPORT")
  [ "$nb" -eq 1 ] || refuser "section $n absente ou en double"
done
total=$(grep -cE '^#{1,6}[[:space:]]+[0-9]+' "$RAPPORT")
[ "$total" -eq 8 ] || refuser "$total sections numérotées au lieu de 8"

echo "$maintenant" > "$LIAISON/compteur.txt"
echo 0 > "$LIAISON/echecs.txt"
echo "RESET_OK $horodatage epoch=$maintenant rapport=$RAPPORT" >> "$JOURNAL"
echo "Compteur remis à zéro ($horodatage)."
