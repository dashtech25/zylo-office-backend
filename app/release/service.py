"""Service public du domaine release (BE-250).

Trois opérations :
  - `enregistrer_release` : crée la release de validation (source d'une promotion) ;
  - `promouvoir_release` : copie un artefact vers un environnement cible, sous conditions ;
  - `identifier_rollback` : retrouve la release antérieure et compatible d'un environnement.

Règles :
  - une promotion exige la permission `PERMISSION_PROMOTION` chez l'approbateur, sinon 403 ;
  - l'approbateur doit être distinct du demandeur, sinon 403 ;
  - tous les gates requis doivent être « reussi » dans la release source, sinon 409 ;
  - une version ne peut être présente qu'une fois par environnement, sinon 409 ;
  - aucune opération ne modifie une ligne existante : seules des lignes sont ajoutées.

Le service ne commit pas : l'appelant (route, commande ou test) possède la transaction.
Les permissions sont passées par l'appelant, déjà résolues par `rbac` ; ce service ne
lit pas la base IAM, pour rester une capacité de plateforme sans dépendance vers rbac.
"""

import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.release.models import ReleaseRecord
from app.release.permissions import PERMISSION_PROMOTION

GATE_REUSSI = "reussi"


async def enregistrer_release(
    db: AsyncSession,
    *,
    version: str,
    hash_artefact: str,
    reference_source: str,
    sbom_reference: str,
    config_version: int,
    resultats_gates: dict,
    demandeur_id: uuid.UUID,
    environnement: str,
) -> ReleaseRecord:
    """Ajoute la release d'un artefact dans un environnement et la renvoie (non commitée).

    Sert à enregistrer la validation d'un artefact produit par la chaîne de build.
    Une version déjà présente dans l'environnement lève 409 `release.version.existante`.
    """
    existante = (await db.execute(
        select(ReleaseRecord.id).where(
            ReleaseRecord.version == version,
            ReleaseRecord.environnement == environnement,
        )
    )).first()
    if existante is not None:
        raise AppError(
            "release.version.existante",
            "Cette version est déjà enregistrée dans cet environnement.",
            status_code=409,
        )
    release = ReleaseRecord(
        version=version,
        hash_artefact=hash_artefact,
        reference_source=reference_source,
        sbom_reference=sbom_reference,
        config_version=config_version,
        resultats_gates=dict(resultats_gates),
        environnement=environnement,
        demandeur_id=demandeur_id,
        # Un enregistrement de validation n'a pas d'approbation distincte : l'approbateur
        # est le demandeur lui-même. La promotion, elle, exige une approbation distincte.
        approbateur_id=demandeur_id,
        promue_le=datetime.now(timezone.utc),
    )
    db.add(release)
    await db.flush()
    return release


async def promouvoir_release(
    db: AsyncSession,
    *,
    source_id: uuid.UUID,
    environnement_cible: str,
    demandeur_id: uuid.UUID,
    approbateur_id: uuid.UUID,
    permissions_approbateur: frozenset[str],
    gates_requis: Iterable[str],
    resultats_gates_courants: dict | None = None,
) -> ReleaseRecord:
    """Promeut l'artefact de la release `source_id` vers `environnement_cible`.

    Contrôles, dans l'ordre :
      1. l'approbateur possède `PERMISSION_PROMOTION` (sinon 403 `release.promotion.refusee`) ;
      2. approbateur différent du demandeur (sinon 403 `release.approbation.non_distincte`) ;
      3. la source existe (sinon 404 `release.introuvable`) ;
      4. chaque gate de `gates_requis` vaut « reussi » dans les résultats (sinon 409
         `release.gate.non_reussi`). `resultats_gates_courants` remplace les résultats
         stockés quand ils sont fournis, pour refléter le dernier passage des gates ;
      5. la version n'est pas déjà présente dans l'environnement cible (sinon 409).

    La nouvelle ligne recopie hash, source, SBOM, version et config de la source : le même
    artefact est donc promu, jamais reconstruit (BE-250 CA-1).
    """
    if PERMISSION_PROMOTION not in permissions_approbateur:
        raise AppError(
            "release.promotion.refusee",
            "Droit insuffisant pour promouvoir une release.",
            status_code=403,
        )
    if approbateur_id == demandeur_id:
        raise AppError(
            "release.approbation.non_distincte",
            "La promotion doit être approuvée par une personne distincte du demandeur.",
            status_code=403,
        )

    source = await db.get(ReleaseRecord, source_id)
    if source is None:
        raise AppError("release.introuvable", "Release source introuvable.", status_code=404)

    gates = source.resultats_gates if resultats_gates_courants is None else resultats_gates_courants
    gates_manquants = [g for g in gates_requis if gates.get(g) != GATE_REUSSI]
    if gates_manquants:
        raise AppError(
            "release.gate.non_reussi",
            "Gates requis non réussis : " + ", ".join(gates_manquants),
            status_code=409,
            details=[{"gates": gates_manquants}],
        )

    deja_presente = (await db.execute(
        select(ReleaseRecord.id).where(
            ReleaseRecord.version == source.version,
            ReleaseRecord.environnement == environnement_cible,
        )
    )).first()
    if deja_presente is not None:
        raise AppError(
            "release.version.existante",
            "Cette version est déjà présente dans l'environnement cible.",
            status_code=409,
        )

    promue = ReleaseRecord(
        version=source.version,
        hash_artefact=source.hash_artefact,
        reference_source=source.reference_source,
        sbom_reference=source.sbom_reference,
        config_version=source.config_version,
        resultats_gates=dict(gates),
        environnement=environnement_cible,
        demandeur_id=demandeur_id,
        approbateur_id=approbateur_id,
        promue_le=datetime.now(timezone.utc),
    )
    db.add(promue)
    await db.flush()
    return promue


async def identifier_rollback(
    db: AsyncSession,
    *,
    environnement: str,
    version_courante: str,
    config_version_supportee: int,
) -> ReleaseRecord | None:
    """Renvoie la release à restaurer pour revenir en arrière dans `environnement`.

    La cible est la release la plus récente, promue avant la version courante, dont la
    configuration est compatible : `config_version <= config_version_supportee`, c'est-à-dire
    que le code en place sait lire son schéma de configuration. Renvoie None si aucune
    release antérieure n'est compatible, ou si la version courante n'est pas présente.
    """
    courante = (await db.execute(
        select(ReleaseRecord).where(
            ReleaseRecord.environnement == environnement,
            ReleaseRecord.version == version_courante,
        )
    )).scalar_one_or_none()
    if courante is None:
        return None

    candidates = (await db.execute(
        select(ReleaseRecord)
        .where(
            ReleaseRecord.environnement == environnement,
            ReleaseRecord.promue_le < courante.promue_le,
        )
        .order_by(ReleaseRecord.promue_le.desc())
    )).scalars().all()
    for candidate in candidates:
        if candidate.config_version <= config_version_supportee:
            return candidate
    return None
