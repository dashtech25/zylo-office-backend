"""Permissions du domaine release (BE-250).

Format `domaine.entite.action`. La promotion est réservée au responsable livraison ;
le rôle qui porte cette permission n'est pas encore semé (aucune route dans BE-250),
donc aucun utilisateur ne peut promouvoir tant que le câblage IAM n'est pas livré.
"""

PERMISSION_PROMOTION = "release.promotion.executer"
