"""Registre des schémas d'événements versionnés (BE-176, CA-1 et CA-2).

Rôle : tenir, pour chaque type d'événement (`eventType`, au format `domaine.action`), la liste de
ses versions de schéma de payload (`schemaVersion`), et refuser à l'enregistrement une version
incompatible avec la précédente.

Règle de compatibilité (CA-2, recommandation appliquée faute de règle définie : QE-PAR-08) :
- une nouvelle version qui retire un champ de `required` par rapport à la version précédente
  est incompatible, sauf si elle déclare une rupture : `compatibleDepuis` doit être strictement
  supérieur à `schemaVersion` de la version précédente ;
- un ajout de champ, ou un retrait de champ non requis, est compatible ;
- une version déjà enregistrée pour le même type est refusée (la contrainte d'unicité de la
  base le garantirait, mais l'erreur métier est levée avant l'écriture).

Refus : `AppError` `SCHEMA_INVALID` (422, catalogue BE-151). Aucun message ne recopie le contenu
du schéma. La couverture du catalogue (CA-1) se vérifie par `verifier_couverture`, qui échoue si
un type attendu n'a aucune version active, ou si une version attendue est absente.

Ce module ne commit pas : l'appelant (route, job ou test) décide de la transaction.
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.evenements.models import SchemaEvenement


def _champs_requis(schema: dict) -> set[str]:
    """Champs déclarés obligatoires par un schéma JSON (absence de `required` = aucun)."""
    return set(schema.get("required", []) or [])


async def _version_precedente(db: AsyncSession, eventType: str, schemaVersion: int) -> SchemaEvenement | None:
    """Version de même type la plus haute strictement inférieure à `schemaVersion`, ou None."""
    requete = (
        select(SchemaEvenement)
        .where(SchemaEvenement.eventType == eventType, SchemaEvenement.schemaVersion < schemaVersion)
        .order_by(SchemaEvenement.schemaVersion.desc())
        .limit(1)
    )
    return (await db.execute(requete)).scalar_one_or_none()


async def enregistrer_schema(
    db: AsyncSession,
    *,
    eventType: str,
    schemaVersion: int,
    schemaJson: dict,
    compatibleDepuis: int,
    actif: bool = True,
) -> SchemaEvenement:
    """Ajoute une version de schéma au registre après contrôle de compatibilité (CA-2).

    Erreurs : `SCHEMA_INVALID` (422) si la version existe déjà pour ce type, si
    `compatibleDepuis` sort de l'intervalle `1..schemaVersion`, ou si un champ requis de la
    version précédente disparaît sans rupture déclarée. En cas d'erreur, rien n'est ajouté à la
    session.
    """
    if not (1 <= compatibleDepuis <= schemaVersion):
        raise AppError(code="SCHEMA_INVALID", message="compatibleDepuis hors de l'intervalle 1..schemaVersion.", status_code=422)

    existante = (
        await db.execute(
            select(SchemaEvenement.id).where(
                SchemaEvenement.eventType == eventType,
                SchemaEvenement.schemaVersion == schemaVersion,
            )
        )
    ).scalar_one_or_none()
    if existante is not None:
        raise AppError(
            code="SCHEMA_INVALID",
            message=f"Version {schemaVersion} déjà enregistrée pour le type {eventType}.",
            status_code=422,
        )

    precedente = await _version_precedente(db, eventType, schemaVersion)
    if precedente is not None:
        champs_retires = _champs_requis(precedente.schemaJson) - _champs_requis(schemaJson)
        rupture_declaree = compatibleDepuis > precedente.schemaVersion
        if champs_retires and not rupture_declaree:
            raise AppError(
                code="SCHEMA_INVALID",
                message=f"Champ requis retiré sans nouvelle version compatible pour le type {eventType}.",
                status_code=422,
            )

    ligne = SchemaEvenement(
        eventType=eventType,
        schemaVersion=schemaVersion,
        schemaJson=schemaJson,
        compatibleDepuis=compatibleDepuis,
        actif=actif,
    )
    db.add(ligne)
    await db.flush()
    return ligne


async def verifier_couverture(
    db: AsyncSession,
    types_attendus: Iterable[str],
    versions_attendues: dict[str, int] | None = None,
) -> None:
    """Vérifie que chaque type attendu a au moins une version active (CA-1).

    `versions_attendues` (optionnel) exige en plus la présence d'une version précise pour un type.
    Erreur : `SCHEMA_INVALID` (422) listant les types non couverts. Le nom du type figure dans le
    message ; aucun contenu de schéma n'est renvoyé.
    """
    manquants: list[str] = []
    for type_evenement in types_attendus:
        requete = select(SchemaEvenement.schemaVersion).where(
            SchemaEvenement.eventType == type_evenement,
            SchemaEvenement.actif.is_(True),
        )
        versions = set((await db.execute(requete)).scalars().all())
        version_exigee = (versions_attendues or {}).get(type_evenement)
        if not versions or (version_exigee is not None and version_exigee not in versions):
            manquants.append(type_evenement)

    if manquants:
        raise AppError(
            code="SCHEMA_INVALID",
            message="Types d'événements sans schéma actif : " + ", ".join(manquants),
            status_code=422,
        )


async def lister_types(db: AsyncSession) -> list[dict]:
    """Catalogue : chaque type présent au registre, avec ses versions triées par numéro croissant."""
    lignes = (await db.execute(select(SchemaEvenement).order_by(SchemaEvenement.eventType, SchemaEvenement.schemaVersion))).scalars().all()
    catalogue: dict[str, list[dict]] = {}
    for ligne in lignes:
        catalogue.setdefault(ligne.eventType, []).append(
            {
                "schemaVersion": ligne.schemaVersion,
                "compatibleDepuis": ligne.compatibleDepuis,
                "actif": ligne.actif,
                "schemaJson": ligne.schemaJson,
            }
        )
    return [{"eventType": type_evenement, "versions": versions} for type_evenement, versions in catalogue.items()]
