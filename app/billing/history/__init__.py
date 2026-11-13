"""Historique commercial consultable par portée (BE-099).

Lecture seule de `audit_event` (BE-007, alimentée par BE-073) pour les entrées `billing.*`
du tenant courant. Voir `app/billing/history/router.py` pour le contrat HTTP et
`app/billing/history/service.py` pour la règle de permission et de périmètre.
"""
