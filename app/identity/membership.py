"""Membership et sélection de contexte (BE-189).

Rôle : gérer l'appartenance d'un utilisateur à un tenant (ici une organisation) et
ouvrir un contexte de travail sur ce tenant.

Modèle (écart consigné, recommandation la plus simple) : la table `organization_user`
(BE-004) joue le rôle de `membership` : une ligne par couple (organisation, utilisateur),
contrainte d'unicité `uq_organizationUser_org_user`. Cette table reçoit ici `version` et
`status`, parmi `invited`, `active`, `suspended`, `revoked`.

Invariants :
- seul un membership `active` ouvre un contexte (`rbac.guards.assert_active_membership`
  exige le même statut) ;
- un tenant sans membership actif répond 404 `organization_not_found`, identique pour
  « inexistant », « sans appartenance » et « suspendu » (non-énumération) ;
- la révocation (`DELETE`) garde la ligne, passe le statut à `revoked` et retire les rôles
  de l'utilisateur dans le tenant : l'historique est conservé (QE-API-15) et l'accès coupé
  dès la requête suivante ;
- chaque changement de contexte et chaque changement de membership écrit exactement une
  entrée d'audit (BE-007), dans la même transaction que la modification ;
- l'invitation est idempotente : l'unicité (organisation, utilisateur) interdit un second
  membership, donc un rejeu ne crée rien de plus.

Hors périmètre v1 : acceptation de l'invitation par la personne invitée (l'activation se
fait par `PATCH`), protection du dernier propriétaire lors d'une révocation.
"""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.identity.models import Organization, OrganizationUser, User
from app.rbac.guards import organisation_introuvable
from app.rbac.models import UserRole

ETAT_INVITED = "invited"
ETAT_ACTIVE = "active"
ETAT_SUSPENDED = "suspended"
ETAT_REVOKED = "revoked"
ETATS_MODIFIABLES = (ETAT_INVITED, ETAT_ACTIVE, ETAT_SUSPENDED)

ACTION_CONTEXTE_SELECT = "contexte.select"
ACTION_MEMBERSHIP_INVITE = "membership.invite"
ACTION_MEMBERSHIP_UPDATE = "membership.update"
ACTION_MEMBERSHIP_REVOKE = "membership.revoke"


def _vers_contexte(appartenance: OrganizationUser, nom_organisation: str) -> dict:
    return {
        "organizationId": str(appartenance.organizationId),
        "name": nom_organisation,
        "membershipId": str(appartenance.id),
        "state": appartenance.status,
    }


def _vers_membership(appartenance: OrganizationUser, utilisateur: User) -> dict:
    return {
        "membershipId": str(appartenance.id),
        "organizationId": str(appartenance.organizationId),
        "userId": str(utilisateur.id),
        "email": utilisateur.email,
        "fullName": utilisateur.fullName,
        "state": appartenance.status,
        "version": appartenance.version,
    }


async def _appartenance_par_id(db: AsyncSession, organization_id: uuid.UUID, membership_id: uuid.UUID) -> OrganizationUser:
    """Membership de l'organisation désignée, ou 404 `membership_not_found` (aucune fuite inter-tenant)."""
    appartenance = await db.scalar(
        select(OrganizationUser).where(
            OrganizationUser.id == membership_id, OrganizationUser.organizationId == organization_id
        )
    )
    if appartenance is None:
        raise AppError(code="membership_not_found", message="Membership introuvable.", status_code=404)
    return appartenance


