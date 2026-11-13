"""Émission d'un événement de facturation dans l'outbox (BE-074, CA-1 et CA-4).

Rôle : fournir à la facturation le point d'émission unique. Il applique la garde anti-carte
(`app.billing.events.garde`) puis délègue l'écriture à `app.evenements.outbox.enregistrer_evenement`
(BE-234), qui valide l'enveloppe (BE-150) et écrit `outbox_evenement`.

Contrat de transaction (CA-1) : la fonction n'ouvre ni ne committe de transaction. L'appelant
écrit sa commande dans la même session, appelle cette fonction, puis committe. Si l'enveloppe
est invalide, l'exception remonte et l'appelant doit annuler la commande : une commande sans
événement n'est pas committée.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.events.garde import valider_sans_donnee_carte
from app.evenements.enveloppe import EnveloppeEvenement
from app.evenements.outbox import enregistrer_evenement


async def emettre_evenement_facturation(
    db: AsyncSession,
    donnees: dict[str, Any],
    *,
    emetteur_tenant: uuid.UUID | None,
) -> EnveloppeEvenement:
    """Écrit un événement de facturation dans l'outbox, sans commit, après contrôle des données de carte.

    Erreurs : `SCHEMA_INVALID` si le payload contient un PAN ou un CVV (aucune écriture) ;
    erreurs de `enregistrer_evenement` (`PERMISSION_DENIED`, `SCHEMA_INVALID`, `TENANT_MISMATCH`).
    """
    payload = donnees.get("payload") if isinstance(donnees, dict) else None
    if payload is not None:
        valider_sans_donnee_carte(payload)
    return await enregistrer_evenement(db, donnees, emetteur_tenant=emetteur_tenant)
