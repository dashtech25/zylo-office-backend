"""Service du cycle de vie du tenant (BE-185).

Trois fonctions publiques : `creer_tenant`, `lire_tenant`, `transitionner`. Les
routes ne font que valider la requête, appeler ces fonctions et valider la
transaction.

Ordre des contrôles d'une transition (le premier échec gagne) :
1. droit `platform.tenant.manage` (403, sans toucher à la base) ;
2. tenant existant (404) ;
3. version attendue égale à la version courante (409 `version_conflict`). C'est
   ce contrôle qui rend une demande identique rejouée inoffensive : après la
   première, la version a changé, donc la seconde reçoit 409 (CA-5) ;
4. transition permise par le graphe (422, CA-1).

Chaque mutation réussie écrit, dans le même savepoint, une entrée d'audit
(`tenant.transition`) et une entrée outbox plateforme (CA-4). Si l'audit échoue,
la mutation est annulée et `AUDIT_WRITE_FAILED` (500) est levé : la politique
est fermée (fail-closed), comme pour les mutations sensibles de BE-153.

Lecture : un membre du tenant (organisation de même identifiant, rattachement
`organizationUser`) lit son tenant tant qu'il n'est pas `closed` ; tout autre
utilisateur reçoit 404, sans distinguer « inexistant » de « pas à vous ». La
plateforme lit tous les tenants.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.core.errors import AppError
from app.core.versioning import lever_conflit_de_version
from app.evenements.outbox import enregistrer_evenement_plateforme
from app.identity.models import Organization, OrganizationUser, Tenant
from app.tenants.machine import transition_autorisee
from app.tenants.permissions import a_droit_gestion_tenant, exiger_gestion_tenant

ACTION_CREATION = "tenant.create"
ACTION_TRANSITION = "tenant.transition"
TYPE_EVENEMENT_TRANSITION = "Plateforme.tenant.transition"
TYPE_ENTITE = "tenant"


async def _auditer(
    db: AsyncSession,
    acteur_id: uuid.UUID,
    action: str,
    tenant_id: uuid.UUID,
    resume: str,
    changes: dict,
) -> None:
    """Écrit l'entrée d'audit d'une action plateforme sur un tenant.

    `sans_organisation=True` : le tenant n'a pas forcément d'organisation (sa clé
    étrangère vers `organization` ne serait pas satisfaite), et l'action relève de
    la plateforme. Toute erreur d'écriture devient `AUDIT_WRITE_FAILED` (CA-4, fail-closed).
    """
    try:
        await record_audit_event(
            db,
            None,
            acteur_id,
            action,
            TYPE_ENTITE,
            tenant_id,
            resume,
            changes,
            sans_organisation=True,
        )
    except Exception as exc:
        raise ErreurCatalogue(CodeErreur.AUDIT_WRITE_FAILED, detail=f"{type(exc).__name__}: {exc}") from exc


async def _publier_transition(db: AsyncSession, acteur_id: uuid.UUID, tenant: Tenant, de: str, vers: str) -> None:
    """Écrit l'événement de transition dans l'outbox plateforme (CA-4).

    L'événement n'a pas de `tenantId` d'enveloppe : c'est un événement de la
    plateforme qui décrit un tenant, donc il relève de `Plateforme.` (BE-234). Le
    tenant est porté par `scope` et `subject`. Aucun secret dans le payload.
    """
    identifiant = str(tenant.tenantId)
    await enregistrer_evenement_plateforme(
        db,
        {
            "eventId": uuid.uuid4(),
            "eventType": TYPE_EVENEMENT_TRANSITION,
            "schemaVersion": 1,
            "occurredAt": datetime.now(timezone.utc),
            "tenantId": None,
            "scope": {"type": TYPE_ENTITE, "id": identifiant},
            "actor": {"type": "humain", "userId": str(acteur_id)},
            "subject": {"type": TYPE_ENTITE, "id": identifiant},
            "dataClassification": "internal",
            "correlationId": None,
            "causationId": None,
            "payload": {"fromState": de, "toState": vers, "version": tenant.version},
        },
        emetteur_plateforme=True,
    )


async def creer_tenant(db: AsyncSession, acteur_id: uuid.UUID, slug: str) -> Tenant:
    """Crée un tenant en `requested`, version 1 (demande de création, QE-API-01).

    Droit : `platform.tenant.manage`. Un slug déjà pris renvoie 409 : le slug est
    unique (QE-API-05, QE-API-28). La contrainte de base reste la garantie finale ;
    la vérification préalable donne seulement un message propre.
    """
    exiger_gestion_tenant(acteur_id)
    existant = await db.execute(select(Tenant.tenantId).where(Tenant.slug == slug))
    if existant.first() is not None:
        raise AppError(code="tenant_slug_conflict", message="Ce slug de tenant est déjà utilisé.", status_code=409)

    tenant = Tenant(slug=slug, state="requested", version=1)
    try:
        async with db.begin_nested():
            db.add(tenant)
            await db.flush()
            await _auditer(db, acteur_id, ACTION_CREATION, tenant.tenantId, f"Demande de création du tenant {slug}", {"state": "requested"})
    except IntegrityError as exc:
        raise AppError(code="tenant_slug_conflict", message="Ce slug de tenant est déjà utilisé.", status_code=409) from exc
    return tenant


async def _est_membre(db: AsyncSession, acteur_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
    """Vrai si l'utilisateur est rattaché à l'organisation de même identifiant (organisation non supprimée)."""
    stmt = (
        select(OrganizationUser.id)
        .join(Organization, Organization.id == OrganizationUser.organizationId)
        .where(
            OrganizationUser.organizationId == tenant_id,
            OrganizationUser.userId == acteur_id,
            Organization.deletedAt.is_(None),
        )
    )
    return (await db.execute(stmt)).first() is not None


async def lire_tenant(db: AsyncSession, acteur_id: uuid.UUID, tenant_id: uuid.UUID) -> Tenant:
    """Lit un tenant selon le droit du demandeur (voir la docstring du module).

    Un tenant inconnu, un tenant sans rattachement de l'acteur, ou un tenant
    `closed` pour un membre renvoient tous la même 404 `tenant_not_found`.
    """
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise _tenant_introuvable()
    if a_droit_gestion_tenant(acteur_id):
        return tenant
    if tenant.state == "closed" or not await _est_membre(db, acteur_id, tenant_id):
        raise _tenant_introuvable()
    return tenant


async def transitionner(
    db: AsyncSession,
    acteur_id: uuid.UUID,
    tenant_id: uuid.UUID,
    cible: str,
    version_attendue: int,
) -> Tenant:
    """Fait passer le tenant de son état courant à `cible`, si le graphe le permet.

    Le tenant est verrouillé (`FOR UPDATE`) pour que deux transitions concurrentes
    ne lisent pas la même version. Voir l'ordre des contrôles en tête de module.
    """
    exiger_gestion_tenant(acteur_id)
    stmt = select(Tenant).where(Tenant.tenantId == tenant_id).with_for_update()
    tenant = (await db.execute(stmt)).scalar_one_or_none()
    if tenant is None:
        raise _tenant_introuvable()
    if tenant.version != version_attendue:
        lever_conflit_de_version(tenant.version, datetime.now(timezone.utc))
    de = tenant.state
    if not transition_autorisee(de, cible):
        raise AppError(
            code="tenant_transition_interdite",
            message=f"Transition de {de} vers {cible} interdite par le cycle de vie du tenant.",
            status_code=422,
        )

    async with db.begin_nested():
        tenant.state = cible
        tenant.version += 1
        if cible == "closed":
            tenant.closedAt = datetime.now(timezone.utc)
        await db.flush()
        await _auditer(
            db,
            acteur_id,
            ACTION_TRANSITION,
            tenant.tenantId,
            f"Transition du tenant de {de} vers {cible}",
            {"fromState": de, "toState": cible, "version": tenant.version},
        )
        await _publier_transition(db, acteur_id, tenant, de, cible)
    return tenant


def _tenant_introuvable() -> AppError:
    """404 uniforme : « inexistant », « pas à vous » et « fermé pour un membre » ont la même réponse."""
    return AppError(code="tenant_not_found", message="Tenant introuvable.", status_code=404)
