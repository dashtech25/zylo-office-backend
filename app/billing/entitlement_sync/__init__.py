"""Demande et suivi de changement de droits, ou synchronisation des droits (BE-085).

Contenu du paquet :
- `service.py` : `demander_synchronisation`, `enregistrer_resultat` et `verifier_droits_confirmes`.

Règles :
- PH-09 reste la seule autorité de droits. Le paiement ne crée aucun droit ; ce paquet ne
  modifie ni l'abonnement, ni les paiements, ni les droits (`subscription_entitlement`).
- Aucun routeur HTTP : la synchronisation n'est déclenchée que par un appel interne (CA-3).
- Un abonnement d'un autre tenant est traité comme inexistant (CA-4).
- Une synchronisation en échec est terminale : seule une nouvelle demande recrée une
  synchronisation applicable (CA-1). Tant que la dernière demande n'est pas `applied`, la
  confirmation des droits renvoie `ENTITLEMENT_SYNC_PENDING`.
"""
