"""Configuration d'intégration et référence de credential (BE-210).

Rôle : créer, faire tourner et révoquer la configuration d'une intégration externe d'un
tenant, et résoudre une référence de credential pour un envoi. La base ne porte que la
référence (`IntegrationCredential.referenceSecret`) ; la valeur vit dans le coffre
`COFFRE_INTEGRATIONS` (magasin en mémoire du processus, même choix que BE-161).

Règles tenues par ce module :
- CA-1 : aucune fonction ne renvoie la valeur d'un secret. Le `GET` de la route ne contient
  donc aucun champ de secret, et un secret enregistré ne peut plus être relu par l'API.
- CA-2 : la valeur n'entre dans aucune ligne, aucun `changes` d'audit et aucun message
  d'erreur. Les `changes` ne contiennent que le fournisseur, l'usage, l'état et le numéro de
  version.
- CA-3 : une révocation coupe la résolution (`resoudre_reference` refuse) et supprime les
  valeurs du coffre.
- CA-4 : une rotation ajoute une version sans supprimer les précédentes ; elles restent
  résolubles jusqu'à la révocation explicite.
- CA-6 : toute lecture ou écriture filtre sur le tenant de l'appelant ; une intégration d'un
  autre tenant est introuvable (404), comme une référence inconnue.

Choix assumés, appliqués sans attendre (écarts avec la définition, recommandation la plus
simple) :
- doublon `(organisation, fournisseur, usage)` : 409 `VERSION_CONFLICT`, faute de code de
  conflit dédié au catalogue BE-151 ;
- rotation ou révocation d'une intégration déjà révoquée : rotation refusée en 409
  `VERSION_CONFLICT` ; révocation idempotente (pas de second audit) ;
- référence révoquée ou sans valeur dans le coffre : 401 `SECRET_EXPIRED`, le code du
  catalogue le plus proche d'un secret qui n'est plus valide.

Les fonctions ne commitent pas : l'appelant gère la transaction.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice, executer_mutation_sensible
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.core.secrets import SecretStore
from app.integrations.models import (
    ETAT_INTEGRATION_CONFIGUREE,
    ETAT_INTEGRATION_REVOQUEE,
    Integration,
    IntegrationCredential,
)

TYPE_ENTITE = "Integration"
ACTION_CREATION = "integration.creee"
ACTION_ROTATION = "integration.secret_roté"
ACTION_REVOCATION = "integration.revoquee"

# Coffre des valeurs de secrets d'intégration. Seules les références sortent en base.
COFFRE_INTEGRATIONS = SecretStore()


def _reference(integration_id: uuid.UUID, version: int) -> str:
    """Nom du secret dans le coffre. Il ne contient jamais la valeur."""
    return f"integration/{integration_id}/v{version}"


def _introuvable() -> ErreurCatalogue:
    """Intégration absente ou d'un autre tenant : même réponse, sans révéler l'existence (CA-6)."""
    return ErreurCatalogue(CodeErreur.TENANT_MISMATCH, detail="intégration introuvable pour ce tenant")


async def _charger(db: AsyncSession, organization_id: uuid.UUID, integration_id: uuid.UUID) -> Integration:
    """Charge l'intégration si elle appartient au tenant ; sinon 404."""
    integration = await db.get(Integration, integration_id)
    if integration is None or integration.organizationId != organization_id:
        raise _introuvable()
    return integration


async def _version_courante(db: AsyncSession, integration_id: uuid.UUID) -> int:
    """Plus haut numéro de version de credential de l'intégration (0 s'il n'y en a aucun)."""
    plus_haut = await db.scalar(
        select(func.max(IntegrationCredential.version)).where(IntegrationCredential.integrationId == integration_id)
    )
    return plus_haut or 0


async def creer_integration(
    db: AsyncSession,
    identite: IdentiteEmettrice,
    *,
    provider: str,
    purpose: str,
    scopes: list[str],
    config_schema_version: int,
    secret: str,
) -> Integration:
    """Crée une intégration à l'état `configured`, avec sa version 1 de credential, et audite.

    Ordre : valeur non vide (`ValueError`), contrôle de doublon (409), puis mutation et audit
    dans un même savepoint. La valeur est déposée dans le coffre après le flush de la ligne
    de référence ; un échec d'audit laisse une valeur orpheline, jamais référencée.
    Retour : l'intégration ajoutée à la session. L'appelant doit `commit()`.
    """
    if not secret:
        raise ValueError("Une intégration exige un secret non vide.")
    organization_id = identite.organization_id
    doublon = await db.scalar(
        select(Integration.id).where(
            Integration.organizationId == organization_id,
            Integration.provider == provider,
            Integration.purpose == purpose,
        )
    )
    if doublon is not None:
        raise ErreurCatalogue(CodeErreur.VERSION_CONFLICT, detail="intégration déjà configurée pour ce fournisseur et cet usage")

    integration_id = uuid.uuid4()
    reference = _reference(integration_id, 1)

    async def mutation(session: AsyncSession) -> Integration:
        integration = Integration(
            id=integration_id,
            organizationId=organization_id,
            provider=provider,
            purpose=purpose,
            scopes=list(scopes),
            configSchemaVersion=config_schema_version,
            state=ETAT_INTEGRATION_CONFIGUREE,
            credentialRef=reference,
        )
        session.add(integration)
        await session.flush()
        session.add(IntegrationCredential(integrationId=integration_id, version=1, referenceSecret=reference))
        await session.flush()
        COFFRE_INTEGRATIONS.rotate(reference, secret)
        return integration

    changes = {"provider": provider, "purpose": purpose, "state": ETAT_INTEGRATION_CONFIGUREE, "credentialVersion": 1}
    return await executer_mutation_sensible(
        db,
        identite,
        organization_id,
        ACTION_CREATION,
        TYPE_ENTITE,
        integration_id,
        f"Intégration {provider}/{purpose} créée",
        mutation,
        changes,
    )


