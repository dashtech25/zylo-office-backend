"""BE-169 : moteur de notification (audience, déduplication, suppression).

Tests écrits d'après la définition `### BE-169` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : un événement d'origine produit une notification par destinataire éligible,
  résolu à l'envoi (statut `en_attente`) ;
- CA-2 : un destinataire sans consentement, ou non éligible (compte suspendu), produit
  un statut `supprimee` avec le motif `CONSENT_SUPPRESSED` ;
- CA-3 (refus) : un producteur sans droit de consultation du sujet ne produit aucune
  notification, refus `403` PERMISSION_DENIED ;
- CA-4 : un même événement rejoué ne crée pas de doublon ; la contrainte d'unicité
  `(eventId, categorieCode, destinataireId)` est testée en base ;
- CA-5 (isolation tenant) : l'audience est résolue uniquement dans le tenant de
  l'événement ; un membre d'un autre tenant est exclu.

Points non tranchés par la définition (signalés dans le rapport, pas présumés ici) :
- QE-PAR-27 : le droit de consulter le sujet est porté par le moteur d'autorisation
  unique (BE-226) ; le test passe donc par `decide` réel, avec une permission de test ;
- « éligible » n'est pas défini : le test retient un compte actif et non supprimé ;
- la règle est insérée directement, car sa création exige l'autorité plateforme (BE-167)
  et le catalogue d'événements (BE-176) n'existe pas encore.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.core.security import hash_password
from app.identity.models import OrganizationUser, User
from app.identity.schemas import CreateOrganizationRequest
from app.identity.service import create_organization
from app.notifications.categories import creer_categorie
from app.notifications.models import Notification, RegleNotification
from app.notifications.moteur import produire_notifications
from app.notifications.preferences import modifier_preference
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.service import assign_role, get_or_create_permission

PERMISSION_CONSULTER = "be169.sujet.consulter"
MODULE_TEST = "be169"
AUDIENCE = "membres_organisation"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé avant
    et après lui (même remise à zéro que les autres tests de notifications)."""
    await engine.dispose()
    yield
    await engine.dispose()


def _suffixe() -> str:
    return uuid.uuid4().hex[:10]


async def _utilisateur(db, label: str, status: str = "active") -> User:
    user = User(
        email=f"be169-{label}-{_suffixe()}@example.com",
        hashedPassword=hash_password("x"),
        fullName=label,
        status=status,
    )
    db.add(user)
    await db.flush()
    return user


async def _membre(db, organization_id: uuid.UUID, user: User) -> None:
    db.add(OrganizationUser(organizationId=organization_id, userId=user.id))
    await db.flush()


async def _donner_droit_a_proprietaire(db, organization_id: uuid.UUID, owner: User) -> None:
    """Le propriétaire détient la permission qu'il attribue (non-élévation)."""
    owner_role = (
        await db.execute(
            select(Role).join(UserRole, UserRole.roleId == Role.id).where(
                UserRole.userId == owner.id, UserRole.organizationId == organization_id, Role.code == "owner"
            )
        )
    ).scalar_one()
    permission = await get_or_create_permission(db, PERMISSION_CONSULTER, MODULE_TEST, "Consulter le sujet (test)")
    db.add(RolePermission(roleId=owner_role.id, permissionId=permission.id))
    await db.flush()


async def _lecteur(db, organization_id: uuid.UUID, owner: User, membre: User) -> None:
    """Donne à `membre` un rôle d'organisation portant la permission de consultation."""
    role = Role(organizationId=organization_id, code=f"lecteur-{_suffixe()}", name="Lecteur (test)")
    db.add(role)
    await db.flush()
    permission = await get_or_create_permission(db, PERMISSION_CONSULTER, MODULE_TEST, "Consulter le sujet (test)")
    db.add(RolePermission(roleId=role.id, permissionId=permission.id))
    await db.flush()
    await assign_role(db, organization_id, owner.id, membre.id, role.id)


