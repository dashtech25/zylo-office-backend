"""Liens vers des comptes de fournisseurs externes (BE-239).

Rôle : connecter un tenant à un compte externe, le déconnecter, lister ses liens et
réconcilier le curseur de synchronisation. Le module s'appuie sur les briques déjà en place :
- le registre des connecteurs (BE-160) pour le connecteur porteur du lien ;
- le coffre de secrets (BE-161, `SecretStore`) : la valeur n'entre jamais en base ;
- les permissions `integrations.read` et `integrations.manage` (BE-162).

Règles tenues par ce module :
- CA-1 : une clé distante doit être composée `fournisseur/compte/ressource`, où le
  fournisseur et le compte sont ceux du lien. Une clé nue est refusée (422) avant toute
  écriture (`verifier_cle_composee`).
- CA-2 : la déconnexion retire les valeurs du coffre (`SecretStore.supprimer`) : la
  résolution pour un envoi échoue ensuite (404 `secret_integration_absent`, BE-161).
- CA-3 : un lien n'est visible et modifiable que par son tenant. Pour un autre tenant il est
  introuvable (404), jamais « refusé », afin de ne pas révéler son existence.
- CA-4 : sans `integrations.manage`, connexion et déconnexion sont refusées (403) avant
  toute écriture ; la lecture exige `integrations.read`.
- CA-5 : la réconciliation lit la vérité amont en lecture seule. Une erreur du fournisseur
  n'altère ni le curseur, ni le statut du lien, ni l'amont : elle est seulement consignée
  (`statutReconciliation = 'echec'`).

Un adaptateur par fournisseur (module `app/integrations/<fournisseur>/`) implémente le
protocole `AdaptateurSynchronisation`. Ce module ne connaît aucun fournisseur précis, sauf la
liste `FOURNISSEURS_CONNUS` qui borne les valeurs acceptées.

Les fonctions ne commitent pas : l'appelant gère la transaction.
"""

import datetime as dt
import logging
import re
import uuid
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.core.errors import AppError
from app.core.secrets import SecretStore
from app.integrations.models import IntegrationLink, SecretIntegration
from app.integrations.permissions import INTEGRATIONS_MANAGE, INTEGRATIONS_READ
from app.integrations.registre import creer_connecteur
from app.integrations.secrets import enregistrer_secret
from app.rbac.service import user_has_permission

logger = logging.getLogger(__name__)

STATUT_CONNECTEE = "connectée"
STATUT_DECONNECTEE = "déconnectée"
STATUT_RECONCILIATION_SUCCES = "succes"
STATUT_RECONCILIATION_ECHEC = "echec"

# Fournisseurs reconnus. La définition ne nomme pas le fournisseur (Q-07) : l'unique adaptateur
# existant est retenu, les autres s'ajouteront ici avec leur adaptateur.
FOURNISSEURS_CONNUS: frozenset[str] = frozenset({"holykell"})

_SEGMENT_COMPTE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")


class AdaptateurSynchronisation(Protocol):
    """Contrat d'un adaptateur de fournisseur pour la réconciliation (BE-239, CA-5).

    `lire_changements` interroge l'amont à partir du curseur courant et rend le nouveau curseur
    et la liste des changements. Il ne doit rien modifier côté amont. Toute exception signale
    une erreur de synchronisation : elle est consignée, jamais propagée au métier.
    """

    async def lire_changements(self, remote_key: str, curseur: str | None) -> tuple[str, list[dict]]:
        """Nouveau curseur et changements depuis `curseur`, pour la clé `remote_key`."""
        ...


def verifier_cle_composee(provider: str, external_account: str, remote_key: str) -> None:
    """Refuse une clé distante qui n'est pas la référence composée du lien (CA-1).

    Forme attendue : `fournisseur/compte/ressource`, avec `fournisseur` et `compte` égaux à
    ceux du lien et `ressource` non vide. Une clé nue (`capteur-7`) ou rattachée à un autre
    compte est refusée en 422 : sans le compte, la clé ne désigne rien de façon unique.
    """
    prefixe = f"{provider}/{external_account}/"
    if not remote_key.startswith(prefixe) or len(remote_key) == len(prefixe):
        raise AppError(
            code="remote_key_non_composee",
            message="La clé distante doit être composée fournisseur/compte/ressource.",
            status_code=422,
        )


async def _exiger_permission(db: AsyncSession, identite: IdentiteEmettrice, code: str) -> None:
    """Refus 403 `PERMISSION_DENIED` si l'utilisateur n'a pas `code` dans le tenant (CA-4)."""
    if not await user_has_permission(db, identite.user_id, identite.organization_id, code):
        raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail=f"permission manquante : {code}")


async def _lien_du_tenant(db: AsyncSession, identite: IdentiteEmettrice, lien_id: uuid.UUID) -> IntegrationLink:
    """Lien demandé, uniquement s'il appartient au tenant de l'identité (CA-3).

    Un lien d'un autre tenant, ou inexistant, produit le même 404 : pas de fuite d'existence.
    """
    lien = await db.get(IntegrationLink, lien_id)
    if lien is None or lien.organizationId != identite.organization_id:
        raise AppError(code="integration_introuvable", message="Intégration introuvable.", status_code=404)
    return lien


