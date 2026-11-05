"""Permissions et modes du module support (BE-262).

Les codes suivent la convention `domaine.entite.action`. Les noms exacts sont
une recommandation appliquée : la source les marque NON DÉFINI (BE-008).
"""

# Lecture des données d'une organisation sous accès support, portée organisation.
SUPPORT_READ = "support.read"

# Écriture sous accès support : exige en plus le mode `ecriture` de l'accès.
SUPPORT_WRITE_SENSIBLE = "support.write_sensible"

# Mode par défaut d'un accès : lecture seule (CA-1).
MODE_LECTURE = "lecture"
MODE_ECRITURE = "ecriture"
MODES = (MODE_LECTURE, MODE_ECRITURE)
