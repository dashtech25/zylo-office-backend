"""Constantes du registre des modules : codes reconnus et versions de manifeste supportées.

Le contrat du manifeste est versionné (`module.manifestVersion`). Son format détaillé n'est pas
encore défini (QE-SOC-19) : seul le numéro de version est contrôlé ici. Un manifeste dont la
version n'est pas listée dans `VERSIONS_MANIFESTE_SUPPORTEES` rend le module `incompatible`.

Le socle ne liste que des codes (chaînes) : il n'importe jamais un module métier. Ajouter un
module au catalogue reconnu = ajouter son code ici ET son entrée dans `seed.py`.
"""

# Codes de module reconnus par le système. Un code hors de cette liste est `inconnu`, même s'il
# figure dans la table `module` : la reconnaissance vient du code de l'application, pas des données.
CODES_MODULES_CONNUS: frozenset[str] = frozenset({"zylo_liquid", "zylo_tanker"})

# Versions du contrat de manifeste que le socle sait lire. Une version absente de cet ensemble
# rend le module `incompatible` (aucun droit n'est déduit d'un manifeste qu'on ne comprend pas).
VERSIONS_MANIFESTE_SUPPORTEES: frozenset[int] = frozenset({1})
