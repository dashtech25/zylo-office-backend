"""Permissions de la sortie de tenant (BE-246).

Format `domaine.entite.action` (CLAUDE.md, « Sécurité, IAM et permissions »).
- `donnees.sortie.decider` : demander une sortie et poser un hold. Réservée à l'opérateur habilité,
  accordée à aucun rôle par défaut (QE-EXP-15 : décision avec approbation distincte).
- `donnees.sortie.lire` : lire l'attestation d'une sortie, pour un tiers qui n'y figure pas.
"""

SORTIE_TENANT_DECIDER = "donnees.sortie.decider"
SORTIE_TENANT_LIRE = "donnees.sortie.lire"
