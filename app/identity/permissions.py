"""Permissions déclarées par le module identity — convention reprise par tout
futur module métier : chaque domaine possède son propre fichier permissions.py,
jamais une déclaration centralisée qui coupler tous les modules entre eux."""

ORGANIZATION_MANAGE = "identity.organization.manage"

# Créer, réémettre une invitation et désactiver/réactiver les membres d'une
# organisation (T-021, T-048). Accordée au propriétaire à la création de
# l'organisation, et par la migration explicite b3c4d5e6f7a8 aux propriétaires
# existants (jamais par un backfill au démarrage).
USER_MANAGE = "identity.user.manage"

# Inviter une personne à rejoindre l'organisation courante et consulter les
# invitations en attente (BE-012). Le code suit la recommandation QE-SOC-06 ;
# il est accordé au propriétaire à la création de l'organisation, puis par la
# migration explicite de BE-012 aux propriétaires existants.
MEMBERS_INVITE = "organization.members.invite"
# BE-014 : lire la liste des membres de l'organisation courante, et en retirer
# un. Accordées au propriétaire à la création de l'organisation (OWNER_DEFAULT_PERMISSIONS) ;
# les organisations existantes les reçoivent par `cli.py` (backfill_owner_default_permissions).
MEMBERS_READ = "organization.members.read"
MEMBERS_REMOVE = "organization.members.remove"

# BE-011 : modifier les réglages minimaux de l'organisation courante (nom).
# La lecture des réglages est ouverte à tout membre actif ; seule l'écriture
# exige ce code. Recommandation QE-SOC-06 : format `ressource.action`. Accordée
# au propriétaire à la création de l'organisation (OWNER_DEFAULT_PERMISSIONS).
ORGANIZATION_SETTINGS_UPDATE = "organization.settings.update"

# BE-186 : lire l'organisation (GET /api/v1/organizations/{organization_id}) et la
# modifier (PATCH, verrou `expectedVersion`). Portée tenant : une organisation
# d'un autre tenant répond 404 avant tout contrôle de droit (rbac/guards.py).
ORGANIZATION_READ = "organization.read"
ORGANIZATION_UPDATE = "organization.update"
# BE-186 : voir les identifiants légaux confidentiels de l'organisation. Sans ce
# droit, les champs sont absents de la réponse (et non renvoyés vides).
ORGANIZATION_LEGAL_READ = "organization.legal.read"

# BE-109 : lire le résumé du portail (GET /organizations/{organization_id}/portal-summary).
# Écart : la fiche écrit `portal:read` ; le format `domaine.entite.action` est retenu, comme BE-108.
# Accordée au propriétaire à la création de l'organisation (OWNER_DEFAULT_PERMISSIONS).
PORTAL_SUMMARY_READ = "portal.summary.read"