async def lire_integration(db: AsyncSession, organization_id: uuid.UUID, integration_id: uuid.UUID) -> Integration:
    """Intégration du tenant, sans aucune valeur de secret. 404 si absente ou d'un autre tenant."""
    return await _charger(db, organization_id, integration_id)


async def rotater_secret(
    db: AsyncSession,
    identite: IdentiteEmettrice,
    integration_id: uuid.UUID,
    *,
    secret: str,
) -> Integration:
    """Ajoute une version de credential et en fait la référence courante (CA-4).

    Les versions précédentes restent dans le coffre et résolubles jusqu'à la révocation. Une
    intégration révoquée ne tourne plus : 409 `VERSION_CONFLICT`. Audite `integration.secret_roté`
    avec le seul numéro de version.
    """
    if not secret:
        raise ValueError("Une rotation exige un secret non vide.")
    organization_id = identite.organization_id
    integration = await _charger(db, organization_id, integration_id)
    if integration.state == ETAT_INTEGRATION_REVOQUEE:
        raise ErreurCatalogue(CodeErreur.VERSION_CONFLICT, detail="rotation refusée : intégration révoquée")

    version = await _version_courante(db, integration_id) + 1
    reference = _reference(integration_id, version)

    async def mutation(session: AsyncSession) -> Integration:
        session.add(IntegrationCredential(integrationId=integration_id, version=version, referenceSecret=reference))
        integration.credentialRef = reference
        await session.flush()
        COFFRE_INTEGRATIONS.rotate(reference, secret)
        return integration

    return await executer_mutation_sensible(
        db,
        identite,
        organization_id,
        ACTION_ROTATION,
        TYPE_ENTITE,
        integration_id,
        f"Nouvelle version {version} du secret de l'intégration {integration.provider}/{integration.purpose}",
        mutation,
        {"credentialVersion": version},
    )


async def revoquer_integration(
    db: AsyncSession,
    identite: IdentiteEmettrice,
    integration_id: uuid.UUID,
) -> Integration:
    """Passe l'intégration à `revoked` et retire toutes ses valeurs du coffre (CA-3).

    Idempotente : une intégration déjà révoquée est renvoyée telle quelle, sans second audit.
    Les valeurs sont retirées du coffre après le succès de la mutation et de l'audit.
    """
    organization_id = identite.organization_id
    integration = await _charger(db, organization_id, integration_id)
    if integration.state == ETAT_INTEGRATION_REVOQUEE:
        return integration

    async def mutation(session: AsyncSession) -> Integration:
        integration.state = ETAT_INTEGRATION_REVOQUEE
        await session.flush()
        return integration

    revoquee = await executer_mutation_sensible(
        db,
        identite,
        organization_id,
        ACTION_REVOCATION,
        TYPE_ENTITE,
        integration_id,
        f"Intégration {integration.provider}/{integration.purpose} révoquée",
        mutation,
        {"state": ETAT_INTEGRATION_REVOQUEE},
    )
    references = (
        await db.execute(
            select(IntegrationCredential.referenceSecret).where(IntegrationCredential.integrationId == integration_id)
        )
    ).scalars().all()
    for reference in references:
        COFFRE_INTEGRATIONS.supprimer(reference)
    return revoquee


async def resoudre_reference(db: AsyncSession, organization_id: uuid.UUID, reference: str) -> str:
    """Valeur d'un credential pour un envoi, si l'intégration est active et du tenant (CA-3, CA-4).

    Refus, sans aucune lecture de valeur : référence inconnue ou d'un autre tenant (404) ;
    intégration révoquée ou valeur absente du coffre (401 `SECRET_EXPIRED`).
    """
    ligne = (
        await db.execute(
            select(IntegrationCredential.integrationId, Integration.organizationId, Integration.state)
            .join(Integration, Integration.id == IntegrationCredential.integrationId)
            .where(IntegrationCredential.referenceSecret == reference)
        )
    ).first()
    if ligne is None or ligne.organizationId != organization_id:
        raise _introuvable()
    if ligne.state == ETAT_INTEGRATION_REVOQUEE:
        raise ErreurCatalogue(CodeErreur.SECRET_EXPIRED, detail="référence révoquée")
    valeur = COFFRE_INTEGRATIONS.valeur_courante(reference)
    if valeur is None:
        raise ErreurCatalogue(CodeErreur.SECRET_EXPIRED, detail="valeur absente du coffre")
    return valeur
