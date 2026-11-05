"""File de lettres mortes d'intégration et reprise manuelle tracée (BE-165).

Rôle : recueillir les tentatives d'intégration définitivement échouées (journal BE-164) dans
une file de lettres mortes, puis permettre à un opérateur de les reprendre à la main, avec un
motif, une trace d'audit et une garantie de non-doublon.

Garanties :
- CA-1 : `deplacer_en_lettre_morte` ne crée une lettre que pour une tentative `echec` sans
  prochaine tentative planifiée (échec définitif) ; une tentative encore reprogrammable est
  refusée (`ValueError`). Une seule lettre par tentative : un second appel rend la lettre
  existante.
- CA-2 : la reprise exige un motif non vide (`SCHEMA_INVALID`, 422). Avec motif, elle écrit
  `operateur`, `motif`, `reprisAt` et `originalId`, appelle la relance une seule fois, et
  journalise l'action `integration.lettre_morte.reprendre` dans la même transaction.
- CA-3 : sans `integrations.manage` dans l'organisation, la reprise est refusée
  (`PERMISSION_DENIED`, 403) avant toute lecture de la lettre ; rien n'est relancé.
- CA-4 : une lettre dont `reprisAt` est déjà posé renvoie `REPLAY_DUPLICATE` (409) ; la
  relance n'est pas rejouée.
- CA-5 : une lettre d'une autre organisation est invisible : `TENANT_MISMATCH` (404) pour la
  reprise, absence de la liste pour la lecture.

Le module ne contient aucun adaptateur d'intégration : la relance est fournie par l'appelant
sous forme de fonction asynchrone recevant la lettre, comme `executer_effet` (BE-164). La
relance s'exécute dans le savepoint de la mutation : si elle lève, la reprise est annulée et
la lettre reste reprenable.

Documentation de route : `app/integrations/lettres-mortes.md`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice, executer_mutation_sensible
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.integrations.models import ISSUE_ECHEC, LettreMorte, TentativeIntegration
from app.integrations.permissions import INTEGRATIONS_MANAGE, INTEGRATIONS_READ
from app.rbac.service import user_has_permission

ACTION_REPRISE = "integration.lettre_morte.reprendre"
TYPE_ENTITE = "lettreMorte"

Relance = Callable[[LettreMorte], Awaitable[None]]


async def deplacer_en_lettre_morte(
    db: AsyncSession,
    *,
    tentative_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> LettreMorte:
    """Déplace un échec définitif de `tentativeIntegration` vers `lettreMorte` (CA-1).

    Précondition : la tentative existe dans `organization_id`, est `echec`, et n'a aucune
    `prochaineTentativeAt`. Sinon `ValueError` (la tentative peut encore être reprise par le
    backoff, ou ce n'est pas un échec). Une tentative inconnue du tenant lève `ValueError`
    aussi : l'appelant est un service interne, pas une route.

    Idempotent : si une lettre existe déjà pour cette tentative, elle est rendue telle quelle.
    `originalId` reçoit l'`eventId` de la tentative. Ne fait pas de `commit()`.
    """
    existante = await db.scalar(select(LettreMorte).where(LettreMorte.tentativeId == tentative_id))
    if existante is not None:
        return existante

    tentative = await db.scalar(
        select(TentativeIntegration).where(
            TentativeIntegration.id == tentative_id,
            TentativeIntegration.organizationId == organization_id,
        )
    )
    if tentative is None:
        raise ValueError("tentative introuvable dans ce tenant")
    if tentative.issue != ISSUE_ECHEC:
        raise ValueError("seule une tentative en échec peut devenir une lettre morte")
    if tentative.prochaineTentativeAt is not None:
        raise ValueError("la tentative a encore une reprise planifiée : pas un échec définitif")

    lettre = LettreMorte(
        tentativeId=tentative.id,
        organizationId=organization_id,
        originalId=tentative.eventId,
    )
    db.add(lettre)
    await db.flush()
    return lettre


async def lister_lettres_mortes(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    organization_id: uuid.UUID,
) -> list[LettreMorte]:
    """Liste les lettres mortes d'une organisation, pour un utilisateur avec `integrations.read`.

    Sans identité ou sans la permission dans `organization_id` : `PERMISSION_DENIED` (403),
    aucune donnée lue (CA-5 : filtre sur le tenant demandé, jamais sur un autre).
    """
    if identite is None:
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail="lecture de lettres mortes sans identité")
    if not await user_has_permission(db, identite.user_id, organization_id, INTEGRATIONS_READ):
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail="integrations.read absente")
    resultat = await db.execute(
        select(LettreMorte)
        .where(LettreMorte.organizationId == organization_id)
        .order_by(LettreMorte.createdAt, LettreMorte.id)
    )
    return list(resultat.scalars().all())


async def reprendre_lettre_morte(
    db: AsyncSession,
    *,
    identite: IdentiteEmettrice | None,
    organization_id: uuid.UUID,
    lettre_id: uuid.UUID,
    motif: str | None,
    relance: Relance,
) -> LettreMorte:
    """Reprend une lettre morte à la main, avec motif, trace d'audit et garde contre le rejeu.

    Ordre des contrôles (chacun avant toute écriture) :
    1. `integrations.manage` dans `organization_id` : sinon `PERMISSION_DENIED` (403) (CA-3) ;
    2. motif non vide après `strip()` : sinon `SCHEMA_INVALID` (422) (CA-2) ;
    3. lettre du tenant : sinon `TENANT_MISMATCH` (404) (CA-5) ;
    4. lettre pas encore reprise (`reprisAt` nul) : sinon `REPLAY_DUPLICATE` (409) (CA-4).

    Puis, dans un même savepoint (`executer_mutation_sensible`) : pose `operateur`, `motif`,
    `reprisAt` et `originalId`, appelle `relance(lettre)` une fois, et écrit l'entrée d'audit.
    Une exception de `relance` annule la reprise entière.

    Ne fait pas de `commit()` : l'appelant valide la transaction.
    """
    if identite is None or not await user_has_permission(
        db, identite.user_id, organization_id, INTEGRATIONS_MANAGE
    ):
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail="integrations.manage absente")

    motif_propre = (motif or "").strip()
    if not motif_propre:
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="motif de reprise vide")

    lettre = await db.scalar(
        select(LettreMorte).where(LettreMorte.id == lettre_id, LettreMorte.organizationId == organization_id)
    )
    if lettre is None:
        raise ErreurCatalogue(CodeErreur.TENANT_MISMATCH, detail="lettre absente du tenant demandé")
    if lettre.reprisAt is not None:
        raise ErreurCatalogue(CodeErreur.REPLAY_DUPLICATE, detail="lettre déjà reprise")

    async def mutation(session: AsyncSession) -> LettreMorte:
        lettre.operateur = identite.user_id
        lettre.motif = motif_propre
        lettre.reprisAt = datetime.now(timezone.utc)
        await session.flush()
        await relance(lettre)
        return lettre

    return await executer_mutation_sensible(
        db,
        identite,
        organization_id,
        ACTION_REPRISE,
        TYPE_ENTITE,
        lettre.id,
        "Reprise manuelle d'une lettre morte d'intégration",
        mutation,
        motif=motif_propre,
    )
