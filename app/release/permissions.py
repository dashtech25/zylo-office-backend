"""Permissions du domaine release (BE-250).

Format `domaine.entite.action`. La promotion est réservée au responsable livraison ;
le rôle qui porte cette permission n'est pas encore semé (aucune route dans BE-250),
donc aucun utilisateur ne peut promouvoir tant que le câblage IAM n'est pas livré.
"""

PERMISSION_PROMOTION = "release.promotion.executer"

# Déclenchement d'une compensation (BE-252) : réservé au propriétaire métier et à
# l'exploitation, avec approbation distincte du demandeur. Non semé : aucune route en BE-252.
PERMISSION_COMPENSATION = "release.compensation.executer"
