"""Socle identité : utilisateurs, organisations, appartenances, invitations et profil de compte (BE-020).

La route de profil en lecture seule (GET /api/v1/account/profile) est dans router.py,
montée sous le préfixe /account. Elle ne lit que la session courante.

Organisation courante (BE-010) : GET /api/v1/organizations/current renvoie l'organisation
sélectionnée par l'en-tête X-Organization-Id, après contrôle d'appartenance active
(app.rbac.guards). Sans session : 401 ; hors appartenance : 404 organization_not_found
(décision T-010) ; l'identifiant ne peut venir que de l'en-tête, jamais d'un paramètre
de requête. Droit de lecture non défini (QE-SOC-06) : tout membre actif peut lire.

Réglages d'organisation (BE-011) : GET et PUT /api/v1/organizations/current/settings.
Lecture ouverte à tout membre actif ; écriture (nom seul) sous la permission
`organization.settings.update` (QE-SOC-06), accordée au propriétaire. Le service
`service.update_organization` est partagé avec PATCH /organizations/{id} et porte
le contrôle de version (BE-233) et l'entrée d'audit.
"""
