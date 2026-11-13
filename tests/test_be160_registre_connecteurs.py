"""BE-160 : registre des connecteurs et de leurs états.

Tests écrits d'après la définition `### BE-160` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Couverture :
- CA-1 : chaque changement d'état (création, activation, suspension, révocation) écrit
  une ligne d'audit `EVT-INT-01` ;
- CA-2 : une transition interdite (révoqué vers activé, etc.) est refusée `409` et
  n'écrit rien ;
- CA-3 : une reprise de configuration n'est possible que si la configuration est validée ;
- CA-4 : isolation tenant (un connecteur tenant A n'est jamais listé pour le tenant B) et
  un connecteur global n'est modifiable que par l'administration plateforme.

Les routes sont exposées par BE-162 : ces tests appellent directement le service.
"""

import uuid

import pytest
from sqlalchemy import select

from app.audit.ecriture import IdentiteEmettrice
from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.identity.models import Organization
from app.integrations.registre import (
    ETAT_ACTIVE,
    ETAT_CREATION,
    ETAT_REVOQUE,
    ETAT_SUSPENDU,
    ConfigurationConnecteurNonValidee,
    TransitionConnecteurInterdite,
    changer_etat,
    creer_connecteur,
    lister_connecteurs,
    reprendre_configuration,
)
from app.integrations.models import Connecteur
from app.identity.models import User


async def _identite(registered_user: dict, organization: dict) -> tuple[IdentiteEmettrice, uuid.UUID]:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
    org_id = uuid.UUID(organization["id"])
    return IdentiteEmettrice(user_id=user.id, organization_id=org_id), org_id


async def _autre_organisation() -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        organisation = Organization(name="Tenant B BE-160", slug=f"be160-b-{uuid.uuid4().hex[:10]}")
        db.add(organisation)
        await db.flush()
        org_id = organisation.id
        await db.commit()
    return org_id


async def _creer(identite, org_id, *, portee="tenant", est_admin=False) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        connecteur = await creer_connecteur(
            db,
            identite,
            portee=portee,
            nom=f"Connecteur {uuid.uuid4().hex[:8]}",
            organization_id=org_id if portee == "tenant" else None,
            est_admin_plateforme=est_admin,
        )
        await db.commit()
        return connecteur.id


async def _etat(connecteur_id: uuid.UUID) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Connecteur.etat).where(Connecteur.id == connecteur_id))).scalar_one()


async def _version(connecteur_id: uuid.UUID) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(Connecteur.versionConfiguration).where(Connecteur.id == connecteur_id))
        ).scalar_one()


async def _audits_connecteur(connecteur_id: uuid.UUID) -> list[AuditEvent]:
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            select(AuditEvent).where(AuditEvent.entityType == "Connecteur", AuditEvent.entityId == connecteur_id)
        )
        return list(resultat.scalars().all())


