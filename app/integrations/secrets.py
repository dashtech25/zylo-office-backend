"""Secrets d'intégration : références en base, valeurs dans le coffre (BE-161).

Rôle : enregistrer la valeur d'un secret d'intégration et la résoudre pour un envoi, sans
qu'elle sorte jamais du coffre. La base ne porte que la référence (`SecretIntegration`,
table `secret_integration`).

Règles tenues par ce module :
- CA-1 : la valeur n'est écrite que dans le coffre (`SecretStore`). Elle n'entre dans
  aucune ligne de table, aucun objet renvoyé, aucun audit (`changes` ne contient que la
  version et l'échéance) et aucun message d'erreur.
- CA-2 : un secret dont `expireAt` est atteint est refusé `SECRET_EXPIRED` (401, catalogue
  BE-151) avant toute résolution : l'appelant n'obtient aucune valeur et n'envoie rien.
- CA-3 : la résolution de valeur est réservée au service d'intégration
  (`AppelantService`). Tout autre appelant, utilisateur ou administrateur compris, reçoit
  `PERMISSION_DENIED` (403) avant toute lecture. Aucune route ne l'expose (BE-162 n'expose
  que les métadonnées).
- CA-4 : un connecteur n'est résolu que pour son propre tenant (`organizationId` égal à
  celui de l'appel), sinon `TENANT_MISMATCH`. Un enregistrement de secret suit la règle de
  portée du registre (`verifier_portee`, BE-160).

Versions : chaque enregistrement crée une version (1, 2, ...) ; la plus haute est la valeur
courante. L'ancienne version reste dans le coffre mais n'est plus résolue.

Coffre : `SecretStore` (mémoire du processus) sert de coffre en attendant le choix du
coffre réel. Recommandation appliquée (QE-PAR-10) : secrets désignés par référence, sans
technologie imposée. Conséquence connue : une valeur enregistrée est perdue au redémarrage
tant que le coffre persistant n'est pas branché (point ouvert à QE-BE161-01).

Les fonctions ne commitent pas : l'appelant gère la transaction.
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.core.errors import AppError
from app.core.secrets import SecretStore
from app.integrations.models import SecretIntegration
from app.integrations.registre import (
    ecrire_mutation_connecteur,
    charger_connecteur,
    verifier_portee,
)

ACTION_ENREGISTREMENT = "connecteur.secret_enregistre"
TYPE_ENTITE = "Connecteur"


@dataclass(frozen=True)
class AppelantService:
    """Appelant technique du service d'intégration : seul habilité à résoudre une valeur (CA-3).

    Une identité utilisateur n'est jamais un `AppelantService`, d'où le refus de toute
    lecture par un utilisateur, administrateur compris."""

    nom: str


SERVICE_INTEGRATION = AppelantService("integration")


def _reference(connecteur_id: uuid.UUID, version: int) -> str:
    """Nom du secret dans le coffre. Il ne contient jamais la valeur."""
    return f"integration/{connecteur_id}/v{version}"


async def enregistrer_secret(
    db: AsyncSession,
    store: SecretStore,
    identite: IdentiteEmettrice | None,
    connecteur_id: uuid.UUID,
    valeur: str,
    *,
    expire_at: dt.datetime | None = None,
    est_admin_plateforme: bool = False,
) -> SecretIntegration:
    """Enregistre une nouvelle version du secret du connecteur et écrit son audit.

    Ordre, sans écriture avant la fin des contrôles :
    1. valeur vide refusée (`ValueError`) : une clé vide ouvrirait l'accès ;
    2. connecteur introuvable : 404 ;
    3. droits de portée (`verifier_portee`) : 403 ou `TENANT_MISMATCH` (CA-4) ;
    4. valeur déposée dans le coffre sous une référence nouvelle ;
    5. ligne `secret_integration` et audit `connecteur.secret_enregistre`, sans la valeur.

    `expire_at` est optionnel (QE-PAR-09) ; s'il est atteint, la résolution échoue (CA-2).
    Retour : la ligne ajoutée à la session. L'appelant doit `commit()`.
    """
    if not valeur:
        raise ValueError("Un secret d'intégration exige une valeur non vide.")
    connecteur = await charger_connecteur(db, connecteur_id)
    verifier_portee(identite, connecteur.portee, connecteur.organizationId, est_admin_plateforme)

    version_precedente = (
        await db.execute(
            select(func.max(SecretIntegration.version)).where(SecretIntegration.connecteurId == connecteur_id)
        )
    ).scalar_one()
    version = (version_precedente or 0) + 1
    reference = _reference(connecteur_id, version)
    # Le coffre reçoit la valeur ; la base ne reçoit que la référence (CA-1).
    store.rotate(reference, valeur)

    ligne = SecretIntegration(
        connecteurId=connecteur_id,
        referenceSecret=reference,
        version=version,
        expireAt=expire_at,
    )

    async def mutation(session: AsyncSession) -> SecretIntegration:
        session.add(ligne)
        await session.flush()
        return ligne

    changes = {
        "version": version,
        "expireAt": expire_at.isoformat() if expire_at is not None else None,
        "portee": connecteur.portee,
    }
    return await ecrire_mutation_connecteur(
        db,
        identite,
        connecteur,
        ACTION_ENREGISTREMENT,
        f"Nouvelle version {version} du secret du connecteur {connecteur.nom}",
        mutation,
        changes,
    )


async def resoudre_secret_pour_envoi(
    db: AsyncSession,
    store: SecretStore,
    appelant: object,
    connecteur_id: uuid.UUID,
    organization_id: uuid.UUID | None,
    maintenant: dt.datetime,
) -> str:
    """Valeur courante du secret d'un connecteur, pour un envoi. Réservé au service (CA-3).

    Contrôles, dans l'ordre et avant toute lecture de valeur :
    1. `appelant` n'est pas le service d'intégration : `PERMISSION_DENIED` (403) ;
    2. connecteur introuvable : 404 ;
    3. `organization_id` différent de l'organisation du connecteur : `TENANT_MISMATCH` (CA-4) ;
       un connecteur global a une organisation nulle, il n'est donc résolu que sans tenant ;
    4. aucune version enregistrée, ou valeur absente du coffre : 404 `secret_integration_absent`
       (code local, à ajouter au catalogue, QE-BE161-02) ;
    5. version courante expirée (`expireAt` <= `maintenant`) : `SECRET_EXPIRED` (CA-2).

    Le détail d'un refus n'expose jamais la valeur. Retour : la valeur en clair, à utiliser
    tout de suite pour l'envoi et à ne pas journaliser.
    """
    if not isinstance(appelant, AppelantService):
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail="lecture de secret réservée au service d'intégration")

    connecteur = await charger_connecteur(db, connecteur_id)
    if connecteur.organizationId != organization_id:
        raise ErreurCatalogue(CodeErreur.TENANT_MISMATCH, detail="secret d'un autre tenant")

    ligne = (
        await db.execute(
            select(SecretIntegration)
            .where(SecretIntegration.connecteurId == connecteur_id)
            .order_by(SecretIntegration.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if ligne is None:
        raise AppError(code="secret_integration_absent", message="Secret d'intégration absent.", status_code=404)

    if ligne.expireAt is not None and ligne.expireAt <= maintenant:
        raise ErreurCatalogue(CodeErreur.SECRET_EXPIRED, detail=f"connecteur {connecteur_id} version {ligne.version}")

    valeur = store.valeur_courante(ligne.referenceSecret)
    if valeur is None:
        raise AppError(code="secret_integration_absent", message="Secret d'intégration absent.", status_code=404)
    return valeur
