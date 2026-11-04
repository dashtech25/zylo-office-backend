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