async def _monde(db):
    """Une organisation, un propriétaire qui peut consulter le sujet, une règle
    événement -> catégorie avec l'audience « membres de l'organisation ».

    Retourne (propriétaire, organisation, type d'événement, code de catégorie)."""
    owner = await _utilisateur(db, "proprietaire")
    org = await create_organization(
        db, owner, CreateOrganizationRequest(name=f"BE169 {_suffixe()}", slug=f"be169-{_suffixe()}")
    )
    await _donner_droit_a_proprietaire(db, org.id, owner)
    code = f"BE169-{_suffixe()}"
    evenement_type = f"BE169.Test.{_suffixe()}"
    await db.commit()
    await creer_categorie(db, code=code, libelle="Catégorie BE-169", audience_regle=AUDIENCE)
    db.add(RegleNotification(evenementType=evenement_type, categorieCode=code, audience=AUDIENCE))
    await db.commit()
    return owner, org, evenement_type, code


async def _produire(db, org_id, owner_id, evenement_type, *, event_id=None, producteur=None):
    """Appelle le moteur pour un sujet de l'organisation donnée."""
    return await produire_notifications(
        db,
        eventId=event_id or uuid.uuid4(),
        evenementType=evenement_type,
        tenantId=org_id,
        producteur=producteur,
        permissionConsultation=PERMISSION_CONSULTER,
        sujetType="dossier",
        sujetId=uuid.uuid4(),
        sujetTenantId=org_id,
    )


async def _notifications(event_id: uuid.UUID) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list((await db.execute(select(Notification).where(Notification.eventId == event_id))).scalars().all())


async def test_ca1_une_notification_par_destinataire_eligible():
    """CA-1 : chaque membre éligible de l'audience reçoit une notification `en_attente`."""
    async with AsyncSessionLocal() as db:
        owner, org, evenement_type, code = await _monde(db)
        membre = await _utilisateur(db, "membre")
        await _membre(db, org.id, membre)
        await _lecteur(db, org.id, owner, membre)
        await db.commit()
        event_id = uuid.uuid4()

        await produire_notifications(
            db,
            eventId=event_id,
            evenementType=evenement_type,
            tenantId=org.id,
            producteur=owner,
            permissionConsultation=PERMISSION_CONSULTER,
            sujetType="dossier",
            sujetId=uuid.uuid4(),
            sujetTenantId=org.id,
        )

    lignes = await _notifications(event_id)
    destinataires = {ligne.destinataireId for ligne in lignes}
    assert destinataires == {owner.id, membre.id}
    assert all(ligne.statut == "en_attente" and ligne.motifSuppression is None for ligne in lignes)
    assert all(ligne.categorieCode == code for ligne in lignes)


async def test_ca2_sans_consentement_ou_non_eligible_produit_supprimee():
    """CA-2 : désinscrit ou compte suspendu => `supprimee` avec `CONSENT_SUPPRESSED`.
    Le membre consentant reste `en_attente`."""
    async with AsyncSessionLocal() as db:
        owner, org, evenement_type, code = await _monde(db)
        desinscrit = await _utilisateur(db, "desinscrit")
        suspendu = await _utilisateur(db, "suspendu", status="suspended")
        for membre in (desinscrit, suspendu):
            await _membre(db, org.id, membre)
            await _lecteur(db, org.id, owner, membre)
        await db.commit()
        await modifier_preference(
            db,
            organization_id=org.id,
            acteur_id=desinscrit.id,
            utilisateur_id=desinscrit.id,
            categorie_code=code,
            consentement=False,
        )
        event_id = uuid.uuid4()

        await produire_notifications(
            db,
            eventId=event_id,
            evenementType=evenement_type,
            tenantId=org.id,
            producteur=owner,
            permissionConsultation=PERMISSION_CONSULTER,
            sujetType="dossier",
            sujetId=uuid.uuid4(),
            sujetTenantId=org.id,
        )

    par_destinataire = {ligne.destinataireId: ligne for ligne in await _notifications(event_id)}
    assert par_destinataire[desinscrit.id].statut == "supprimee"
    assert par_destinataire[desinscrit.id].motifSuppression == "CONSENT_SUPPRESSED"
    assert par_destinataire[suspendu.id].statut == "supprimee"
    assert par_destinataire[suspendu.id].motifSuppression == "CONSENT_SUPPRESSED"
    assert par_destinataire[owner.id].statut == "en_attente"


