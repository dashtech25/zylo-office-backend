"""BE-161 : stockage séparé des secrets d'intégration.

Tests écrits d'après la définition `### BE-161` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : une valeur de secret factice n'apparaît dans aucune ligne de table, aucune ligne
  d'audit, aucune trace de journal ni aucun objet renvoyé par le service ;
- CA-2 : un secret expiré provoque `SECRET_EXPIRED` : aucune valeur n'est résolue pour l'envoi ;
- CA-3 : la lecture de valeur est refusée `403` (PERMISSION_DENIED) à un utilisateur,
  même administrateur ; seul le service d'intégration résout une valeur ;
- CA-4 (isolation tenant) : un secret du tenant A n'est jamais résolu pour le tenant B,
  et le tenant B ne peut pas en enregistrer sur le connecteur du tenant A.

Les routes relèvent de BE-162 : ces tests appellent directement le service.
"""

import datetime as dt
import logging
import uuid

import pytest
from sqlalchemy import inspect, select

from app.audit.ecriture import IdentiteEmettrice
from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.core.secrets import SecretStore
from app.identity.models import Organization, User
from app.integrations.models import Connecteur, SecretIntegration
from app.integrations.registre import creer_connecteur
from app.integrations.secrets import (
    SERVICE_INTEGRATION,
    enregistrer_secret,
    resoudre_secret_pour_envoi,
)


async def _identite(registered_user: dict, organization: dict) -> tuple[IdentiteEmettrice, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
    org_id = uuid.UUID(organization["id"])
    return IdentiteEmettrice(user_id=user.id, organization_id=org_id), org_id


async def _autre_organisation() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="Tenant B BE-161", slug=f"be161-b-{uuid.uuid4().hex[:10]}")
        db.add(organisation)
        await db.flush()
        org_id = organisation.id
        await db.commit()
    return org_id


async def _creer_connecteur(identite: IdentiteEmettrice, org_id: uuid.UUID) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        connecteur = await creer_connecteur(
            db,
            identite,
            portee="tenant",
            nom=f"Connecteur {uuid.uuid4().hex[:8]}",
            organization_id=org_id,
        )
        await db.commit()
        return connecteur.id


async def _enregistrer(store: SecretStore, identite: IdentiteEmettrice, connecteur_id: uuid.UUID, valeur: str, **kwargs):
    async with AsyncSessionLocal() as db:
        secret = await enregistrer_secret(db, store, identite, connecteur_id, valeur, **kwargs)
        await db.commit()
        return secret


def _attributs(objet) -> dict:
    """Valeurs de toutes les colonnes d'un objet ORM, par nom d'attribut."""
    return {attr.key: getattr(objet, attr.key) for attr in inspect(objet).mapper.column_attrs}


async def _toutes_les_sorties_persistees() -> str:
    """Texte de toutes les lignes des tables des secrets et de l'audit (aucun filtre)."""
    async with AsyncSessionLocal() as db:
        secrets = (await db.execute(select(SecretIntegration))).scalars().all()
        audits = (await db.execute(select(AuditEvent))).scalars().all()
    lignes = [repr(_attributs(ligne)) for ligne in [*secrets, *audits]]
    return "\n".join(lignes)


async def test_be161_ca1_valeur_absente_de_toutes_les_sorties(registered_user: dict, organization: dict, caplog):
    caplog.set_level(logging.DEBUG)
    identite, org_id = await _identite(registered_user, organization)
    connecteur_id = await _creer_connecteur(identite, org_id)
    store = SecretStore()
    valeur_v1 = f"VALEUR-FACTICE-V1-{uuid.uuid4().hex}"
    valeur_v2 = f"VALEUR-FACTICE-V2-{uuid.uuid4().hex}"

    premier = await _enregistrer(store, identite, connecteur_id, valeur_v1)
    rotation = await _enregistrer(store, identite, connecteur_id, valeur_v2)

    # La valeur existe bien dans le coffre (sinon le test serait vide de sens).
    assert store.valeur_courante(premier.referenceSecret) == valeur_v1
    assert store.valeur_courante(rotation.referenceSecret) == valeur_v2
    assert premier.referenceSecret != rotation.referenceSecret

    sorties = [
        await _toutes_les_sorties_persistees(),
        repr(_attributs(premier)),
        repr(_attributs(rotation)),
        caplog.text,
    ]
    for valeur in (valeur_v1, valeur_v2):
        for sortie in sorties:
            assert valeur not in sortie, "la valeur d'un secret ne doit figurer dans aucune sortie"