async def lister_contextes(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """Contextes ouverts par l'utilisateur : ses memberships `active` sur des organisations non supprimées."""
    stmt = (
        select(OrganizationUser, Organization.name)
        .join(Organization, Organization.id == OrganizationUser.organizationId)
        .where(
            OrganizationUser.userId == user_id,
            OrganizationUser.status == ETAT_ACTIVE,
            Organization.deletedAt.is_(None),
        )
        .order_by(Organization.name)
    )
    return [_vers_contexte(appartenance, nom) for appartenance, nom in (await db.execute(stmt)).all()]


async def selectionner_contexte(db: AsyncSession, user: User, organization_id: uuid.UUID) -> dict:
    """Ouvre le contexte de `organization_id` pour `user`, et l'audite.

    404 `organization_not_found` si l'utilisateur n'a pas de membership actif sur ce tenant."""
    stmt = (
        select(OrganizationUser, Organization.name)
        .join(Organization, Organization.id == OrganizationUser.organizationId)
        .where(
            OrganizationUser.organizationId == organization_id,
            OrganizationUser.userId == user.id,
            OrganizationUser.status == ETAT_ACTIVE,
            Organization.deletedAt.is_(None),
        )
    )
    ligne = (await db.execute(stmt)).first()
    if ligne is None:
        raise organisation_introuvable()
    appartenance, nom = ligne
    await record_audit_event(
        db,
        organization_id,
        user.id,
        action=ACTION_CONTEXTE_SELECT,
        entity_type="Membership",
        entity_id=appartenance.id,
        summary=f"Ouverture du contexte de l'organisation {nom}",
    )
    await db.commit()
    return _vers_contexte(appartenance, nom)


async def lister_memberships(db: AsyncSession, organization_id: uuid.UUID) -> list[dict]:
    """Memberships du tenant courant, tous statuts confondus, triés par nom complet."""
    stmt = (
        select(OrganizationUser, User)
        .join(User, User.id == OrganizationUser.userId)
        .where(OrganizationUser.organizationId == organization_id)
        .order_by(User.fullName)
    )
    return [_vers_membership(appartenance, utilisateur) for appartenance, utilisateur in (await db.execute(stmt)).all()]


async def inviter(db: AsyncSession, actor: User, organization_id: uuid.UUID, email: str) -> tuple[dict, bool]:
    """Invite un utilisateur existant (par e-mail) dans le tenant courant.

    Renvoie `(membership, cree)`. 404 `user_not_found` si aucun compte ne porte cet e-mail.
    Un membership déjà présent (quel que soit son état hors révocation) est renvoyé
    sans modification : c'est ce qui rend le rejeu idempotent. Un membership révoqué
    est réactivé en `invited`."""
    utilisateur = await db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if utilisateur is None:
        raise AppError(code="user_not_found", message="Utilisateur introuvable.", status_code=404)

    appartenance = await db.scalar(
        select(OrganizationUser).where(
            OrganizationUser.organizationId == organization_id, OrganizationUser.userId == utilisateur.id
        )
    )
    if appartenance is not None and appartenance.status != ETAT_REVOKED:
        return _vers_membership(appartenance, utilisateur), False

    if appartenance is None:
        appartenance = OrganizationUser(organizationId=organization_id, userId=utilisateur.id, status=ETAT_INVITED, version=1)
        db.add(appartenance)
    else:
        appartenance.status = ETAT_INVITED
        appartenance.version += 1
    await db.flush()
    await record_audit_event(
        db,
        organization_id,
        actor.id,
        action=ACTION_MEMBERSHIP_INVITE,
        entity_type="Membership",
        entity_id=appartenance.id,
        summary=f"Invitation de {utilisateur.email} dans l'organisation",
    )
    await db.commit()
    return _vers_membership(appartenance, utilisateur), True


async def modifier_etat(
    db: AsyncSession, actor: User, organization_id: uuid.UUID, membership_id: uuid.UUID, nouvel_etat: str
) -> dict:
    """Change l'état d'un membership (`invited`, `active`, `suspended`) et incrémente `version`.

    409 `membership_revoked` pour un membership révoqué (seule une nouvelle invitation le réactive).
    Un état identique au courant ne change rien et n'écrit rien."""
    if nouvel_etat not in ETATS_MODIFIABLES:
        raise AppError(code="membership_state_invalid", message="État de membership inconnu.", status_code=422)
    appartenance = await _appartenance_par_id(db, organization_id, membership_id)
    utilisateur = await db.get(User, appartenance.userId)
    if appartenance.status == ETAT_REVOKED:
        raise AppError(code="membership_revoked", message="Membership révoqué : inviter à nouveau.", status_code=409)
    if appartenance.status == nouvel_etat:
        return _vers_membership(appartenance, utilisateur)

    ancien_etat = appartenance.status
    appartenance.status = nouvel_etat
    appartenance.version += 1
    await record_audit_event(
        db,
        organization_id,
        actor.id,
        action=ACTION_MEMBERSHIP_UPDATE,
        entity_type="Membership",
        entity_id=appartenance.id,
        summary=f"Membership de {utilisateur.email} : {ancien_etat} -> {nouvel_etat}",
        changes={"state": {"from": ancien_etat, "to": nouvel_etat}},
    )
    await db.commit()
    return _vers_membership(appartenance, utilisateur)


async def revoquer(db: AsyncSession, actor: User, organization_id: uuid.UUID, membership_id: uuid.UUID) -> None:
    """Révoque le membership : statut `revoked`, rôles de l'utilisateur dans le tenant retirés, audit.

    La ligne est conservée (historique, QE-API-15). Révoquer deux fois ne fait rien de plus."""
    appartenance = await _appartenance_par_id(db, organization_id, membership_id)
    if appartenance.status == ETAT_REVOKED:
        return
    utilisateur = await db.get(User, appartenance.userId)

    appartenance.status = ETAT_REVOKED
    appartenance.version += 1
    await db.execute(delete(UserRole).where(UserRole.organizationId == organization_id, UserRole.userId == appartenance.userId))
    await record_audit_event(
        db,
        organization_id,
        actor.id,
        action=ACTION_MEMBERSHIP_REVOKE,
        entity_type="Membership",
        entity_id=appartenance.id,
        summary=f"Révocation du membership de {utilisateur.email}",
    )
    await db.commit()
