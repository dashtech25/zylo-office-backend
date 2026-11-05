"""BE-052 : réconciliation des états incertains.

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-modules-droits.md,
section BE-052) avant le code. Critères CA-1 à CA-5.

Décisions de test (voir la docstring de `app.modules_registry.reconciliation`) :
- la console de réconciliation est montée sous `/api/v1/admin/reconciliations` (QE-MOD-01, recommandation
  appliquée) ;
- le droit `platform.reconciliation.resolve` est de portée plateforme : il est accordé par une
  allowlist d'environnement (`PLATFORM_RECONCILIATION_RESOLVE_USER_IDS`), posée ici par `monkeypatch`
  sans valeur réelle (QE-MOD-07/16) ;
- CA-5 : le moteur d'accessibilité effective (BE-053) n'existe pas encore. Le test porte sur la fonction
  de lecture `reconciliation_ouverte_pour` qui sera appelée par BE-053 ; le refus `RECONCILIATION_PENDING`
  lui-même est à tester avec BE-053.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, engine
from app.identity.models import User
from app.modules_registry.models import OrganizationModule
from app.modules_registry.reconciliation import (
    ouvrir_cas_si_contradiction,
    reconciliation_ouverte_pour,
    resoudre_cas,
)
from app.modules_registry.service import get_or_create_module
from app.modules_registry.models import ModuleReconciliation

URL_RECONCILIATIONS = "/api/v1/admin/reconciliations"
VARIABLE_RESOLVE = "PLATFORM_RECONCILIATION_RESOLVE_USER_IDS"
TYPE_SUJET = "tenant_module"


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    await engine.dispose()
    yield


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _donner_droit_resolve(monkeypatch, registered_user: dict) -> uuid.UUID:
    user_id = await _id_utilisateur(registered_user["email"])
    monkeypatch.setenv(VARIABLE_RESOLVE, str(user_id))
    return user_id


async def _retirer_droit_resolve(monkeypatch, registered_user: dict) -> None:
    monkeypatch.setenv(VARIABLE_RESOLVE, "")


def _entetes(registered_user: dict) -> dict:
    return {"Authorization": f"Bearer {registered_user['accessToken']}"}


async def _module_installe(organization: dict, statut: str = "active") -> tuple[str, uuid.UUID]:
    """Crée un module du catalogue et son activation pour l'organisation ; renvoie (code, id d'activation)."""
    code = f"mod-be052-{uuid.uuid4().hex[:10]}"
    async with AsyncSessionLocal() as db:
        await get_or_create_module(db, code=code, name="Module BE-052", description="Test de réconciliation")
        activation = OrganizationModule(organizationId=uuid.UUID(organization["id"]), moduleCode=code, status=statut)
        db.add(activation)
        await db.commit()
        return code, activation.id


async def _ouvrir_cas(organization: dict, subject_id: uuid.UUID, cle: str | None = None) -> ModuleReconciliation:
    async with AsyncSessionLocal() as db:
        cas = await ouvrir_cas_si_contradiction(
            db,
            subject_type=TYPE_SUJET,
            subject_id=subject_id,
            organization_id=uuid.UUID(organization["id"]),
            source_a="granted",
            source_b="removed",
            idempotency_key=cle or f"evt-{uuid.uuid4().hex}",
        )
        await db.commit()
        assert cas is not None
        return cas


async def _relire_cas(cas_id: uuid.UUID) -> ModuleReconciliation:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(ModuleReconciliation).where(ModuleReconciliation.id == cas_id))).scalar_one()


async def _etat_activation(activation_id: uuid.UUID) -> str:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(OrganizationModule.status).where(OrganizationModule.id == activation_id))).scalar_one()


async def _nombre_cas(organization: dict) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(func.count()).select_from(ModuleReconciliation).where(
                    ModuleReconciliation.organizationId == uuid.UUID(organization["id"])
                )
            )
        ).scalar_one()


async def test_ca1_source_contradictoire_ouvre_un_cas_open_sans_modifier_le_module(organization: dict):
    _, activation_id = await _module_installe(organization, statut="active")

    async with AsyncSessionLocal() as db:
        cas = await ouvrir_cas_si_contradiction(
            db,
            subject_type=TYPE_SUJET,
            subject_id=activation_id,
            organization_id=uuid.UUID(organization["id"]),
            source_a="granted",
            source_b="removed",
            idempotency_key=f"evt-{uuid.uuid4().hex}",
        )
        await db.commit()

    assert cas is not None
    assert cas.state == "open"
    assert cas.sourceA == "granted" and cas.sourceB == "removed"
    assert cas.openedAt is not None and cas.resolvedAt is None
    # La réconciliation ne touche jamais l'état du module : il reste `active`.
    assert await _etat_activation(activation_id) == "active"


async def test_ca1_sources_concordantes_n_ouvrent_aucun_cas(organization: dict):
    _, activation_id = await _module_installe(organization)

    async with AsyncSessionLocal() as db:
        cas = await ouvrir_cas_si_contradiction(
            db,
            subject_type=TYPE_SUJET,
            subject_id=activation_id,
            organization_id=uuid.UUID(organization["id"]),
            source_a="granted",
            source_b="granted",
            idempotency_key=f"evt-{uuid.uuid4().hex}",
        )
        await db.commit()

    assert cas is None
    assert await _nombre_cas(organization) == 0


async def test_ca2_doublon_d_evenement_ne_cree_pas_de_second_cas(organization: dict):
    _, activation_id = await _module_installe(organization)
    cle = f"evt-{uuid.uuid4().hex}"

    premier = await _ouvrir_cas(organization, activation_id, cle=cle)
    async with AsyncSessionLocal() as db:
        doublon = await ouvrir_cas_si_contradiction(
            db,
            subject_type=TYPE_SUJET,
            subject_id=activation_id,
            organization_id=uuid.UUID(organization["id"]),
            source_a="granted",
            source_b="removed",
            idempotency_key=cle,
        )
        await db.commit()

    assert doublon is not None and doublon.id == premier.id
    assert await _nombre_cas(organization) == 1


async def test_ca3_acteur_sans_droit_resolve_recoit_403(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    _, activation_id = await _module_installe(organization)
    cas = await _ouvrir_cas(organization, activation_id)
    await _retirer_droit_resolve(monkeypatch, registered_user)

    res = await client.post(
        f"{URL_RECONCILIATIONS}/{cas.id}/resolve",
        json={"resolution": "confirm_granted", "evidenceReference": "PV-2026-0001"},
        headers=_entetes(registered_user),
    )

    assert res.status_code == 403, res.text
    assert (await _relire_cas(cas.id)).state == "open"


async def test_ca3_acteur_sans_droit_ne_lit_pas_la_liste(client: AsyncClient, registered_user: dict, monkeypatch):
    await _retirer_droit_resolve(monkeypatch, registered_user)

    res = await client.get(f"{URL_RECONCILIATIONS}?state=open", headers=_entetes(registered_user))

    assert res.status_code == 403, res.text


async def test_ca4_resolution_sans_evidence_reference_renvoie_422(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    await _donner_droit_resolve(monkeypatch, registered_user)
    _, activation_id = await _module_installe(organization)
    cas = await _ouvrir_cas(organization, activation_id)

    absente = await client.post(
        f"{URL_RECONCILIATIONS}/{cas.id}/resolve",
        json={"resolution": "confirm_granted"},
        headers=_entetes(registered_user),
    )
    vide = await client.post(
        f"{URL_RECONCILIATIONS}/{cas.id}/resolve",
        json={"resolution": "confirm_granted", "evidenceReference": "   "},
        headers=_entetes(registered_user),
    )

    assert absente.status_code == 422, absente.text
    assert vide.status_code == 422, vide.text
    assert (await _relire_cas(cas.id)).state == "open"


async def test_resolution_hors_liste_renvoie_422(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    await _donner_droit_resolve(monkeypatch, registered_user)
    _, activation_id = await _module_installe(organization)
    cas = await _ouvrir_cas(organization, activation_id)

    res = await client.post(
        f"{URL_RECONCILIATIONS}/{cas.id}/resolve",
        json={"resolution": "devine_le_etat", "evidenceReference": "PV-2026-0002"},
        headers=_entetes(registered_user),
    )

    assert res.status_code == 422, res.text
    assert (await _relire_cas(cas.id)).state == "open"


@pytest.mark.parametrize(
    ("resolution", "etat_attendu"),
    [("confirm_granted", "resolved"), ("confirm_removed", "resolved"), ("escalate", "escalated")],
)
async def test_resolution_avec_preuve_ferme_le_cas(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch, resolution: str, etat_attendu: str
):
    user_id = await _donner_droit_resolve(monkeypatch, registered_user)
    _, activation_id = await _module_installe(organization)
    cas = await _ouvrir_cas(organization, activation_id)

    res = await client.post(
        f"{URL_RECONCILIATIONS}/{cas.id}/resolve",
        json={"resolution": resolution, "evidenceReference": "PV-2026-0003"},
        headers=_entetes(registered_user),
    )

    assert res.status_code == 200, res.text
    relu = await _relire_cas(cas.id)
    assert relu.state == etat_attendu
    assert relu.resolution == resolution
    assert relu.evidenceReference == "PV-2026-0003"
    assert relu.resolvedBy == user_id
    assert relu.resolvedAt is not None


async def test_resolution_d_un_cas_inconnu_renvoie_404(client: AsyncClient, registered_user: dict, monkeypatch):
    await _donner_droit_resolve(monkeypatch, registered_user)

    res = await client.post(
        f"{URL_RECONCILIATIONS}/{uuid.uuid4()}/resolve",
        json={"resolution": "confirm_granted", "evidenceReference": "PV-2026-0004"},
        headers=_entetes(registered_user),
    )

    assert res.status_code == 404, res.text


async def test_liste_des_cas_open_pour_l_acteur_autorise(client: AsyncClient, registered_user: dict, organization: dict, monkeypatch):
    await _donner_droit_resolve(monkeypatch, registered_user)
    _, activation_id = await _module_installe(organization)
    cas = await _ouvrir_cas(organization, activation_id)

    res = await client.get(f"{URL_RECONCILIATIONS}?state=open", headers=_entetes(registered_user))

    assert res.status_code == 200, res.text
    identifiants = {item["id"] for item in res.json()["items"]} if isinstance(res.json(), dict) else {i["id"] for i in res.json()}
    assert str(cas.id) in identifiants


async def test_ca5_cas_open_signale_une_reconciliation_pendante_jusqu_a_resolution(
    client: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    """Lecture sur laquelle s'appuie BE-053 pour refuser `RECONCILIATION_PENDING`."""
    await _donner_droit_resolve(monkeypatch, registered_user)
    _, activation_id = await _module_installe(organization)
    organisation_id = uuid.UUID(organization["id"])
    cas = await _ouvrir_cas(organization, activation_id)

    async with AsyncSessionLocal() as db:
        pendant = await reconciliation_ouverte_pour(db, organisation_id, TYPE_SUJET, activation_id)
    assert pendant is True

    await client.post(
        f"{URL_RECONCILIATIONS}/{cas.id}/resolve",
        json={"resolution": "confirm_granted", "evidenceReference": "PV-2026-0005"},
        headers=_entetes(registered_user),
    )

    async with AsyncSessionLocal() as db:
        apres = await reconciliation_ouverte_pour(db, organisation_id, TYPE_SUJET, activation_id)
    assert apres is False
