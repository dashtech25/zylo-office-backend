"""BE-056 : événements et audit des transitions de module.

Tests écrits d'après la définition de la tâche (implementation-backend/tasks-modules-droits.md,
section BE-056) avant le code. Critères couverts :
- CA-1 : chaque transition réussie produit exactement un événement avec scope, acteur,
  `correlationId` ; un rejeu ou une transition refusée n'en produit aucun ;
- CA-2 : un payload contenant un champ secret est rejeté avant écriture ;
- CA-3 : un membre sans `organization.audit.read` reçoit 403 ;
- CA-4 : isolation tenant : le journal de B n'est jamais renvoyé à un acteur de A (404) ;
- CA-5 : le filtre `moduleId` ne renvoie que les événements du module demandé dans le tenant.

Route testée : GET /api/v1/organizations/{organization_id}/module-audit?from=&to=&moduleId=.
Les événements sont écrits dans la table unique `audit_event` (BE-007), dont la migration
de BE-056 ajoute les colonnes `subjectType`, `subjectId`, `eventName`, `origin`, `correlationId`,
`payloadMinimal` et l'index `(organizationId, createdAt)`.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal, engine
from app.core.errors import AppError
from app.identity.models import OrganizationUser, User

MOT_DE_PASSE = "TestPassword123!"
TYPE_SUJET = "tenant_module"
EVENEMENTS_ATTENDUS = {
    "ModuleVersionPublished",
    "TenantModuleAvailabilityChanged",
    "ModuleInstallationStateChanged",
    "EntitlementAllocationChanged",
    "ModuleSuspended",
    "ModuleReactivated",
    "ModuleUninstalled",
}


@pytest.fixture(autouse=True)
async def _pool_neuf_par_test():
    """Le moteur est un singleton lié à la boucle qui l'a ouvert : un pool neuf par test."""
    await engine.dispose()
    yield
    await engine.dispose()


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def _id_utilisateur(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(User.id).where(User.email == email))).scalar_one()


async def _transition(
    db,
    *,
    organisation: uuid.UUID,
    module: uuid.UUID,
    sujet: uuid.UUID,
    vers_etat: str,
    version: int,
    cle: str,
    acteur: uuid.UUID,
):
    from app.modules_registry.transitions import transitionner

    return await transitionner(
        db,
        type_sujet=TYPE_SUJET,
        id_sujet=sujet,
        vers_etat=vers_etat,
        version_attendue=version,
        acteur_id=acteur,
        origine="client",
        cle_idempotence=cle,
        organisation_id=organisation,
        module_id=module,
    )


async def _evenements_du_sujet(sujet: uuid.UUID) -> list[AuditEvent]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(AuditEvent).where(AuditEvent.subjectId == sujet).order_by(AuditEvent.createdAt)
                )
            ).scalars().all()
        )


async def _membre_sans_droit(client: AsyncClient, organization_id: uuid.UUID) -> str:
    """Crée un utilisateur rattaché à l'organisation sans rôle ; retourne son jeton."""
    email = f"be056-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Membre BE-056"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=await _id_utilisateur(email)))
        await db.commit()
    return login.json()["accessToken"]


async def _organisation_de(client: AsyncClient, token: str) -> dict:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": "Org BE-056", "slug": f"be056-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