async def _changer(identite, connecteur_id: uuid.UUID, cible: str, est_admin: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        await changer_etat(db, identite, connecteur_id, cible, est_admin_plateforme=est_admin)
        await db.commit()


async def test_be160_ca1_chaque_changement_d_etat_ecrit_un_audit_evt_int_01(registered_user: dict, organization: dict):
    identite, org_id = await _identite(registered_user, organization)
    connecteur_id = await _creer(identite, org_id)

    await _changer(identite, connecteur_id, ETAT_ACTIVE)
    await _changer(identite, connecteur_id, ETAT_SUSPENDU)
    await _changer(identite, connecteur_id, ETAT_REVOQUE)

    audits = await _audits_connecteur(connecteur_id)
    assert len(audits) == 4, "création, activation, suspension, révocation : une ligne d'audit chacune"
    assert all(a.changes and a.changes.get("evenement") == "EVT-INT-01" for a in audits)
    assert await _etat(connecteur_id) == ETAT_REVOQUE


async def test_be160_ca2_transition_revoque_vers_active_refusee_409_sans_ecriture(registered_user: dict, organization: dict):
    identite, org_id = await _identite(registered_user, organization)
    connecteur_id = await _creer(identite, org_id)
    await _changer(identite, connecteur_id, ETAT_REVOQUE)
    nombre_audits_avant = len(await _audits_connecteur(connecteur_id))

    async with AsyncSessionLocal() as db:
        with pytest.raises(TransitionConnecteurInterdite) as info:
            await changer_etat(db, identite, connecteur_id, ETAT_ACTIVE)
        await db.rollback()

    assert info.value.status_code == 409
    assert await _etat(connecteur_id) == ETAT_REVOQUE, "une transition interdite ne modifie pas l'état"
    assert len(await _audits_connecteur(connecteur_id)) == nombre_audits_avant, "une transition interdite n'écrit rien"


@pytest.mark.parametrize(
    ("etat_depart", "cible_interdite"),
    [
        (ETAT_CREATION, ETAT_SUSPENDU),
        (ETAT_REVOQUE, ETAT_SUSPENDU),
        (ETAT_SUSPENDU, ETAT_CREATION),
    ],
)
async def test_be160_ca2_autres_transitions_interdites_refusees(
    registered_user: dict, organization: dict, etat_depart: str, cible_interdite: str
):
    identite, org_id = await _identite(registered_user, organization)
    connecteur_id = await _creer(identite, org_id)
    if etat_depart == ETAT_SUSPENDU:
        await _changer(identite, connecteur_id, ETAT_ACTIVE)
        await _changer(identite, connecteur_id, ETAT_SUSPENDU)
    elif etat_depart == ETAT_REVOQUE:
        await _changer(identite, connecteur_id, ETAT_REVOQUE)
    assert await _etat(connecteur_id) == etat_depart

    async with AsyncSessionLocal() as db:
        with pytest.raises(TransitionConnecteurInterdite):
            await changer_etat(db, identite, connecteur_id, cible_interdite)
        await db.rollback()

    assert await _etat(connecteur_id) == etat_depart


async def test_be160_ca3_reprise_refusee_si_configuration_non_validee(registered_user: dict, organization: dict):
    identite, org_id = await _identite(registered_user, organization)
    connecteur_id = await _creer(identite, org_id)
    version_avant = await _version(connecteur_id)
    nombre_audits_avant = len(await _audits_connecteur(connecteur_id))

    async with AsyncSessionLocal() as db:
        with pytest.raises(ConfigurationConnecteurNonValidee):
            await reprendre_configuration(db, identite, connecteur_id, version_avant + 1, validee=False)
        await db.rollback()

    assert await _version(connecteur_id) == version_avant, "la reprise refusée ne change pas la configuration"
    assert len(await _audits_connecteur(connecteur_id)) == nombre_audits_avant


async def test_be160_ca3_reprise_acceptee_si_configuration_validee(registered_user: dict, organization: dict):
    identite, org_id = await _identite(registered_user, organization)
    connecteur_id = await _creer(identite, org_id)
    version_cible = (await _version(connecteur_id)) + 1

    async with AsyncSessionLocal() as db:
        await reprendre_configuration(db, identite, connecteur_id, version_cible, validee=True)
        await db.commit()

    assert await _version(connecteur_id) == version_cible
    audits = await _audits_connecteur(connecteur_id)
    assert any(a.changes and a.changes.get("evenement") == "EVT-INT-01" for a in audits)


async def test_be160_ca4_connecteur_tenant_jamais_liste_pour_un_autre_tenant(registered_user: dict, organization: dict):
    identite, org_id = await _identite(registered_user, organization)
    autre_org_id = await _autre_organisation()
    connecteur_a = await _creer(identite, org_id)
    identite_b = IdentiteEmettrice(user_id=identite.user_id, organization_id=autre_org_id)
    connecteur_b = await _creer(identite_b, autre_org_id)

    async with AsyncSessionLocal() as db:
        ids_a = {c.id for c in await lister_connecteurs(db, org_id)}
        ids_b = {c.id for c in await lister_connecteurs(db, autre_org_id)}

    assert connecteur_a in ids_a
    assert connecteur_a not in ids_b, "un connecteur tenant A n'est jamais listé pour le tenant B"
    assert connecteur_b in ids_b
    assert connecteur_b not in ids_a


async def test_be160_ca4_connecteur_tenant_modifie_par_un_autre_tenant_refuse(registered_user: dict, organization: dict):
    identite, org_id = await _identite(registered_user, organization)
    autre_org_id = await _autre_organisation()
    connecteur_a = await _creer(identite, org_id)
    etat_avant = await _etat(connecteur_a)
    identite_b = IdentiteEmettrice(user_id=identite.user_id, organization_id=autre_org_id)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as info:
            await changer_etat(db, identite_b, connecteur_a, ETAT_ACTIVE)
        await db.rollback()

    assert info.value.code == "TENANT_MISMATCH"
    assert await _etat(connecteur_a) == etat_avant


async def test_be160_ca4_connecteur_global_refuse_a_un_admin_tenant(registered_user: dict, organization: dict):
    identite, org_id = await _identite(registered_user, organization)
    connecteur_global = await _creer(identite, org_id, portee="global", est_admin=True)
    etat_avant = await _etat(connecteur_global)

    async with AsyncSessionLocal() as db:
        with pytest.raises(AppError) as info:
            await changer_etat(db, identite, connecteur_global, ETAT_ACTIVE, est_admin_plateforme=False)
        await db.rollback()

    assert info.value.code == "PERMISSION_DENIED"
    assert info.value.status_code == 403
    assert await _etat(connecteur_global) == etat_avant
