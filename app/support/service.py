"""Service de l'accès support (BE-262) : octroi, contrôle d'accès, action sous accès.

Règles :
- lire une organisation exige `support.read` ET un accès actif (fenêtre datée,
  même organisation, même support) ; sinon 403 ;
- écrire exige en plus le mode `ecriture` ET `support.write_sensible`. Un accès
  en `lecture` renvoie 403 avant toute mutation (CA-2) ;
- octroyer un accès exige `rbac.grant.manage` chez l'auteur, la justification
  est journalisée via `record_sensitive_action` (CA-3), et l'accès est écrit
  dans la même transaction que son audit (CA-5).

Chaque fonction publique valide sa transaction (commit) ou l'annule en cas
d'erreur : un appelant ne doit pas dépendre d'un commit implicite.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.audit.service import record_audit_event, record_sensitive_action
from app.core.errors import AppError
from app.rbac.permissions import GRANT_MANAGE
from app.rbac.service import user_has_permission
from app.support.models import AccesSupport
from app.support.permissions import MODE_ECRITURE, MODE_LECTURE, MODES, SUPPORT_READ, SUPPORT_WRITE_SENSIBLE

# Durée d'un accès quand l'octroi n'en précise pas (QE-FON-05, non défini).
DUREE_PAR_DEFAUT = timedelta(hours=24)


def _refus(code: str, message: str) -> AppError:
    return AppError(code=code, message=message, status_code=403)


async def _acces_actif(
    db: AsyncSession, organization_id: uuid.UUID, support_user_id: uuid.UUID, maintenant: datetime
) -> AccesSupport | None:
    """Accès dont la fenêtre contient `maintenant` ; le plus récent s'il y en a plusieurs."""
    resultat = await db.execute(
        select(AccesSupport)
        .where(
            AccesSupport.organizationId == organization_id,
            AccesSupport.supportUserId == support_user_id,
            AccesSupport.debutUtc <= maintenant,
            AccesSupport.finUtc > maintenant,
        )
        .order_by(AccesSupport.createdAt.desc())
    )
    return resultat.scalars().first()


async def verifier_acces(
    db: AsyncSession, organization_id: uuid.UUID, support_user_id: uuid.UUID, *, ecriture: bool
) -> AccesSupport:
    """Renvoie l'accès actif qui autorise la lecture, ou l'écriture si `ecriture`.

    Lève 403 sans rien écrire : permission absente, aucun accès actif (expiré
    inclus, CA-6), mode `lecture` pour une écriture (CA-2), ou permission
    `support.write_sensible` absente. Le contrôle se fait sur l'organisation du
    chemin : un accès sur une autre organisation n'entre jamais en compte (CA-4)."""
    if not await user_has_permission(db, support_user_id, organization_id, SUPPORT_READ):
        raise _refus("permission_denied", "Permission support.read absente pour cette organisation.")

    acces = await _acces_actif(db, organization_id, support_user_id, datetime.now(timezone.utc))
    if acces is None:
        raise _refus("acces_support_absent", "Aucun accès support actif sur cette organisation.")

    if ecriture:
        if acces.mode != MODE_ECRITURE:
            raise _refus("acces_support_lecture_seule", "L'accès support est en lecture seule : écriture refusée.")
        if not await user_has_permission(db, support_user_id, organization_id, SUPPORT_WRITE_SENSIBLE):
            raise _refus("permission_denied", "Permission support.write_sensible absente pour cette organisation.")
    return acces


async def creer_acces(
    db: AsyncSession,
    organization_id: uuid.UUID,
    acteur_user_id: uuid.UUID,
    support_user_id: uuid.UUID,
    justification: str,
    mode: str = MODE_LECTURE,
    fin_utc: datetime | None = None,
) -> AccesSupport:
    """Octroie un accès support, avec journalisation de l'octroi dans la même transaction.

    Refus : `mode` hors `MODES` (422), droit `rbac.grant.manage` absent (403),
    fin déjà passée (422), justification vide (422 via `record_sensitive_action`,
    sans ligne écrite, CA-3). `mode` vaut `lecture` par défaut (CA-1)."""
    if mode not in MODES:
        raise AppError(code="mode_acces_invalide", message="Mode d'accès support inconnu.", status_code=422)
    if not await user_has_permission(db, acteur_user_id, organization_id, GRANT_MANAGE):
        raise _refus("permission_denied", "Droit rbac.grant.manage requis pour octroyer un accès support.")

    maintenant = datetime.now(timezone.utc)
    fin = fin_utc or maintenant + DUREE_PAR_DEFAUT
    if fin <= maintenant:
        raise AppError(code="fin_acces_invalide", message="La fin de l'accès doit être dans le futur.", status_code=422)

    acces = AccesSupport(
        organizationId=organization_id,
        supportUserId=support_user_id,
        creeParUserId=acteur_user_id,
        mode=mode,
        justification=justification.strip(),
        debutUtc=maintenant,
        finUtc=fin,
        approbationId=None,
    )
    db.add(acces)
    await db.flush()
    try:
        await record_sensitive_action(
            db,
            organization_id,
            acteur_user_id,
            "support.acces.cree",
            "AccesSupport",
            acces.id,
            f"Accès support ({mode}) accordé",
            justification=justification,
        )
    except AppError:
        await db.rollback()
        raise
    await db.commit()
    await db.refresh(acces)
    return acces


async def obtenir_acces_courant(
    db: AsyncSession, organization_id: uuid.UUID, support_user_id: uuid.UUID
) -> AccesSupport:
    """Lit l'accès actif du support sur l'organisation, et journalise cette lecture (CA-5)."""
    acces = await verifier_acces(db, organization_id, support_user_id, ecriture=False)
    acces_id = acces.id
    await record_audit_event(
        db,
        organization_id,
        support_user_id,
        "support.acces.lecture",
        "AccesSupport",
        acces_id,
        "Consultation de l'accès support courant",
        reason=acces.justification,
    )
    await db.commit()
    await db.refresh(acces)
    return acces


async def executer_sous_acces(
    db: AsyncSession,
    organization_id: uuid.UUID,
    support_user_id: uuid.UUID,
    *,
    action: str,
    ecriture: bool,
    entity_type: str,
    entity_id: uuid.UUID | None,
    summary: str,
    mutation=None,
) -> AuditEvent:
    """Exécute une action sous accès support : contrôle, mutation, audit, commit.

    `mutation` est une coroutine `async def f(db)` appliquée seulement après le
    contrôle d'accès. Toute erreur avant le commit annule la mutation et
    l'audit ensemble (la transaction est celle de `db`). Renvoie la ligne d'audit
    (CA-5)."""
    acces = await verifier_acces(db, organization_id, support_user_id, ecriture=ecriture)
    if mutation is not None:
        await mutation(db)
    entree = await record_audit_event(
        db,
        organization_id,
        support_user_id,
        action,
        entity_type,
        entity_id,
        summary,
        reason=acces.justification,
    )
    await db.commit()
    return entree
