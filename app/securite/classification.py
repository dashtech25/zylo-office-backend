"""Classification et minimisation des données sensibles des événements (BE-174).

Rôle : deux garde-fous appliqués aux payloads d'événement avant qu'ils ne sortent du producteur
ou n'arrivent à un consommateur.

1. `verifier_classification_payload` (CA-1, CA-2) : chaque champ de premier niveau du payload
   doit avoir une classification déclarée dans `classification_champ`, sinon `SCHEMA_INVALID`.
   Un numéro de carte bancaire (suite de 13 à 19 chiffres, espaces ou tirets tolérés, valide au
   sens de Luhn) est refusé, quel que soit le champ où il apparaît.
2. `filtrer_payload_pour_consommateur` (CA-3, CA-4) : renvoie une copie du payload où ne subsistent
   que les champs que le consommateur a le droit de recevoir. Un tenant différent de celui de
   l'événement lève `TENANT_MISMATCH` ; rien n'est alors renvoyé.

Choix de conception :
- Liste déclarative plutôt que liste noire : un champ inconnu est refusé, pas laissé passer.
- Expurgation plutôt que `403` pour un champ sans droit : c'est l'option retenue par la
  définition (NON DÉFINI, QE-PAR-01). Le consommateur reçoit l'événement sans le champ.
- Aucune valeur de payload n'entre dans un message d'erreur ni dans un journal : les erreurs
  utilisent le catalogue BE-151 (`ErreurCatalogue`), qui n'expose que la phrase fixe de la fiche.

Ce module ne publie rien et n'écrit rien : il valide et filtre. Le branchement sur l'outbox
(`app.evenements.outbox.enregistrer_evenement`) n'est pas fait ici, car les événements existants
(BE-150, BE-166) publient des champs non déclarés ; cette mise en cohérence est à décider.
"""

import re
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.erreurs.codes import CodeErreur, ErreurCatalogue

# Niveaux de classification acceptés. `payment` désigne une donnée de paiement : elle ne doit
# jamais circuler dans un payload, la détection par Luhn est le filet de sécurité.
CLASSIFICATIONS = ("public", "internal", "confidential", "payment")

# Séquence de 13 à 19 chiffres, éventuellement séparés par espaces ou tirets : format d'un PAN.
_MOTIF_PAN = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")


def _luhn_valide(chiffres: str) -> bool:
    """Vrai si la suite de chiffres passe le contrôle de Luhn (somme de contrôle des cartes)."""
    total = 0
    for rang, caractere in enumerate(reversed(chiffres)):
        chiffre = int(caractere)
        if rang % 2 == 1:
            chiffre *= 2
            if chiffre > 9:
                chiffre -= 9
        total += chiffre
    return total % 10 == 0


def _contient_numero_de_carte(valeur: Any) -> bool:
    """Parcourt récursivement le payload à la recherche d'un numéro de carte valide (Luhn).

    Seules les chaînes sont examinées : un nombre entier nu (montant, identifiant numérique)
    n'est pas un PAN au sens de ce contrôle, et il est traité par sa classification.
    """
    if isinstance(valeur, str):
        for correspondance in _MOTIF_PAN.finditer(valeur):
            chiffres = re.sub(r"[ -]", "", correspondance.group(0))
            if 13 <= len(chiffres) <= 19 and _luhn_valide(chiffres):
                return True
        return False
    if isinstance(valeur, Mapping):
        return any(_contient_numero_de_carte(v) for v in valeur.values())
    if isinstance(valeur, (list, tuple)):
        return any(_contient_numero_de_carte(v) for v in valeur)
    return False


async def _classifications_du_type(db: AsyncSession, type_evenement: str) -> dict[str, Any]:
    """Renvoie `{champ: ligne}` des classifications déclarées pour un type d'événement."""
    from app.securite.models import ClassificationChamp

    lignes = await db.execute(select(ClassificationChamp).where(ClassificationChamp.typeEvenement == type_evenement))
    return {ligne.champ: ligne for ligne in lignes.scalars()}


async def verifier_classification_payload(db: AsyncSession, type_evenement: str, payload: Mapping[str, Any]) -> None:
    """Refuse un payload dont un champ n'est pas classé, ou qui contient un numéro de carte.

    Ordre des contrôles : numéro de carte (CA-2) puis champs non déclarés (CA-1). Les deux
    refus lèvent `SCHEMA_INVALID` (catalogue BE-151), sans reprendre la valeur fautive.

    Ne lit que `classification_champ` ; ne modifie rien. Renvoie `None` si le payload est
    acceptable.
    """
    if _contient_numero_de_carte(payload):
        raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="numéro de carte détecté dans le payload")

    declarees = await _classifications_du_type(db, type_evenement)
    for champ in payload:
        if champ not in declarees:
            raise ErreurCatalogue(CodeErreur.SCHEMA_INVALID, detail="champ de payload sans classification déclarée")


async def filtrer_payload_pour_consommateur(
    db: AsyncSession,
    type_evenement: str,
    payload: Mapping[str, Any],
    *,
    tenant_evenement: uuid.UUID,
    tenant_consommateur: uuid.UUID,
    permissions: Iterable[str],
) -> dict[str, Any]:
    """Renvoie le payload réduit aux champs que le consommateur peut recevoir.

    Un champ classé `public` est toujours conservé. Un autre champ est conservé si sa ligne de
    classification déclare au moins une permission détenue par le consommateur (`consommablePar`
    intersecté avec `permissions`). Sont retirés : les champs sans ligne, les champs non publics
    dont `consommablePar` est vide ou NULL, et ceux dont aucune permission ne correspond.

    Lève `TENANT_MISMATCH` si le tenant de l'événement n'est pas celui du consommateur (CA-4) :
    la classification n'ouvre jamais un passage inter-tenant.
    """
    if tenant_evenement != tenant_consommateur:
        raise ErreurCatalogue(CodeErreur.TENANT_MISMATCH, detail="sortie inter-tenant refusée")

    detenues = set(permissions)
    declarees = await _classifications_du_type(db, type_evenement)
    visibles: dict[str, Any] = {}
    for champ, valeur in payload.items():
        ligne = declarees.get(champ)
        if ligne is None:
            continue
        if ligne.classification == "public":
            visibles[champ] = valeur
        elif ligne.consommablePar and detenues.intersection(ligne.consommablePar):
            visibles[champ] = valeur
    return visibles