async def test_be161_ca2_secret_expire_provoque_secret_expired(registered_user: dict, organization: dict):
    identite, org_id = await _identite(registered_user, organization)
    connecteur_id = await _creer_connecteur(identite, org_id)
    store = SecretStore()
    maintenant = dt.datetime.now(dt.timezone.utc)
    valeur = f"VALEUR-FACTICE-EXPIRE-{uuid.uuid4().hex}"
    await _enregistrer(store, identite, connecteur_id, valeur, expire_at=maintenant + dt.timedelta(days=1))

    envois: list[str] = []
    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as info:
            valeur_envoi = await resoudre_secret_pour_envoi(
                db, store, SERVICE_INTEGRATION, connecteur_id, org_id, maintenant + dt.timedelta(days=2)
            )
            envois.append(valeur_envoi)
        await db.rollback()

    assert info.value.code == "SECRET_EXPIRED"
    assert info.value.status_code == 401
    assert envois == [], "un secret expiré ne doit jamais servir à un envoi"
    assert valeur not in str(info.value.message)


async def test_be161_ca3_lecture_de_valeur_refusee_a_un_utilisateur_meme_admin(
    registered_user: dict, organization: dict
):
    identite, org_id = await _identite(registered_user, organization)
    connecteur_id = await _creer_connecteur(identite, org_id)
    store = SecretStore()
    maintenant = dt.datetime.now(dt.timezone.utc)
    valeur = f"VALEUR-FACTICE-LECTURE-{uuid.uuid4().hex}"
    await _enregistrer(store, identite, connecteur_id, valeur)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as info:
            await resoudre_secret_pour_envoi(db, store, identite, connecteur_id, org_id, maintenant)
        await db.rollback()
    assert info.value.code == "PERMISSION_DENIED"
    assert info.value.status_code == 403
    assert valeur not in str(info.value.message)

    # Le service d'intégration, lui, résout bien la valeur courante (témoin du contrôle).
    async with AsyncSessionLocal() as db:
        resolue = await resoudre_secret_pour_envoi(db, store, SERVICE_INTEGRATION, connecteur_id, org_id, maintenant)
    assert resolue == valeur


async def test_be161_ca4_secret_tenant_a_jamais_resolu_pour_tenant_b(registered_user: dict, organization: dict):
    identite_a, org_a = await _identite(registered_user, organization)
    connecteur_id = await _creer_connecteur(identite_a, org_a)
    store = SecretStore()
    maintenant = dt.datetime.now(dt.timezone.utc)
    valeur = f"VALEUR-FACTICE-TENANT-A-{uuid.uuid4().hex}"
    await _enregistrer(store, identite_a, connecteur_id, valeur)

    org_b = await _autre_organisation()
    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as info:
            await resoudre_secret_pour_envoi(db, store, SERVICE_INTEGRATION, connecteur_id, org_b, maintenant)
        await db.rollback()
    assert info.value.code == "TENANT_MISMATCH"
    assert valeur not in str(info.value.message)

    identite_b = IdentiteEmettrice(user_id=identite_a.user_id, organization_id=org_b)
    with pytest.raises(AppError) as info_ecriture:
        await _enregistrer(store, identite_b, connecteur_id, f"AUTRE-{uuid.uuid4().hex}")
    assert info_ecriture.value.code == "TENANT_MISMATCH"

    async with AsyncSessionLocal() as db:
        nombre = len((await db.execute(select(SecretIntegration).where(SecretIntegration.connecteurId == connecteur_id))).all())
    assert nombre == 1, "le tenant B n'a rien écrit sur le connecteur du tenant A"