async def test_colonnes_et_index_ajoutes_a_audit_event_par_la_migration():
    """Prérequis du journal d'événements : colonnes de BE-056 et index (organizationId, createdAt)."""
    async with AsyncSessionLocal() as db:
        colonnes = {
            ligne[0]
            for ligne in (
                await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'audit_event'"))
            ).all()
        }
        index = {
            ligne[0]
            for ligne in (await db.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'audit_event'"))).all()
        }
    assert {"subjectType", "subjectId", "eventName", "origin", "correlationId", "payloadMinimal"} <= colonnes
    assert "ix_audit_event_organizationId_createdAt" in index


async def test_ca1_transition_reussie_produit_exactement_un_evenement_avec_scope_acteur_et_correlation(
    client: AsyncClient, registered_user: dict, organization: dict
):
    organisation = uuid.UUID(organization["id"])
    acteur = await _id_utilisateur(registered_user["email"])
    module = uuid.uuid4()
    sujet = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        await _transition(db, organisation=organisation, module=module, sujet=sujet,
                          vers_etat="provisioning", version=0, cle="ca1-evt-1", acteur=acteur)
        await db.commit()

    evenements = await _evenements_du_sujet(sujet)
    assert len(evenements) == 1
    evenement = evenements[0]
    assert evenement.eventName in EVENEMENTS_ATTENDUS
    assert evenement.organizationId == organisation
    assert evenement.actorUserId == acteur
    assert evenement.scopeResourceType == "module"
    assert evenement.scopeResourceId == module
    assert evenement.origin == "client"
    assert evenement.correlationId


async def test_ca1_rejeu_et_transition_refusee_ne_produisent_aucun_evenement_supplementaire(
    client: AsyncClient, registered_user: dict, organization: dict
):
    organisation = uuid.UUID(organization["id"])
    acteur = await _id_utilisateur(registered_user["email"])
    module = uuid.uuid4()
    sujet = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        await _transition(db, organisation=organisation, module=module, sujet=sujet,
                          vers_etat="provisioning", version=0, cle="ca1-rejeu", acteur=acteur)
        await _transition(db, organisation=organisation, module=module, sujet=sujet,
                          vers_etat="provisioning", version=0, cle="ca1-rejeu", acteur=acteur)
        from app.modules_registry.transitions import transitionner

        with pytest.raises(AppError):
            await transitionner(
                db, type_sujet=TYPE_SUJET, id_sujet=sujet, vers_etat="active", version_attendue=1,
                acteur_id=acteur, origine="client", cle_idempotence="ca1-saut",
                organisation_id=organisation, module_id=module,
            )
        await db.commit()

    assert len(await _evenements_du_sujet(sujet)) == 1


async def test_ca1_nom_d_evenement_selon_la_transition(client: AsyncClient, registered_user: dict, organization: dict):
    organisation = uuid.UUID(organization["id"])
    acteur = await _id_utilisateur(registered_user["email"])
    module = uuid.uuid4()
    sujet = uuid.uuid4()
    chemin = [("provisioning", 0), ("installed", 1), ("active", 2), ("suspended", 3), ("active", 4)]
    async with AsyncSessionLocal() as db:
        for vers_etat, version in chemin:
            await _transition(db, organisation=organisation, module=module, sujet=sujet,
                              vers_etat=vers_etat, version=version, cle=f"ca1-nom-{version}", acteur=acteur)
        await db.commit()

    noms = [evenement.eventName for evenement in await _evenements_du_sujet(sujet)]
    assert noms[3] == "ModuleSuspended"
    assert noms[4] == "ModuleReactivated"
    assert len(noms) == 5


async def test_ca2_payload_contenant_un_secret_est_rejete_avant_ecriture(
    client: AsyncClient, registered_user: dict, organization: dict
):
    from app.modules_registry.evenements import publier_evenement

    organisation = uuid.UUID(organization["id"])
    acteur = await _id_utilisateur(registered_user["email"])
    sujet = uuid.uuid4()
    payloads = [
        {"motDePasse": "secret-clair"},
        {"accessToken": "jeton"},
        {"installation": {"clientSecret": "valeur"}},
    ]
    async with AsyncSessionLocal() as db:
        for payload in payloads:
            with pytest.raises(AppError) as exc:
                await publier_evenement(
                    db, nom="ModuleSuspended", organisation_id=organisation, acteur_id=acteur,
                    type_sujet=TYPE_SUJET, id_sujet=sujet, origine="client", payload=payload,
                )
            assert exc.value.code == "EVENEMENT_PAYLOAD_SENSIBLE"
        await db.rollback()

    assert await _evenements_du_sujet(sujet) == []


async def test_ca3_membre_sans_audit_read_recoit_403(client: AsyncClient, registered_user: dict, organization: dict):
    organisation = uuid.UUID(organization["id"])
    token = await _membre_sans_droit(client, organisation)
    res = await client.get(
        f"/api/v1/organizations/{organization['id']}/module-audit",
        headers=_entete(token, organization["id"]),
    )
    assert res.status_code == 403


async def test_ca4_journal_de_b_jamais_renvoye_a_un_acteur_de_a(client: AsyncClient, registered_user: dict, organization: dict):
    organisation_a = uuid.UUID(organization["id"])
    autre = await _organisation_de(client, (await client.post(
        "/api/v1/auth/login",
        json={"email": registered_user["email"], "password": registered_user["password"]},
    )).json()["accessToken"])
    # Le propriétaire de A n'est pas membre de B : la route doit répondre 404 sur `orgId = B`.
    organisation_b = uuid.UUID(autre["id"])
    acteur_b = await _id_utilisateur(registered_user["email"])
    sujet_b = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        await _transition(db, organisation=organisation_b, module=uuid.uuid4(), sujet=sujet_b,
                          vers_etat="provisioning", version=0, cle="ca4-b", acteur=acteur_b)
        await db.commit()
    assert organisation_a != organisation_b

    res = await client.get(
        f"/api/v1/organizations/{organisation_b}/module-audit",
        headers=_entete(registered_user["accessToken"], str(organisation_b)),
    )
    assert res.status_code == 404
    assert str(sujet_b) not in res.text


async def test_ca5_filtre_module_id_ne_renvoie_que_le_module_demande_dans_le_tenant(
    client: AsyncClient, registered_user: dict, organization: dict
):
    organisation = uuid.UUID(organization["id"])
    acteur = await _id_utilisateur(registered_user["email"])
    module_1, module_2 = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        await _transition(db, organisation=organisation, module=module_1, sujet=uuid.uuid4(),
                          vers_etat="provisioning", version=0, cle="ca5-a", acteur=acteur)
        await _transition(db, organisation=organisation, module=module_1, sujet=uuid.uuid4(),
                          vers_etat="provisioning", version=0, cle="ca5-b", acteur=acteur)
        await _transition(db, organisation=organisation, module=module_2, sujet=uuid.uuid4(),
                          vers_etat="provisioning", version=0, cle="ca5-c", acteur=acteur)
        await db.commit()

    res = await client.get(
        f"/api/v1/organizations/{organization['id']}/module-audit",
        params={"moduleId": str(module_1)},
        headers=_entete(registered_user["accessToken"], organization["id"]),
    )
    assert res.status_code == 200, res.text
    donnees = res.json()["data"]
    assert len(donnees) == 2
    assert all(item["moduleId"] == str(module_1) for item in donnees)