async def connecter_integration(
    db: AsyncSession,
    store: SecretStore,
    identite: IdentiteEmettrice,
    provider: str,
    external_account: str,
    remote_key: str,
    secret_value: str,
    *,
    expire_at: dt.datetime | None = None,
) -> IntegrationLink:
    """Crée le lien, son connecteur et la première version du secret.

    Ordre, sans écriture avant la fin des contrôles :
    1. permission `integrations.manage` (CA-4) : 403 ;
    2. fournisseur connu : 422 `fournisseur_inconnu` ;
    3. format du compte et clé composée (CA-1) : 422 ;
    4. pas de lien actif pour ce compte dans ce tenant : 409 `integration_deja_connectee` ;
    5. connecteur tenant (BE-160), puis secret dans le coffre (BE-161) ;
    6. ligne `integration_links` avec la référence composée.

    Le tenant est celui de l'identité, jamais un paramètre fourni par le corps (CA-3).
    """
    await _exiger_permission(db, identite, INTEGRATIONS_MANAGE)
    if provider not in FOURNISSEURS_CONNUS:
        raise AppError(code="fournisseur_inconnu", message="Fournisseur d'intégration inconnu.", status_code=422)
    if not _SEGMENT_COMPTE.match(external_account):
        raise AppError(code="compte_externe_invalide", message="Compte externe invalide.", status_code=422)
    verifier_cle_composee(provider, external_account, remote_key)

    existant = (
        await db.execute(
            select(IntegrationLink.id).where(
                IntegrationLink.organizationId == identite.organization_id,
                IntegrationLink.provider == provider,
                IntegrationLink.externalAccount == external_account,
            )
        )
    ).scalar_one_or_none()
    if existant is not None:
        raise AppError(code="integration_deja_connectee", message="Ce compte est déjà connecté.", status_code=409)

    connecteur = await creer_connecteur(
        db,
        identite,
        portee="tenant",
        nom=f"{provider}:{external_account}",
        organization_id=identite.organization_id,
    )
    await enregistrer_secret(db, store, identite, connecteur.id, secret_value, expire_at=expire_at)

    lien = IntegrationLink(
        organizationId=identite.organization_id,
        connecteurId=connecteur.id,
        provider=provider,
        externalAccount=external_account,
        remoteKey=remote_key,
        statut=STATUT_CONNECTEE,
    )
    db.add(lien)
    await db.flush()
    return lien


async def deconnecter_integration(
    db: AsyncSession,
    store: SecretStore,
    identite: IdentiteEmettrice,
    lien_id: uuid.UUID,
) -> IntegrationLink:
    """Déconnecte le lien et retire toutes ses valeurs de secret du coffre (CA-2).

    La ligne reste en base (statut `déconnectée`) pour l'historique. Les références de
    `secret_integration` restent aussi, mais sans valeur derrière : toute résolution échoue.
    Idempotent : un lien déjà déconnecté est rendu tel quel.
    """
    await _exiger_permission(db, identite, INTEGRATIONS_MANAGE)
    lien = await _lien_du_tenant(db, identite, lien_id)
    if lien.statut == STATUT_DECONNECTEE:
        return lien

    references = (
        await db.execute(
            select(SecretIntegration.referenceSecret).where(SecretIntegration.connecteurId == lien.connecteurId)
        )
    ).scalars()
    for reference in references:
        store.supprimer(reference)

    lien.statut = STATUT_DECONNECTEE
    await db.flush()
    return lien


async def lister_integrations(
    db: AsyncSession,
    identite: IdentiteEmettrice,
    organization_id: uuid.UUID,
) -> Sequence[IntegrationLink]:
    """Liens du tenant demandé, du plus ancien au plus récent. Exige `integrations.read`.

    Ne renvoie jamais un lien d'un autre tenant, même si `organization_id` est fourni.
    """
    await _exiger_permission(db, identite, INTEGRATIONS_READ)
    if organization_id != identite.organization_id:
        raise ErreurCatalogue(CodeErreur.TENANT_MISMATCH, detail="liste d'un autre tenant")
    resultat = await db.execute(
        select(IntegrationLink)
        .where(IntegrationLink.organizationId == organization_id)
        .order_by(IntegrationLink.createdAt)
    )
    return resultat.scalars().all()


async def reconcilier_lien(
    db: AsyncSession,
    lien_id: uuid.UUID,
    adaptateur: AdaptateurSynchronisation,
    maintenant: dt.datetime,
) -> IntegrationLink:
    """Réconcilie le curseur d'un lien connecté avec l'amont (CA-5).

    - lien non connecté : rendu tel quel, aucune interrogation ;
    - succès : le curseur avance et `statutReconciliation` vaut `succes` ;
    - erreur de l'adaptateur : aucune exception n'est propagée. Le curseur, le statut du lien
      et l'amont restent inchangés ; seul `statutReconciliation = 'echec'` est consigné avec
      la date. Seul le type de l'erreur est journalisé, jamais son message (il peut contenir
      une donnée sensible).

    Les changements rendus par l'adaptateur ne sont pas appliqués ici : leur application
    métier relève de l'appelant, qui ne doit la faire qu'après un succès.
    """
    lien = await db.get(IntegrationLink, lien_id)
    if lien is None:
        raise AppError(code="integration_introuvable", message="Intégration introuvable.", status_code=404)
    if lien.statut != STATUT_CONNECTEE:
        return lien

    try:
        nouveau_curseur, _changements = await adaptateur.lire_changements(lien.remoteKey, lien.curseurSync)
    except Exception as erreur:  # noqa: BLE001 : toute erreur amont est consignée, jamais propagée (CA-5)
        logger.warning("réconciliation en échec, lien %s, type %s", lien.id, type(erreur).__name__)
        lien.statutReconciliation = STATUT_RECONCILIATION_ECHEC
        lien.derniereReconciliation = maintenant
    else:
        lien.curseurSync = nouveau_curseur
        lien.statutReconciliation = STATUT_RECONCILIATION_SUCCES
        lien.derniereReconciliation = maintenant
    await db.flush()
    return lien
