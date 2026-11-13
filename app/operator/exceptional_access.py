"""Accès exceptionnel au contenu client (BE-138), refusé par défaut.

Statut : BLOCKED tant que la décision Q-06 (support et accès sensible) et les
exigences PH-16 (QE-ADM-06) ne sont pas tranchées. Tant que c'est le cas, aucun
rôle n'obtient cet accès : toute demande reçoit 403, y compris depuis le rôle
sécurité / incident commander (`securite_incident_commander`, BE-121). L'accès
cross-tenant reste donc interdit.

Route :
- `POST /api/v1/admin/organizations/{organization_id}/exceptional-access` :
  renvoie toujours 403 (`exceptional_access_denied`) et journalise le refus.

Pourquoi une route qui refuse toujours et non l'absence de route : la définition
demande que chaque tentative soit tracée (CA-2). Une route absente ne produirait
aucune trace ; une route refusante produit une entrée d'audit datée, avec le
motif et la corrélation, sans qu'aucun contenu ne sorte.

Garanties :
- CA-1 : aucun rôle ni portée ne débloque la route. Ne pas ajouter de
  condition d'autorisation ici sans décision Q-06 : une exception ouverte
  accorderait l'accès à tout le monde sur ce chemin.
- CA-2 : chaque refus écrit une entrée `audit_event` (action
  `admin.exceptional_access.refuse`, résultat `refused`) avant de répondre.
  `changes.motifRefus` porte le code du motif de refus ; `changes.motifDemande`
  porte le motif saisi par le demandeur, s'il y en a un. La corrélation est
  l'identifiant de requête (`X-Request-Id`), via `ecrire_evenement_admin`.
- CA-3 (isolation tenant) : l'entrée d'audit est rattachée au tenant visé, pour
  que ce tenant voie la tentative. La réponse ne reprend aucune donnée du tenant
  (ni nom, ni slug, ni identifiant hors celui que l'appelant a fourni).
- CA-4 : l'enveloppe d'erreur ne contient que `code` et `message`. Aucune
  donnée de contenu client n'est renvoyée, ni dans le corps ni dans les champs.

Si l'organisation visée n'existe pas, l'entrée d'audit est écrite sans tenant
(portée plateforme) : la clé étrangère de `audit_event` interdit de la rattacher
à un identifiant inconnu, et le refus doit être tracé quand même.

Aucune table ni migration propre : l'événement de refus vit dans `audit_event`
(BE-007). Module de domaine : il ne dépend d'aucun module métier.
"""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.admin_audit import ecrire_evenement_admin
from app.core.database import get_db
from app.core.errors import AppError
from app.core.logging import request_id_ctx
from app.core.security import get_current_user
from app.identity.models import Organization, User

router = APIRouter()

ACTION_REFUS = "admin.exceptional_access.refuse"
CODE_REFUS = "exceptional_access_denied"
MOTIF_REFUS = "acces_contenu_exceptionnel_non_autorise_q06"
TYPE_ENTITE = "Organization"


class DemandeAccesExceptionnel(BaseModel):
    """Corps facultatif de la demande. Le motif saisi est seulement journalisé.

    Le corps est lu après l'authentification et n'ouvre rien : il ne sert qu'à
    consigner la raison invoquée dans l'audit (CA-2)."""

    motif: str | None = Field(default=None, max_length=1000)


@router.post(
    "/organizations/{organization_id}/exceptional-access",
    status_code=403,
    summary="Demander un accès exceptionnel au contenu d'un client (BE-138, refusé)",
    responses={403: {"description": "Accès exceptionnel refusé pour tout appelant (Q-06)."}},
)
async def demander_acces_exceptionnel(
    organization_id: uuid.UUID,
    data: DemandeAccesExceptionnel | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Journalise la tentative puis répond 403.

    L'entrée d'audit est écrite et validée avant la levée de l'erreur, pour que
    le refus soit tracé même si la réponse est perdue. Une requête sans
    identifiant de corrélation lève l'erreur d'audit de `ecrire_evenement_admin`
    (422) : aucune trace n'est alors écrite, et le refus n'est pas silencieux.
    """
    cible = await db.get(Organization, organization_id)
    await ecrire_evenement_admin(
        db,
        organization_id=cible.id if cible is not None else None,
        actor_user_id=current_user.id,
        action=ACTION_REFUS,
        entity_type=TYPE_ENTITE,
        entity_id=organization_id,
        summary="Accès exceptionnel au contenu client refusé (BE-138, Q-06)",
        correlation_id=request_id_ctx.get(),
        changes={
            "motifRefus": MOTIF_REFUS,
            "motifDemande": data.motif if data is not None else None,
        },
        result="refused",
    )
    await db.commit()
    raise AppError(
        code=CODE_REFUS,
        message="Accès exceptionnel au contenu client refusé.",
        status_code=403,
    )
