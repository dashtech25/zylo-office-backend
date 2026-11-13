#!/usr/bin/env bash
# surveillance.sh : boucle sans modèle, à lancer en arrière-plan.
# Retard > DELAI_MIN + TOLERANCE_MIN, ou FAUX_RESET postérieur au dernier reset valide.
# 1er échec : RELANCE.flag, attente ATTENTE_RELANCE_S. 2e échec : ALERTE.txt puis sortie 2.
set -u
LIAISON="$(cd "$(dirname "$0")" && pwd)"
JOURNAL="$LIAISON/journal.log"
COMPTEUR="$LIAISON/compteur.txt"
ECHECS="$LIAISON/echecs.txt"
FLAG="$LIAISON/RELANCE.flag"
ALERTE="$LIAISON/ALERTE.txt"
DELAI_MIN="${DELAI_MIN:-30}"
TOLERANCE_MIN="${TOLERANCE_MIN:-5}"
INTERVALLE_S="${INTERVALLE_S:-60}"
ATTENTE_RELANCE_S="${ATTENTE_RELANCE_S:-600}"
SEUIL_S=$(awk "BEGIN{printf \"%d\", ($DELAI_MIN + $TOLERANCE_MIN) * 60}")

log() { echo "$(date '+%F %H:%M:%S') $*" >> "$JOURNAL"; }

# Affiche la raison du problème et retourne 0 s'il y en a un ; retourne 1 sinon.
probleme() {
  local now last retard ligne faux_epoch
  now=$(date +%s)
  last=$(cat "$COMPTEUR" 2>/dev/null)
  last=${last:-$now}
  retard=$(( now - last ))
  if [ "$retard" -gt "$SEUIL_S" ]; then
    echo "retard de ${retard} s (seuil ${SEUIL_S} s)"
    return 0
  fi
  ligne=$(grep '^FAUX_RESET' "$JOURNAL" 2>/dev/null | tail -n 1)
  faux_epoch=$(printf '%s' "$ligne" | sed -n 's/.* epoch=\([0-9]*\).*/\1/p')
  if [ -n "$faux_epoch" ] && [ "$faux_epoch" -gt "$last" ] && [ $(( now - faux_epoch )) -le "$SEUIL_S" ]; then
    echo "FAUX_RESET récent ($ligne)"
    return 0
  fi
  return 1
}

while true; do
  [ -f "$COMPTEUR" ] || { date +%s > "$COMPTEUR"; log "compteur.txt absent, initialisé à maintenant"; }
  [ -f "$ECHECS" ] || echo 0 > "$ECHECS"

  if raison=$(probleme); then
    n=$(( $(cat "$ECHECS") + 1 ))
    echo "$n" > "$ECHECS"
    log "ECHEC $n : $raison"
    if [ "$n" -eq 1 ]; then
      touch "$FLAG"
      log "RELANCE.flag créé, attente ${ATTENTE_RELANCE_S} s"
      sleep "$ATTENTE_RELANCE_S"
    else
      printf 'ALERTE %s : %s (2e échec, la relance de l intermédiaire est restée sans effet)\n' \
        "$(date '+%F %H:%M:%S')" "$raison" > "$ALERTE"
      log "ALERTE.txt écrit, arrêt de la surveillance (code 2)"
      exit 2
    fi
  else
    echo 0 > "$ECHECS"
    sleep "$INTERVALLE_S"
  fi
done
