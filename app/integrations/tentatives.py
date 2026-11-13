"""Journal des tentatives d'intégration et politique de backoff (BE-164).

Rôle : exécuter un effet externe (appel à un fournisseur, à un connecteur) en gardant une
trace de chaque tentative, sans jamais stocker le contenu échangé.

Garanties :
- chaque tentative écrit une ligne `tentativeIntegration` avec son issue (`succes` ou
  `echec`), le code d'erreur éventuel, la durée mesurée et la corrélation (CA-1) ;
- un échec transitoire (`ErreurTransitoire`) planifie la tentative suivante à
  `maintenant + délai_backoff(tentativeNo)` (CA-2) ; un échec définitif
  (`ErreurDefinitive`) ne planifie rien ;
- la clé d'effet est le couple (connecteur, événement) : si une tentative `succes` existe
  déjà pour ce couple, l'effet n'est pas réexécuté et la ligne existante est rendue (CA-3) ;
- la lecture du journal exige la permission `integrations.read` et ne renvoie que les lignes
  de l'organisation demandée (CA-4, CA-5).

Politique de backoff : délai = base x 2^(tentativeNo - 1), plafonné à `plafond`. La base et
le plafond sont NON DÉFINIS dans la définition (QE-PAR-09) : ils sont lus dans
`settings.INTEGRATION_BACKOFF_BASE_SECONDS` et `settings.INTEGRATION_BACKOFF_CAP_SECONDS`,
sans valeur par défaut codée. Une valeur absente lève `ConfigurationBackoffAbsente`.

Le module ne contient aucun adaptateur d'intégration : l'appelant fournit l'effet sous forme
de fonction asynchrone. Les codes d'erreur sont les libellés fournis par l'effet ; ils ne
contiennent jamais de contenu métier. La table ne porte aucune colonne de payload.

Documentation de module : `app/integrations/tentatives.md`.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.integrations.models import ISSUE_ECHEC, ISSUE_SUCCES, TentativeIntegration
from app.integrations.permissions import INTEGRATIONS_READ
from app.rbac.service import user_has_permission

if TYPE_CHECKING:  # Type seulement : évite un import runtime entre capacités.
    from app.audit.ecriture import IdentiteEmettrice


class ConfigurationBackoffAbsente(RuntimeError):
    """Base ou plafond du backoff non renseigné dans la configuration (QE-PAR-09)."""


class ErreurTransitoire(Exception):
    """Échec où une nouvelle tentative a un sens (délai réseau, indisponibilité).

    `code` est le libellé journalisé dans `codeErreur` (60 caractères au plus).
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ErreurDefinitive(Exception):
    """Échec où réessayer ne changera rien (refus métier, configuration invalide)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class PolitiqueBackoff:
    """Paramètres du backoff, en secondes. Les deux valeurs sont strictement positives."""

    base_secondes: int
    plafond_secondes: int


def lire_politique_backoff() -> PolitiqueBackoff:
    """Lit la politique depuis la configuration à chaque appel (jamais à l'import).

    Lève `ConfigurationBackoffAbsente` si l'une des deux valeurs est absente : le service
    refuse de deviner un délai de reprise.
    """
    base = settings.INTEGRATION_BACKOFF_BASE_SECONDS
    plafond = settings.INTEGRATION_BACKOFF_CAP_SECONDS
    if base is None or plafond is None:
        raise ConfigurationBackoffAbsente(
            "INTEGRATION_BACKOFF_BASE_SECONDS et INTEGRATION_BACKOFF_CAP_SECONDS doivent être renseignés."
        )
    return PolitiqueBackoff(base_secondes=base, plafond_secondes=plafond)


def delai_backoff(tentative_no: int, politique: PolitiqueBackoff) -> int:
    """Délai en secondes avant la tentative suivant la tentative `tentative_no`.

    Croissance exponentielle en base 2 (base, 2 base, 4 base...), plafonnée. Le premier
    échec (`tentative_no` = 1) attend la base. `tentative_no` doit être au moins 1 :
    une valeur nulle ou négative lève `ValueError` plutôt que de produire un délai absurde.
    """
    if tentative_no < 1:
        raise ValueError("tentative_no doit être au moins 1")
    brut = politique.base_secondes * (2 ** (tentative_no - 1))
    return min(brut, politique.plafond_secondes)


async def _succes_existant(db: AsyncSession, connecteur_id: uuid.UUID, event_id: uuid.UUID) -> TentativeIntegration | None:
    return await db.scalar(
        select(TentativeIntegration).where(
            TentativeIntegration.connecteurId == connecteur_id,
            TentativeIntegration.eventId == event_id,
            TentativeIntegration.issue == ISSUE_SUCCES,
        )
    )


async def executer_effet(
    db: AsyncSession,
    *,
    connecteur_id: uuid.UUID,
    organization_id: uuid.UUID,
    correlation_id: uuid.UUID,
    event_id: uuid.UUID,
    effet: Callable[[], Awaitable[None]],
    politique: PolitiqueBackoff,
    maintenant: datetime | None = None,
    tentative_no: int = 1,
) -> TentativeIntegration:
    """Exécute `effet` une fois pour la clé (connecteur, événement) et journalise la tentative.

    - Si une tentative `succes` existe déjà pour la clé, la ligne existante est rendue et
      `effet` n'est pas appelé (CA-3) ;
    - sinon `effet` est appelé et sa durée mesurée. Une `ErreurTransitoire` ou
      `ErreurDefinitive` est journalisée comme `echec` et n'est pas relancée : l'appelant
      lit `prochaineTentativeAt` pour planifier la reprise. Toute autre exception n'est pas
      interceptée : aucune ligne n'est écrite pour un bug de l'appelant ;
    - `maintenant` est injectable pour les tests ; par défaut l'heure UTC courante.

    La fonction ajoute la ligne à la session sans `commit()` : l'appelant valide.
    """
    existante = await _succes_existant(db, connecteur_id, event_id)
    if existante is not None:
        return existante

    instant = maintenant if maintenant is not None else datetime.now(timezone.utc)
    debut = time.perf_counter()
    issue = ISSUE_SUCCES
    code_erreur: str | None = None
    prochaine: datetime | None = None
    try:
        await effet()
    except ErreurTransitoire as exc:
        issue, code_erreur = ISSUE_ECHEC, exc.code
        delai = delai_backoff(tentative_no, politique)
        prochaine = instant + timedelta(seconds=delai)
    except ErreurDefinitive as exc:
        issue, code_erreur = ISSUE_ECHEC, exc.code
    duree_ms = int((time.perf_counter() - debut) * 1000)

    ligne = TentativeIntegration(
        id=uuid.uuid4(),
        connecteurId=connecteur_id,
        organizationId=organization_id,
        correlationId=correlation_id,
        eventId=event_id,
        issue=issue,
        codeErreur=code_erreur,
        dureeMs=duree_ms,
        tentativeNo=tentative_no,
        prochaineTentativeAt=prochaine,
    )
    db.add(ligne)
    await db.flush()
    return ligne


async def lister_tentatives(
    db: AsyncSession,
    identite: IdentiteEmettrice | None,
    organization_id: uuid.UUID,
) -> list[TentativeIntegration]:
    """Liste les tentatives d'une organisation, pour un utilisateur qui a `integrations.read`.

    Sans identité, ou sans la permission dans cette organisation : `PERMISSION_DENIED` (403),
    aucune donnée lue. Les lignes sont filtrées sur `organization_id` (CA-5) ; un tenant
    ne voit jamais les tentatives d'un autre.
    """
    if identite is None:
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail="lecture de tentatives sans identité")
    if not await user_has_permission(db, identite.user_id, organization_id, INTEGRATIONS_READ):
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail="integrations.read absente")
    resultat = await db.execute(
        select(TentativeIntegration)
        .where(TentativeIntegration.organizationId == organization_id)
        .order_by(TentativeIntegration.createdAt, TentativeIntegration.id)
    )
    return list(resultat.scalars().all())