async def test_ca3_producteur_sans_droit_de_consultation_ne_produit_rien():
    """CA-3 : un producteur sans droit de consulter le sujet reçoit `403` PERMISSION_DENIED
    et aucune notification n'est écrite."""
    async with AsyncSessionLocal() as db:
        owner, org, evenement_type, _code = await _monde(db)
        sans_droit = await _utilisateur(db, "sans-droit")
        await _membre(db, org.id, sans_droit)
        await db.commit()
        event_id = uuid.uuid4()

        with pytest.raises(AppError) as erreur:
            await produire_notifications(
                db,
                eventId=event_id,
                evenementType=evenement_type,
                tenantId=org.id,
                producteur=sans_droit,
                permissionConsultation=PERMISSION_CONSULTER,
                sujetType="dossier",
                sujetId=uuid.uuid4(),
                sujetTenantId=org.id,
            )

    assert erreur.value.code == "PERMISSION_DENIED"
    assert erreur.value.status_code == 403
    assert await _notifications(event_id) == []


async def test_ca4_evenement_rejoue_ne_cree_pas_de_doublon():
    """CA-4 : rejouer le même événement ne crée aucune nouvelle ligne, et la contrainte
    d'unicité refuse un doublon écrit directement en base."""
    async with AsyncSessionLocal() as db:
        owner, org, evenement_type, code = await _monde(db)
        event_id = uuid.uuid4()
        premiere = await produire_notifications(
            db,
            eventId=event_id,
            evenementType=evenement_type,
            tenantId=org.id,
            producteur=owner,
            permissionConsultation=PERMISSION_CONSULTER,
            sujetType="dossier",
            sujetId=uuid.uuid4(),
            sujetTenantId=org.id,
        )
        rejeu = await produire_notifications(
            db,
            eventId=event_id,
            evenementType=evenement_type,
            tenantId=org.id,
            producteur=owner,
            permissionConsultation=PERMISSION_CONSULTER,
            sujetType="dossier",
            sujetId=uuid.uuid4(),
            sujetTenantId=org.id,
        )

    assert len(premiere) == 1
    assert rejeu == []
    assert len(await _notifications(event_id)) == 1

    async with AsyncSessionLocal() as db:
        db.add(Notification(eventId=event_id, categorieCode=code, destinataireId=owner.id, statut="en_attente"))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_ca5_audience_limitee_au_tenant_de_l_evenement():
    """CA-5 : un membre d'une autre organisation, même actif et consentant, n'est pas
    destinataire de l'événement de l'organisation A."""
    async with AsyncSessionLocal() as db:
        owner, org, evenement_type, _code = await _monde(db)
        autre_owner = await _utilisateur(db, "autre-tenant")
        autre_org = await create_organization(
            db, autre_owner, CreateOrganizationRequest(name=f"BE169 B {_suffixe()}", slug=f"be169-b-{_suffixe()}")
        )
        await db.commit()
        event_id = uuid.uuid4()

        await produire_notifications(
            db,
            eventId=event_id,
            evenementType=evenement_type,
            tenantId=org.id,
            producteur=owner,
            permissionConsultation=PERMISSION_CONSULTER,
            sujetType="dossier",
            sujetId=uuid.uuid4(),
            sujetTenantId=org.id,
        )

    destinataires = {ligne.destinataireId for ligne in await _notifications(event_id)}
    assert autre_owner.id not in destinataires
    assert destinataires == {owner.id}
    assert autre_org.id != org.id
