"""Registre des versions de contrat : écriture, coexistence et sélection (BE-215).

Règles tenues ici :
- une modification de schéma sur une version existante passe par `changements_cassants` :
  un changement cassant est refusé (`CONTRACT_BREAKING_CHANGE`, 422) et rien n'est écrit ;
- les versions acceptées sont toutes les versions non retirées (N et N-1 coexistent, QE-API-23) ;
- une nouvelle souscription ne peut viser qu'une version `current` (`CONTRACT_VERSION_NOT_SELECTABLE`, 422).

Ce module ne commit pas : l'appelant (route, job ou test) décide de la transaction.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contrats.compatibilite import changements_cassants
from app.contrats.models import ContractVersion
from app.core.errors import AppError


async def _ligne(db: AsyncSession, contract_name: str, version: int) -> ContractVersion | None:
    return (
        await db.execute(
            select(ContractVersion).where(ContractVersion.contractName == contract_name, ContractVersion.version == version)
        )
    ).scalar_one_or_none()


async def enregistrer_version(db: AsyncSession, *, contract_name: str, version: int, schema: dict) -> ContractVersion:
    """Ajoute une version `current` ; refuse une version déjà enregistrée pour ce contrat (422)."""
    if await _ligne(db, contract_name, version) is not None:
        raise AppError(
            code="CONTRACT_VERSION_EXISTS",
            message=f"Version {version} déjà enregistrée pour le contrat {contract_name}.",
            status_code=422,
        )
    ligne = ContractVersion(contractName=contract_name, version=version, status="current", schemaJson=schema)
    db.add(ligne)
    await db.flush()
    return ligne


async def modifier_schema_version(db: AsyncSession, *, contract_name: str, version: int, nouveau_schema: dict) -> ContractVersion:
    """Remplace le schéma d'une version existante si le changement est additif (CA-1, CA-2).

    Erreurs : `CONTRACT_NOT_FOUND` (404) si la version n'existe pas ; `CONTRACT_BREAKING_CHANGE`
    (422) si le changement retire, retype ou rend requis une propriété : il faut alors une
    nouvelle version. En cas d'erreur, le schéma stocké reste inchangé.
    """
    ligne = await _ligne(db, contract_name, version)
    if ligne is None:
        raise AppError(code="CONTRACT_NOT_FOUND", message="Contrat ou version inconnu.", status_code=404)
    cassants = changements_cassants(ligne.schemaJson, nouveau_schema)
    if cassants:
        raise AppError(
            code="CONTRACT_BREAKING_CHANGE",
            message="Changement cassant sans nouvelle version majeure : " + ", ".join(cassants),
            status_code=422,
        )
    ligne.schemaJson = nouveau_schema
    await db.flush()
    return ligne


async def deprecier_version(db: AsyncSession, *, contract_name: str, version: int) -> ContractVersion:
    """Passe une version à `deprecated` : elle reste acceptée mais n'est plus sélectionnable."""
    ligne = await _ligne(db, contract_name, version)
    if ligne is None:
        raise AppError(code="CONTRACT_NOT_FOUND", message="Contrat ou version inconnu.", status_code=404)
    ligne.status = "deprecated"
    await db.flush()
    return ligne


async def versions_acceptees(db: AsyncSession, *, contract_name: str) -> list[int]:
    """Numéros des versions non retirées du contrat, par ordre croissant (coexistence N/N-1)."""
    requete = (
        select(ContractVersion.version)
        .where(ContractVersion.contractName == contract_name, ContractVersion.removedAt.is_(None))
        .order_by(ContractVersion.version)
    )
    return list((await db.execute(requete)).scalars().all())


async def choisir_version_souscription(db: AsyncSession, *, contract_name: str, version: int | None = None) -> int:
    """Version à utiliser pour une nouvelle souscription (CA-5).

    Sans `version`, renvoie la plus haute version `current` non retirée. Avec `version`, la
    renvoie seulement si elle est `current` : une version dépréciée lève
    `CONTRACT_VERSION_NOT_SELECTABLE` (422). Aucune version sélectionnable : `CONTRACT_NOT_FOUND` (404).
    """
    if version is None:
        requete = (
            select(ContractVersion.version)
            .where(
                ContractVersion.contractName == contract_name,
                ContractVersion.status == "current",
                ContractVersion.removedAt.is_(None),
            )
            .order_by(ContractVersion.version.desc())
            .limit(1)
        )
        trouvee = (await db.execute(requete)).scalar_one_or_none()
        if trouvee is None:
            raise AppError(code="CONTRACT_NOT_FOUND", message="Aucune version sélectionnable pour ce contrat.", status_code=404)
        return trouvee

    ligne = await _ligne(db, contract_name, version)
    if ligne is None or ligne.removedAt is not None:
        raise AppError(code="CONTRACT_NOT_FOUND", message="Contrat ou version inconnu.", status_code=404)
    if ligne.status != "current":
        raise AppError(
            code="CONTRACT_VERSION_NOT_SELECTABLE",
            message=f"Version {version} non sélectionnable pour une nouvelle souscription.",
            status_code=422,
        )
    return ligne.version


async def lister_versions(db: AsyncSession, *, contract_name: str) -> list[dict]:
    """Versions du contrat (toutes, retirées comprises), triées par numéro croissant."""
    requete = select(ContractVersion).where(ContractVersion.contractName == contract_name).order_by(ContractVersion.version)
    lignes = (await db.execute(requete)).scalars().all()
    return [
        {
            "version": ligne.version,
            "status": ligne.status,
            "removedAt": ligne.removedAt.isoformat() if ligne.removedAt else None,
        }
        for ligne in lignes
    ]
