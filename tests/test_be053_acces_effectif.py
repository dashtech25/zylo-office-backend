"""BE-053 : moteur d'accessibilité effective.

Couvre les critères d'acceptation de la définition BE-053
(implementation-backend/tasks-modules-droits.md, section BE-053) :
- CA-1 : membre sans la permission -> deny / PERMISSION_MISSING (fonction pure, puis base) ;
- CA-2 : module inactif ou suspendu -> deny / MODULE_NOT_ACTIVE même avec la permission ;
- CA-3 : capacité exigeant un entitlement absent -> deny / ENTITLEMENT_REQUIRED ; capacité
  ne l'exigeant pas -> pas de refus pour cette raison (flag par capacité, QE-MOD-14) ;
- CA-4 : l'évaluation n'écrit aucune ligne en base ;
- CA-5 : organisation hors périmètre -> 404 sans motif révélant l'existence de l'autre tenant ;
- CA-6 : action mutante sans politique déclarée -> refus par défaut (QE-MOD-06).

Les pièces qui dépendent d'un abonnement réel ne sont pas montées : l'absence
d'entitlement est simplement l'état réel d'une organisation sans abonnement. Aucun
test n'est sauté.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, Base, engine
from app.identity.models import OrganizationUser, User
from app.modules_registry.models import Module, OrganizationModule
from app.modules_registry.reconciliation import ouvrir_cas_si_contradiction
from app.modules_registry.service import get_or_create_module, grant_module_permissions_to_owner
from app.rbac.acces_effectif import (
    ENTITLEMENT_REQUIS,
    MODULE_NON_ACTIF,
    MOTIF_NON_MEMBRE,
    PERMISSION_MANQUANTE,
    POLITIQUE_ABSENTE,
    QUOTA_DEPASSE,
    RECONCILIATION_EN_ATTENTE,
    FaitsAcces,
    evaluer_acces,
    evaluer_acces_effectif,
)
from app.rbac.service import get_or_create_permission

TYPE_SUJET = "tenant_module"


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    await engine.dispose()
    yield
    await engine.dispose()


# ---------------------------------------------------------------------------
# Fonction pure : aucune base, aucun appel réseau.
# ---------------------------------------------------------------------------


def _faits(**surcharge) -> FaitsAcces:
    base = dict(
        membre_actif=True,
        permission_accordee=True,
        module_actif=True,
        reconciliation_pendante=False,
        capacite_exige_entitlement=False,
        entitlement_valide=True,
        quota_conforme=None,
        action_mutante=True,
        politique_declaree=True,
    )
    base.update(surcharge)
    return FaitsAcces(**base)


def test_ca1_permission_absente_donne_deny_permission_missing():
    decision = evaluer_acces(_faits(permission_accordee=False))
    assert decision.autorise is False
    assert decision.motif == PERMISSION_MANQUANTE == "PERMISSION_MISSING"


def test_ca2_module_inactif_refuse_meme_si_la_permission_existe():
    decision = evaluer_acces(_faits(module_actif=False, permission_accordee=True))
    assert decision.autorise is False
    assert decision.motif == MODULE_NON_ACTIF == "MODULE_NOT_ACTIVE"


def test_ca3_capacite_exigeant_un_entitlement_absent_donne_entitlement_required():
    decision = evaluer_acces(_faits(capacite_exige_entitlement=True, entitlement_valide=False))
    assert decision.autorise is False
    assert decision.motif == ENTITLEMENT_REQUIS == "ENTITLEMENT_REQUIRED"


def test_ca3_capacite_ne_l_exigeant_pas_n_est_pas_refusee_sans_entitlement():
    decision = evaluer_acces(_faits(capacite_exige_entitlement=False, entitlement_valide=False))
    assert decision.autorise is True
    assert decision.motif is None


def test_qe14_capacite_non_declaree_est_refusee_sans_entitlement_fail_closed():
    """Sans déclaration (None), la capacité est traitée comme exigeant un entitlement."""
    refus = evaluer_acces(_faits(capacite_exige_entitlement=None, entitlement_valide=False))
    accord = evaluer_acces(_faits(capacite_exige_entitlement=None, entitlement_valide=True))
    assert refus.motif == ENTITLEMENT_REQUIS
    assert accord.autorise is True


def test_ca6_action_mutante_sans_politique_declaree_est_refusee_par_defaut():
    decision = evaluer_acces(_faits(action_mutante=True, politique_declaree=False))
    assert decision.autorise is False
    assert decision.motif == POLITIQUE_ABSENTE == "POLICY_MISSING"


def test_ca6_lecture_sans_politique_n_est_pas_refusee_pour_ce_motif():
    decision = evaluer_acces(_faits(action_mutante=False, politique_declaree=False))
    assert decision.autorise is True


def test_reconciliation_pendante_refuse_avec_motif_stable():
    decision = evaluer_acces(_faits(reconciliation_pendante=True))
    assert decision.autorise is False
    assert decision.motif == RECONCILIATION_EN_ATTENTE == "RECONCILIATION_PENDING"


def test_quota_depasse_refuse_et_quota_non_evalue_ne_refuse_pas():
    assert evaluer_acces(_faits(quota_conforme=False)).motif == QUOTA_DEPASSE == "QUOTA_EXCEEDED"
    assert evaluer_acces(_faits(quota_conforme=None)).autorise is True


def test_non_membre_prime_sur_les_autres_motifs():
    decision = evaluer_acces(_faits(membre_actif=False, permission_accordee=False, module_actif=False))
    assert decision.autorise is False
    assert decision.motif == MOTIF_NON_MEMBRE == "NOT_MEMBER"


# ---------------------------------------------------------------------------
# Données de base : un module du registre, son activation, une permission déclarée
# par ce module, accordée au owner comme à l'activation réelle.
# ---------------------------------------------------------------------------


async def _module_active(organization: dict, statut: str = "active") -> tuple[str, str]:
    """Crée le module, son activation (statut donné) et sa permission ; renvoie (code, permission)."""
    suffixe = uuid.uuid4().hex[:10]
    code = f"be053{suffixe}"
    permission = f"be053{suffixe}.dossier.manage"
    async with AsyncSessionLocal() as db:
        await get_or_create_module(db, code=code, name="Module BE-053", description="Test d'accessibilité")
        await get_or_create_permission(db, code=permission, module_code=code, description="BE-053")
        db.add(OrganizationModule(organizationId=uuid.UUID(organization["id"]), moduleCode=code, status=statut))
        await db.flush()
        await grant_module_permissions_to_owner(db, uuid.UUID(organization["id"]), code)
        await db.commit()
    return code, permission


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _membre_sans_role(email: str, organization: dict) -> None:
    """Rattache l'utilisateur à l'organisation sans lui donner aucun rôle."""
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db.add(OrganizationUser(organizationId=uuid.UUID(organization["id"]), userId=user.id))
        await db.commit()


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": f"Bearer {utilisateur['accessToken']}"}


def _url(organization: dict, code: str) -> str:
    return f"/api/v1/organizations/{organization['id']}/modules/{code}/access-evaluation"


async def _evaluer(organization: dict, user_id: uuid.UUID, code: str, permission: str, capacites=None):
    async with AsyncSessionLocal() as db:
        return await evaluer_acces_effectif(
            db,
            user_id=user_id,
            organization_id=uuid.UUID(organization["id"]),
            module_code=code,
            action=permission,
            capacites=capacites,
        )


async def _compter_toutes_les_lignes() -> dict[str, int]:
    """Nombre de lignes par table : sert à prouver qu'une évaluation n'écrit rien (CA-4)."""
    async with AsyncSessionLocal() as db:
        compte = {}
        for table in Base.metadata.sorted_tables:
            compte[table.name] = (await db.execute(select(func.count()).select_from(table))).scalar_one()
        return compte


# ---------------------------------------------------------------------------
# Base de données.
# ---------------------------------------------------------------------------


async def test_ca1_membre_sans_role_recoit_permission_missing_en_base(
    client: AsyncClient, registered_user: dict, organization: dict
):
    autre = {"email": f"be053-membre-{uuid.uuid4().hex[:8]}@example.com", "password": "TestPassword123!"}
    await client.post("/api/v1/auth/register", json={**autre, "fullName": "Membre"})
    await _membre_sans_role(autre["email"], organization)
    code, permission = await _module_active(organization)

    decision = await _evaluer(organization, await _id_utilisateur(autre["email"]), code, permission, {permission: False})

    assert decision.autorise is False
    assert decision.motif == "PERMISSION_MISSING"


async def test_ca2_module_suspendu_donne_module_not_active_meme_avec_permission(
    client: AsyncClient, registered_user: dict, organization: dict
):
    code, permission = await _module_active(organization, statut="suspended")
    owner_id = await _id_utilisateur(registered_user["email"])

    decision = await _evaluer(organization, owner_id, code, permission, {permission: False})

    assert decision.autorise is False
    assert decision.motif == "MODULE_NOT_ACTIVE"


async def test_ca3_capacite_exigeant_entitlement_sans_abonnement_donne_entitlement_required(
    client: AsyncClient, registered_user: dict, organization: dict
):
    code, permission = await _module_active(organization)
    owner_id = await _id_utilisateur(registered_user["email"])

    decision = await _evaluer(organization, owner_id, code, permission, {permission: True})

    assert decision.autorise is False
    assert decision.motif == "ENTITLEMENT_REQUIRED"


async def test_module_actif_owner_et_capacite_sans_entitlement_exige_est_autorise(
    client: AsyncClient, registered_user: dict, organization: dict
):
    code, permission = await _module_active(organization)
    owner_id = await _id_utilisateur(registered_user["email"])

    decision = await _evaluer(organization, owner_id, code, permission, {permission: False})

    assert decision.autorise is True
    assert decision.motif is None


async def test_ca4_evaluation_par_route_n_ecrit_aucune_ligne(client: AsyncClient, registered_user: dict, organization: dict):
    code, permission = await _module_active(organization)
    avant = await _compter_toutes_les_lignes()

    reponse = await client.get(_url(organization, code), params={"action": permission}, headers=_entetes(registered_user))

    assert reponse.status_code == 200
    assert await _compter_toutes_les_lignes() == avant


async def test_ca5_organisation_etrangere_renvoie_404_sans_motif_revelant_le_tenant(
    client: AsyncClient, registered_user: dict, organization: dict
):
    autre = {"email": f"be053-autre-{uuid.uuid4().hex[:8]}@example.com", "password": "TestPassword123!"}
    await client.post("/api/v1/auth/register", json={**autre, "fullName": "Autre"})
    login = await client.post("/api/v1/auth/login", json=autre)
    entetes_autre = {"Authorization": f"Bearer {login.json()['accessToken']}"}
    org_b = await client.post(
        "/api/v1/organizations", json={"name": "Org B", "slug": f"org-b-{uuid.uuid4().hex[:8]}"}, headers=entetes_autre
    )
    org_b_id = org_b.json()["id"]
    code, permission = await _module_active(organization)

    reponse = await client.get(
        f"/api/v1/organizations/{org_b_id}/modules/{code}/access-evaluation",
        params={"action": permission},
        headers=_entetes(registered_user),
    )

    assert reponse.status_code == 404
    corps = reponse.text
    assert "decision" not in corps
    assert "reason" not in corps
    assert org_b_id not in corps


async def test_route_reservee_aux_administrateurs_refuse_un_membre_sans_droit(
    client: AsyncClient, registered_user: dict, organization: dict
):
    membre = {"email": f"be053-simple-{uuid.uuid4().hex[:8]}@example.com", "password": "TestPassword123!"}
    await client.post("/api/v1/auth/register", json={**membre, "fullName": "Simple"})
    login = await client.post("/api/v1/auth/login", json=membre)
    await _membre_sans_role(membre["email"], organization)
    code, permission = await _module_active(organization)

    reponse = await client.get(
        _url(organization, code),
        params={"action": permission},
        headers={"Authorization": f"Bearer {login.json()['accessToken']}"},
    )

    assert reponse.status_code == 403


async def test_route_renvoie_allow_ou_deny_avec_motif_stable(client: AsyncClient, registered_user: dict, organization: dict):
    code, permission = await _module_active(organization)

    reponse = await client.get(_url(organization, code), params={"action": permission}, headers=_entetes(registered_user))

    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["decision"] == "deny"
    assert corps["reason"] == "ENTITLEMENT_REQUIRED"


async def test_reconciliation_ouverte_donne_reconciliation_pending(client: AsyncClient, registered_user: dict, organization: dict):
    code, permission = await _module_active(organization)
    owner_id = await _id_utilisateur(registered_user["email"])
    async with AsyncSessionLocal() as db:
        activation = (
            await db.execute(
                select(OrganizationModule.id).where(
                    OrganizationModule.organizationId == uuid.UUID(organization["id"]),
                    OrganizationModule.moduleCode == code,
                )
            )
        ).scalar_one()
        await ouvrir_cas_si_contradiction(
            db,
            subject_type=TYPE_SUJET,
            subject_id=activation,
            organization_id=uuid.UUID(organization["id"]),
            source_a="granted",
            source_b="removed",
            idempotency_key=f"be053-{uuid.uuid4().hex}",
        )
        await db.commit()

    decision = await _evaluer(organization, owner_id, code, permission, {permission: True})

    assert decision.autorise is False
    assert decision.motif == "RECONCILIATION_PENDING"
