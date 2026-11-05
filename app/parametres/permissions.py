"""Permissions déclarées par le module paramètres (BE-157).

Convention `domaine.entite.action`, comme les autres modules. Sans enregistrement dans
`seed.py`, la permission n'existe pas en base et `user_has_permission` la refuse, y compris
au propriétaire.
"""

# Appliquer, restaurer ou rétablir le défaut d'une valeur de paramètre. Qui la détient n'est
# pas tranché par la définition (QE-PAR-03) : elle n'est accordée à aucun rôle par défaut ; la
# répartition réelle reste à définir avec les rôles d'administration.
PARAMETRE_APPLIQUER = "parametres.setting.apply"

# Lire les paramètres résolus d'un scope (BE-158, GET). Nommée `settings.read` par la définition
# (source EVT-SET-01) ; hors convention `domaine.entite.action`, écart signalé en QE-PAR-03.
PARAMETRE_LIRE = "settings.read"
